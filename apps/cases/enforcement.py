"""İcra İşlemleri ekranı: icra dosyalarının tür, aşama, haciz ve tebligat durumuna göre listesi."""

import datetime as dt

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

from . import stages
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
    qs = enforcement_base().filter(status=CaseStatus.OPEN)
    return [
        ("Açık icra", qs.count()),
        ("Hacizli", qs.filter(seizure_count__gt=0).count()),
        ("Haciz yenilemesi yaklaşan", qs.filter(next_renewal__lte=_renewal_limit()).count()),
        ("Tebligatlı", qs.filter(notice_count__gt=0).count()),
    ]


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
    status = params.get("status", "open")
    if status == "open":
        qs = qs.filter(status=CaseStatus.OPEN)
    elif status == "closed":
        qs = qs.filter(status=CaseStatus.CLOSED)
    if params.get("tur") in EnforcementType.values:
        qs = qs.filter(enforcement_type=params["tur"])
    if params.get("asama") in dict(stages.open_stages(CaseType.ENFORCEMENT)):
        qs = qs.filter(stage=params["asama"], status=CaseStatus.OPEN)
    role = params.get("sifat")
    if role in {"creditor", "debtor"}:
        qs = qs.filter(client_role=role)
    elif role == "other":
        qs = qs.exclude(client_role__in=["creditor", "debtor"])
    if lawyer := params.get("avukat"):
        qs = qs.filter(responsible_lawyer_id=lawyer)
    seizure = params.get("haciz")
    if seizure == "var":
        qs = qs.filter(seizure_count__gt=0)
    elif seizure == "yok":
        qs = qs.filter(seizure_count=0)
    elif seizure == "yenileme":
        qs = qs.filter(next_renewal__lte=_renewal_limit())
    elif seizure:
        qs = qs.filter(pk__in=Seizure.objects.filter(is_active=True, kind=seizure).values("case"))
    if params.get("tebligat"):
        qs = qs.filter(notice_count__gt=0)
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
