"""İcra İşlemleri ekranı: icra dosyalarının tür, aşama, haciz ve tebligat durumuna göre listesi."""

import datetime as dt
import re

from django.db.models import (
    Count,
    DateField,
    DateTimeField,
    F,
    IntegerField,
    Max,
    Min,
    OuterRef,
    Q,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from apps.core.permissions import filter_visible_cases
from apps.core.text import fold

from .models import Case, CaseStatus, CaseType, EnforcementType, Seizure

RENEWAL_WARNING_DAYS = 30


def enforcement_base(user=None):
    """Görünür icra takibi dosyaları; haciz, tebligat ve son işlem bilgileriyle."""
    from apps.imports.models import PortalNotice

    qs = Case.objects.filter(case_type=CaseType.ENFORCEMENT)
    if user is not None:
        qs = filter_visible_cases(qs, user)
    active = Seizure.objects.filter(case=OuterRef("pk"), is_active=True).order_by()
    notices = PortalNotice.objects.filter(resolution_case=OuterRef("pk")).order_by()
    return qs.annotate(
        seizure_count=Coalesce(
            Subquery(
                active.values("case").annotate(n=Count("pk")).values("n"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        next_renewal=Subquery(
            active.values("case").annotate(d=Min("renewal_on")).values("d"),
            output_field=DateField(),
        ),
        last_seizure_at=Subquery(
            Seizure.objects.filter(case=OuterRef("pk"))
            .order_by()
            .values("case")
            .annotate(d=Max("updated_at"))
            .values("d"),
            output_field=DateTimeField(),
        ),
        notice_count=Coalesce(
            Subquery(
                notices.values("resolution_case").annotate(n=Count("pk")).values("n"),
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        last_notice_at=Subquery(
            notices.values("resolution_case").annotate(d=Max("delivered_at")).values("d"),
            output_field=DateTimeField(),
        ),
    ).annotate(
        last_action=Greatest(
            "updated_at",
            Coalesce("last_seizure_at", "updated_at"),
            Coalesce("last_notice_at", "updated_at"),
        )
    )


def _renewal_limit():
    return timezone.localdate() + dt.timedelta(days=RENEWAL_WARNING_DAYS)


def enforcement_stats():
    """Modül başlığındaki özet: büro geneli, kullanıcıya göre değişmez."""
    qs = enforcement_base().filter(status=CaseStatus.OPEN, client_role="creditor")
    return [
        ("Açık icra", qs.count()),
        ("Hacizli", qs.filter(seizure_count__gt=0).count()),
        ("Haciz yenilemesi yaklaşan", qs.filter(next_renewal__lte=_renewal_limit()).count()),
        ("Tebligatlı", qs.filter(notice_count__gt=0).count()),
    ]


# Sekmeler: (anahtar, ad, açık dosyada bu aşamalar). Alacaklı sekmelerinde ilk sekme kalan
# tüm açık aşamaları da alır; borçlu ve üçüncü şahıs sekmeleri aşamaya bölünmez.
TABS = [
    ("tebligat", "Tebligat aşaması", ("started", "order_issued", "order_served")),
    ("haciz", "Haciz aşaması", ("finalized", "seizure", "sale", "partial_collection")),
    ("durdurulan", "Durdurulan takipler", ("suspended",)),
    ("islemsiz", "İşlemsiz / Kapalı dosyalar", ("dormant",)),
    ("borclu", "Borçlu olduklarımız", ()),
    ("ucuncu", "Üçüncü şahıs olduklarımız", ()),
]
DEFAULT_TAB = TABS[0][0]
ROLE_TABS = {"borclu", "ucuncu"}


def tab_key(params):
    key = params.get("sekme")
    return key if key in {t[0] for t in TABS} else DEFAULT_TAB


def apply_tab(qs, key):
    """Sekmeye göre dosya kümesi; kapalı alacaklı dosyaları yalnızca "İşlemsiz / Kapalı"da."""
    if key == "borclu":
        return qs.filter(client_role="debtor")
    if key == "ucuncu":
        return qs.exclude(client_role__in=["creditor", "debtor"])
    qs = qs.filter(client_role="creditor")
    if key == "islemsiz":
        return qs.filter(Q(status=CaseStatus.CLOSED) | Q(stage="dormant"))
    stage_map = {k: s for k, _, s in TABS}
    qs = qs.filter(status=CaseStatus.OPEN)
    if key == "tebligat":
        other = [s for k, ss in stage_map.items() if k != "tebligat" for s in ss]
        return qs.exclude(stage__in=other)
    return qs.filter(stage__in=stage_map[key])


def tab_counts(qs):
    """Sekme başlığındaki sayılar (aramadan bağımsız)."""
    return {key: apply_tab(qs, key).count() for key, _, _ in TABS}


def apply_filters(qs, params):
    """GET süzgeçlerini icra dosyası sorgusuna uygular."""
    if q := params.get("q", "").strip():
        qs = qs.filter(
            Q(archive_no__icontains=q)
            | Q(archive_folder_no__icontains=q)
            | Q(official_no__icontains=q)
            | Q(subject__icontains=q)
            | Q(authority__icontains=q)
            | Q(client__search_key__contains=fold(q))
        )
    tab = tab_key(params)
    qs = apply_tab(qs, tab)
    if params.get("tur") in EnforcementType.values:
        qs = qs.filter(enforcement_type=params["tur"])
    if lawyer := params.get("avukat"):
        qs = qs.filter(responsible_lawyer_id=lawyer)
    seizure = params.get("haciz")
    if tab == "haciz":
        if seizure == "var":
            qs = qs.filter(seizure_count__gt=0)
        elif seizure == "yok":
            qs = qs.filter(seizure_count=0)
        elif seizure == "yenileme":
            qs = qs.filter(next_renewal__lte=_renewal_limit())
    return qs


SORT_FIELDS = {
    "last_action",
    "next_renewal",
    "opened_on",
    "archive_no",
    "client__name",
    "enforcement_type",
    "stage",
    "seizure_count",
    "notice_count",
}


def apply_sort(qs, sort):
    """Sıralanmış sorgu ve geçerli sıralama anahtarı."""
    if sort.lstrip("-") not in SORT_FIELDS:
        sort = "-last_action"
    if sort.lstrip("-") == "next_renewal":
        field = F("next_renewal")
        ordering = (
            field.desc(nulls_last=True) if sort.startswith("-") else field.asc(nulls_last=True)
        )
        return qs.order_by(ordering, "pk"), sort
    return qs.order_by(sort, "pk"), sort


def side_names(case, role):
    """Dosyanın alacaklı/borçlu tarafındaki adlar; müvekkil (varsa) başta, tekrarsız.

    `party_links__party` ve `co_client_links__client` önceden yüklenmiş olmalıdır."""
    names = []
    if case.client_id and case.client_role == role:
        names.append(case.client.name)
    names += [c.client.name for c in case.co_client_links.all() if c.role == role]
    names += [link.party.name for link in case.party_links.all() if link.role == role]
    return list(dict.fromkeys(n for n in names if n))


def uyap_closing_reason(case):
    """Kapalı dosyada UYAP'taki kapanma nedeni; UYAP bilgisi yoksa büronun girdiği neden."""
    if case.is_open:
        return ""
    stage = (case.uyap_stage or "").strip()
    if match := re.search(r"Kapalı\s*\(([^)]+)\)", stage, re.I):
        return match.group(1).strip()
    if stage and not stage.lower().startswith(("kapalı", "kapali")):
        return stage
    return case.closing_label
