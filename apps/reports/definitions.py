"""Rapor tanımları. Her rapor: parametre formu + build(params, user) -> ReportResult."""

from collections import defaultdict
from decimal import Decimal

from django import forms
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounting.models import _MONEY as MONEY
from apps.accounting.models import CREDIT_EXPR, EntryKind, LedgerEntry
from apps.accounts.models import User
from apps.cases import seizure_types, stages
from apps.cases.flows import cluster
from apps.cases.models import Case, CaseEvent, CaseStatus, CaseType, Seizure
from apps.clients.models import Client
from apps.core.forms import BootstrapMixin, DateInput
from apps.tasks.models import OPEN_STATUSES, Task, TaskStatus

from .base import Column, ReportResult

ZERO = Decimal("0.00")
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]  # fmt: skip


def _period(data) -> str:
    s, e = data.get("start"), data.get("end")
    if s and e:
        return f"{s:%d.%m.%Y} – {e:%d.%m.%Y}"
    if s:
        return f"{s:%d.%m.%Y} sonrası"
    if e:
        return f"{e:%d.%m.%Y} öncesi"
    return "Tüm zamanlar"


class PeriodForm(BootstrapMixin, forms.Form):
    start = forms.DateField(label="Başlangıç", required=False, widget=DateInput())
    end = forms.DateField(label="Bitiş", required=False, widget=DateInput())

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            self.add_error("end", "Bitiş tarihi başlangıçtan önce olamaz.")
        return data


def _date_filter(qs, data, field="date"):
    if data.get("start"):
        qs = qs.filter(**{f"{field}__gte": data["start"]})
    if data.get("end"):
        qs = qs.filter(**{f"{field}__lte": data["end"]})
    return qs


# 1. Müvekkil cari ekstresi ---------------------------------------------------------------
class StatementForm(PeriodForm):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all())
    field_order = ["client", "start", "end"]


def build_statement(d, user):
    client = d["client"]
    entries = client.ledger_entries.active().select_related("case").order_by("date", "pk")
    balance = ZERO
    if d.get("start"):
        balance = entries.filter(date__lt=d["start"]).balances()["balance"]
    entries = _date_filter(entries, d)
    rows = []
    if d.get("start"):
        rows.append([d["start"], "Devir", "", "", None, balance])
    for e in entries:
        balance += e.balance_effect
        rows.append(
            [
                e.date,
                e.get_kind_display(),
                e.case.archive_reference if e.case else "",
                e.description,
                e.amount,
                balance,
            ]
        )
    return ReportResult(
        title="Müvekkil Hesap Ekstresi",
        subtitle=f"{client.name} · {_period(d)}",
        columns=[
            Column("Tarih", "date", 0.8),
            Column("Hareket", "text", 1.3),
            Column("Dosya", "text", 0.8),
            Column("Açıklama", "text", 2.2),
            Column("Tutar", "money", 1),
            Column("Bakiye", "money", 1),
        ],  # fmt: skip
        rows=rows,
        summary=[
            ("Müvekkil", client.name),
            ("Kimlik no", client.identity_no or "—"),
            ("Dönem sonu bakiye", _tl(balance)),
        ],
    )


# 2. Borçlu müvekkiller ---------------------------------------------------------------------
class DebtorsForm(BootstrapMixin, forms.Form):
    lawyer = forms.ModelChoiceField(
        label="Sorumlu avukat",
        queryset=User.objects.filter(role__in=["admin", "senior", "lawyer"]),
        required=False,
    )
    include_zero = forms.BooleanField(label="Borcu olmayanları da göster", required=False)


def build_debtors(d, user):
    from apps.clients.views import annotate_list_values

    qs = annotate_list_values(Client.objects.select_related("responsible_lawyer"))
    if d.get("lawyer"):
        qs = qs.filter(responsible_lawyer=d["lawyer"])
    if not d.get("include_zero"):
        qs = qs.filter(balance__gt=0)
    rows, total = [], ZERO
    credit_sq = (
        LedgerEntry.objects.filter(client=OuterRef("pk"), is_cancelled=False)
        .order_by().values("client").annotate(t=Sum(CREDIT_EXPR)).values("t")
    )  # fmt: skip
    qs = qs.annotate(
        credit=Coalesce(Subquery(credit_sq, output_field=MONEY), Value(ZERO), output_field=MONEY)
    )
    for c in qs.order_by("-balance", "name"):
        rows.append([c.name, c.responsible_lawyer, c.case_count, c.credit, c.balance])
        total += c.balance
    return ReportResult(
        title="Borçlu Müvekkiller / Alacak Listesi",
        subtitle=f"{timezone.localdate():%d.%m.%Y} itibarıyla"
        + (f" · {d['lawyer']}" if d.get("lawyer") else ""),
        columns=[
            Column("Müvekkil", "text", 2.2),
            Column("Sorumlu avukat", "text", 1.4),
            Column("Dosya", "int", 0.6),
            Column("Ofisten alacağı", "money", 1.1),
            Column("Bakiye (borç)", "money", 1.1),
        ],  # fmt: skip
        rows=rows,
        totals=["Toplam", "", "", None, total],
        landscape=False,
    )


# 3. Görev raporu ---------------------------------------------------------------------------
class TaskReportForm(PeriodForm):
    STATUS = [
        ("open", "Açık görevler"),
        ("overdue", "Gecikmiş görevler"),
        *TaskStatus.choices,
        ("all", "Tümü"),
    ]
    status = forms.ChoiceField(label="Durum", choices=STATUS, initial="open", required=False)
    user = forms.ModelChoiceField(
        label="Kişi (sorumlu veya kontrolcü)", queryset=User.objects.all(), required=False
    )
    field_order = ["status", "user", "start", "end"]


def build_tasks(d, user):
    qs = Task.objects.select_related("task_type", "case", "client", "assignee", "reviewer")
    st = d.get("status") or "open"
    today = timezone.localdate()
    if st == "open":
        qs = qs.filter(status__in=OPEN_STATUSES)
    elif st == "overdue":
        qs = qs.filter(status__in=OPEN_STATUSES, due_date__lt=today)
    elif st in TaskStatus.values:
        qs = qs.filter(status=st)
    if d.get("user"):
        qs = qs.filter(Q(assignee=d["user"]) | Q(reviewer=d["user"]))
    qs = _date_filter(qs, d, "due_date").order_by("due_date", "pk")
    rows = [
        [t.due_date, t.title, t.task_type.name, f"{t.case.archive_reference} · {t.client}", t.assignee, t.reviewer,
         t.get_status_display() + (" (revizyon)" if t.revision_requested else ""),
         t.due_label if t.is_open else (f"{timezone.localtime(t.completed_at):%d.%m.%Y}" if t.completed_at else "")]
        for t in qs
    ]  # fmt: skip
    label = dict(TaskReportForm.STATUS)[st]
    return ReportResult(
        title="Görev Raporu",
        subtitle=f"{label} · son gün: {_period(d)}" + (f" · {d['user']}" if d.get("user") else ""),
        columns=[
            Column("Son gün", "date", 0.8),
            Column("Görev", "text", 2),
            Column("Tür", "text", 1),
            Column("Dosya / Müvekkil", "text", 2),
            Column("Sorumlu", "text", 1.2),
            Column("Kontrolcü", "text", 1.2),
            Column("Durum", "text", 1),
            Column("Kalan / Tamamlanma", "text", 1),
        ],  # fmt: skip
        rows=rows,
        summary=[("Görev sayısı", str(len(rows)))],
    )


# 4. Dosya listesi --------------------------------------------------------------------------
class CaseListForm(BootstrapMixin, forms.Form):
    case_type = forms.ChoiceField(
        label="Dosya türü", choices=[("", "Tümü"), *CaseType.choices], required=False
    )
    status = forms.ChoiceField(
        label="Durum",
        choices=[("open", "Açık dosyalar"), ("closed", "Kapalı dosyalar"), ("all", "Tümü")],
        initial="open",
        required=False,
    )
    lawyer = forms.ModelChoiceField(
        label="Sorumlu avukat",
        queryset=User.objects.filter(role__in=["admin", "senior", "lawyer"]),
        required=False,
    )

    stage = forms.ChoiceField(label="Aşama", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].choices = [
            ("", "Tüm aşamalar"),
            *[
                (label, [(f"{kind}:{key}", text) for key, text in stages.open_stages(kind)])
                for kind, label in CaseType.choices
            ],
        ]


def _seizure_summary(cases):
    active = Seizure.objects.filter(
        case_id=OuterRef("pk"), is_active=True, case__case_type=CaseType.ENFORCEMENT
    ).filter(Q(kind="") | Q(state__in=seizure_types.SEIZED_STATES))
    count = active.order_by().values("case_id").annotate(total=Count("pk")).values("total")
    return cases.annotate(
        active_seizures=Coalesce(Subquery(count, output_field=IntegerField()), Value(0)),
        next_renewal=Subquery(
            active.exclude(renewal_on__isnull=True)
            .order_by("renewal_on", "pk")
            .values("renewal_on")[:1]
        ),
    )


def _linked_name(case) -> str:
    """Bağlı dosyalar raporlarda art arda gelir; ad önüne bağ işareti, sonuna bağlı sayısı eklenir."""
    name = case.display_name
    if getattr(case, "chain_prev", False):
        name = "↔ " + name
    if getattr(case, "linked_others", 0):
        name += f" (+{case.linked_others} dosya bağlı)"
    return name


def build_cases(d, user):
    qs = Case.objects.select_related("client", "responsible_lawyer", "responsible_intern")
    if d.get("case_type"):
        qs = qs.filter(case_type=d["case_type"])
    st = d.get("status") or "open"
    if st == "open":
        qs = qs.exclude(status=CaseStatus.CLOSED)
    elif st in CaseStatus.values:
        qs = qs.filter(status=st)
    if d.get("lawyer"):
        qs = qs.filter(responsible_lawyer=d["lawyer"])
    if d.get("stage"):
        kind, key = d["stage"].split(":", 1)
        qs = qs.filter(case_type=kind, stage=key, status=CaseStatus.OPEN)
    qs = _seizure_summary(qs)
    qs = qs.annotate(open_tasks=Count("tasks", filter=Q(tasks__status__in=OPEN_STATUSES))).order_by(
        "archive_no"
    )
    rows = [
        [k.archive_reference, k.get_case_type_display(), _linked_name(k), k.client.name if k.client else "—", f"{k.authority} {k.official_no_display}".strip(),
         k.get_status_display(), k.responsible_lawyer, k.open_tasks,
         k.status_detail or k.uyap_stage, k.active_seizures, k.next_renewal]
        for k in cluster(qs)
    ]  # fmt: skip
    return ReportResult(
        title="Dosya Listesi",
        subtitle=" · ".join(
            x
            for x in [
                dict(CaseType.choices).get(d.get("case_type"), "Tüm türler"),
                dict(CaseListForm.base_fields["status"].choices)[st],
                str(d["lawyer"]) if d.get("lawyer") else "",
            ]
            if x
        ),  # fmt: skip
        columns=[
            Column("Arşiv no", "text", 0.8),
            Column("Tür", "text", 1),
            Column("Dosya", "text", 2),
            Column("Müvekkil", "text", 1.6),
            Column("Merci / Resmi no", "text", 1.8),
            Column("Durum", "text", 1),
            Column("Avukat", "text", 1.2),
            Column("Açık görev", "int", 0.6),
            Column("Aşama / Kapanma nedeni", "text", 1.4),
            Column("Aktif haciz", "int", 0.6),
            Column("Yenileme tarihi", "date", 0.8),
        ],  # fmt: skip
        rows=rows,
        summary=[("Dosya sayısı", str(len(rows)))],
    )


# 5. Dönem muhasebe raporu ------------------------------------------------------------------
class PeriodAccountingForm(PeriodForm):
    pass


def build_period_accounting(d, user):
    qs = _date_filter(LedgerEntry.objects.active(), d)
    by_month = defaultdict(lambda: defaultdict(lambda: ZERO))
    for e in qs.only("date", "kind", "amount"):
        by_month[(e.date.year, e.date.month)][e.kind] += e.amount
    kinds = [k for k, _ in EntryKind.choices]
    rows, totals = [], defaultdict(lambda: ZERO)
    for y, m in sorted(by_month):
        vals = by_month[(y, m)]
        rows.append([f"{MONTHS[m - 1]} {y}", *[vals[k] for k in kinds]])
        for k in kinds:
            totals[k] += vals[k]
    t = qs.totals_by_kind()
    return ReportResult(
        title="Dönem Muhasebe Raporu",
        subtitle=_period(d),
        columns=[Column("Ay", "text", 1.1)]
        + [Column(label, "money", 1) for _, label in EntryKind.choices],
        rows=rows,
        totals=["Toplam", *[totals[k] for k in kinds]],
        summary=[
            ("Müvekkilden tahsilat (ücret ve masraf karşılığı)", _tl(t["collection"])),
            ("Tahakkuk eden vekalet ücreti", _tl(t["fee"])),
            ("Müvekkil adına masraf", _tl(t["expense"])),
            ("Karşı taraftan tahsilat (müvekkilin ofisten alacağı)", _tl(t["trust_in"])),
            ("Müvekkile ödeme", _tl(t["trust_out"])),
        ],
    )


def _tl(v):
    from .base import fmt

    return fmt(v, "money")


# 6. Müvekkil bazlı dosya son durum raporu --------------------------------------------------
class ClientCasesForm(BootstrapMixin, forms.Form):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all(), required=False,
                                    help_text="Boş bırakılırsa tüm müvekkiller")  # fmt: skip
    include_closed = forms.BooleanField(label="Kapanmış dosyaları da göster", required=False)


def build_client_cases(d, user):
    cases = _seizure_summary(Case.objects.select_related("client"))
    if d.get("client"):
        cases = cases.filter(client=d["client"])
    if not d.get("include_closed"):
        cases = cases.exclude(status=CaseStatus.CLOSED)
    tasks_sq = (
        Task.objects.filter(case=OuterRef("pk"), status__in=OPEN_STATUSES)
        .order_by().values("case").annotate(n=Count("pk")).values("n")
    )  # fmt: skip
    last_sq = CaseEvent.objects.filter(case=OuterRef("pk")).order_by("-date", "-created_at")
    cases = cases.annotate(
        open_tasks=Coalesce(Subquery(tasks_sq, output_field=IntegerField()), Value(0)),
        last_date=Subquery(last_sq.values("date")[:1]),
        last_title=Subquery(last_sq.values("title")[:1]),
    ).order_by("client__name", "archive_no")
    rows = [
        [k.client.name if k.client else "—", k.archive_reference, _linked_name(k), k.get_status_display(),
         k.open_tasks, f"{k.last_date:%d.%m.%Y} {k.last_title}" if k.last_date else "",
         k.status_detail or k.uyap_stage, k.active_seizures, k.next_renewal]
        for k in cluster(cases)
    ]  # fmt: skip
    return ReportResult(
        title="Dosyaların Son Durumu",
        subtitle=(d["client"].name if d.get("client") else "Tüm müvekkiller")
        + f" · {timezone.localdate():%d.%m.%Y}",
        columns=[
            Column("Müvekkil", "text", 1.5),
            Column("Arşiv no", "text", 0.7),
            Column("Dosya", "text", 1.7),
            Column("Durum", "text", 1),
            Column("Açık görev", "int", 0.6),
            Column("Son gelişme", "text", 2.4),
            Column("Aşama / Kapanma nedeni", "text", 1.4),
            Column("Aktif haciz", "int", 0.6),
            Column("Yenileme tarihi", "date", 0.8),
        ],  # fmt: skip
        rows=rows,
        summary=[("Dosya sayısı", str(len(rows)))],
    )


class SeizureReportForm(PeriodForm):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all(), required=False)
    lawyer = forms.ModelChoiceField(
        label="Sorumlu avukat",
        queryset=User.objects.filter(role__in=["admin", "senior", "lawyer"]),
        required=False,
    )
    state = forms.ChoiceField(
        label="Haciz durumu",
        required=False,
        initial="active",
        choices=[("active", "Aktif"), ("inactive", "Pasif"), ("all", "Tümü")],
    )
    include_closed = forms.BooleanField(label="Kapalı dosyaları da göster", required=False)
    field_order = ["client", "lawyer", "state", "start", "end", "include_closed"]


def build_seizures(d, user):
    items = (
        Seizure.objects.filter(case__case_type=CaseType.ENFORCEMENT)
        .select_related(
            "case__client",
            "case__responsible_intern",
            "case__responsible_lawyer",
            "debtor_party",
            "debtor_client",
        )
        .prefetch_related("renewals__task__assignee", "renewals__task__reviewer")
    )
    if not d.get("include_closed"):
        items = items.filter(case__status=CaseStatus.OPEN)
    if d.get("client"):
        items = items.filter(
            Q(case__client=d["client"]) | Q(case__co_clients=d["client"])
        ).distinct()
    if d.get("lawyer"):
        items = items.filter(case__responsible_lawyer=d["lawyer"])
    if d.get("state") != "all":
        items = items.filter(is_active=d.get("state") != "inactive")
    items = _date_filter(items, d, "renewal_on").order_by("renewal_on", "pk")
    rows = []
    for item in items:
        cycle = next(
            (cycle for cycle in item.renewals.all() if cycle.due_date == item.renewal_on), None
        )
        task = cycle.task if cycle else None
        state = (
            task.get_status_display()
            if task
            else ("Görev silinmiş" if cycle else "Görev günü bekleniyor")
        )
        if not task and not cycle:
            if not item.is_active:
                state = "Takip pasif"
            elif not item.case.is_open:
                state = "Dosya kapalı"
        rows.append(
            [
                item.case.display_name,
                item.case.client.name if item.case.client else "—",
                item.debtor_display,
                item.asset_label,
                item.seized_on,
                item.renewal_on,
                "Aktif" if item.is_active else "Pasif",
                task.assignee if task else item.case.responsible_intern,
                task.reviewer if task else item.case.responsible_lawyer,
                state,
                item.state_label,
            ]
        )
    return ReportResult(
        title="Haciz ve Yenileme Takibi",
        subtitle=f"Yenileme tarihi: {_period(d)}",
        columns=[
            Column("Dosya", "text", 2),
            Column("Müvekkil", "text", 1.3),
            Column("Borçlu", "text", 1.2),
            Column("Haciz türü / ayrıntı", "text", 1.8),
            Column("Haciz tarihi", "date", 0.8),
            Column("Yenileme tarihi", "date", 0.8),
            Column("Haciz durumu", "text", 0.7),
            Column("Sorumlu", "text", 1),
            Column("Kontrolcü", "text", 1),
            Column("Görev durumu", "text", 1.1),
            Column("Haciz aşaması", "text", 1.2),
        ],
        rows=rows,
        summary=[("Takip sayısı", str(len(rows)))],
    )


REPORTS = {
    "cari-ekstre": {
        "title": "Müvekkil hesap ekstresi", "icon": "bi-journal-text", "financial": True, "form": StatementForm,
        "build": build_statement, "desc": "Bir müvekkilin dönem içindeki tüm hareketleri, devir ve bakiyeleri.",
    },
    "borclu-muvekkiller": {
        "title": "Borçlu müvekkiller / alacak listesi", "icon": "bi-cash-stack", "financial": True,
        "form": DebtorsForm, "build": build_debtors, "desc": "Bakiyesi (müvekkilin ofise borcu) olan müvekkiller ve toplam alacak.",
    },
    "gorevler": {
        "title": "Görev raporu", "icon": "bi-check2-square", "financial": False, "form": TaskReportForm,
        "build": build_tasks, "desc": "Açık, gecikmiş veya tamamlanan görevler; kişi ve tarihe göre.",
    },
    "dosya-listesi": {
        "title": "Dosya listesi", "icon": "bi-folder2-open", "financial": False, "form": CaseListForm,
        "build": build_cases, "desc": "Dosyalar türe, duruma ve sorumluya göre.",
    },
    "donem-muhasebe": {
        "title": "Dönem muhasebe raporu", "icon": "bi-bar-chart-line", "financial": True,
        "form": PeriodAccountingForm, "build": build_period_accounting,
        "desc": "Aylara göre vekalet ücreti, masraf, tahsilat ve ödeme toplamları.",
    },
    "dosya-son-durum": {
        "title": "Müvekkil bazlı dosya son durumu", "icon": "bi-clipboard-data", "financial": False,
        "form": ClientCasesForm, "build": build_client_cases,
        "desc": "Dosyaların durumu, aşaması, açık görevleri, hacizleri ve son gelişmesi.",
    },
}  # fmt: skip


REPORTS["haciz-takibi"] = {
    "title": "Haciz ve yenileme takibi",
    "icon": "bi-calendar-check",
    "financial": False,
    "form": SeizureReportForm,
    "build": build_seizures,
    "desc": "Borçlu, mal varlığı, haciz tarihi, yenileme günü ve görev durumu.",
}
REPORT_GROUPS = [
    ("cases", "Dosya raporları"),
    ("tasks", "Görev raporları"),
    ("financial", "Mali raporlar"),
]
for key, spec in REPORTS.items():
    spec["group"] = (
        "financial" if spec["financial"] else ("tasks" if key == "gorevler" else "cases")
    )
