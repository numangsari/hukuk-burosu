"""Rapor tanımları. Her rapor: parametre formu + build(params, user) -> ReportResult."""

from collections import defaultdict
from decimal import Decimal

from django import forms
from django.core.exceptions import PermissionDenied
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounting.models import _MONEY as MONEY
from apps.accounting.models import CREDIT_EXPR, EntryKind, LedgerEntry
from apps.accounts.models import User
from apps.cases import stages
from apps.cases.flows import cluster
from apps.cases.models import Case, CaseEvent, CaseStatus, CaseType
from apps.clients.models import Client, PersonKind
from apps.core.forms import BootstrapMixin, DateInput
from apps.core.permissions import (
    can_view_all_office_data,
    filter_visible_cases,
    filter_visible_clients,
    filter_visible_tasks,
)
from apps.core.text import tr_title
from apps.office.models import TaskType
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
    if not filter_visible_clients(Client.objects.filter(pk=client.pk), user).exists():
        raise PermissionDenied
    # Müvekkile giden raporda iptal edilen ve hesap dışı bırakılan kayıtlar yer almaz.
    entries = client.ledger_entries.counted().select_related("case").order_by("date", "pk")
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
                tr_title(e.case.display_name) if e.case else "",
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
            Column("Dosya", "text", 1.6),
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

    qs = annotate_list_values(
        filter_visible_clients(Client.objects.select_related("responsible_lawyer"), user)
    )
    if d.get("lawyer"):
        qs = qs.filter(responsible_lawyer=d["lawyer"])
    if not d.get("include_zero"):
        qs = qs.filter(balance__gt=0)
    rows, total = [], ZERO
    credit_sq = (
        LedgerEntry.objects.counted().filter(client=OuterRef("pk"))
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
    task_type = forms.ModelChoiceField(
        label="Görev türü", queryset=TaskType.objects.all(), required=False
    )
    assignee = forms.ModelChoiceField(label="Sorumlu", queryset=User.objects.all(), required=False)
    reviewer = forms.ModelChoiceField(
        label="Kontrolcü", queryset=User.objects.all(), required=False
    )
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all(), required=False)
    user = forms.ModelChoiceField(
        label="Kişi (sorumlu veya kontrolcü)", queryset=User.objects.all(), required=False
    )
    field_order = ["status", "task_type", "assignee", "reviewer", "client", "user", "start", "end"]


def build_tasks(d, user):
    qs = filter_visible_tasks(
        Task.objects.select_related("task_type", "case", "client", "assignee", "reviewer"), user
    )
    st = d.get("status") or "open"
    today = timezone.localdate()
    if st == "open":
        qs = qs.filter(status__in=OPEN_STATUSES)
    elif st == "overdue":
        qs = qs.filter(status__in=OPEN_STATUSES, due_date__lt=today)
    elif st in TaskStatus.values:
        qs = qs.filter(status=st)
    if d.get("task_type"):
        qs = qs.filter(task_type=d["task_type"])
    if d.get("assignee"):
        qs = qs.filter(assignee=d["assignee"])
    if d.get("reviewer"):
        qs = qs.filter(Q(reviewer=d["reviewer"]) | Q(second_reviewer=d["reviewer"]))
    if d.get("client"):
        qs = qs.filter(client=d["client"])
    if d.get("user"):
        qs = qs.filter(Q(assignee=d["user"]) | Q(reviewer=d["user"]))
    qs = _date_filter(qs, d, "due_date").order_by("due_date", "pk")
    rows = [
        [t.due_date, t.title, t.task_type.name, (f"{t.case.archive_reference} · {t.client}" if t.case_id else "Ofis içi"), t.assignee, t.reviewer,
         t.get_status_display() + (" (revizyon)" if t.revision_requested else ""),
         t.due_label if t.is_open else (f"{timezone.localtime(t.completed_at):%d.%m.%Y}" if t.completed_at else "")]
        for t in qs
    ]  # fmt: skip
    label = dict(TaskReportForm.STATUS)[st]
    parts = [label, f"son gün: {_period(d)}"]
    for key in ("task_type", "assignee", "reviewer", "client", "user"):
        if d.get(key):
            parts.append(str(d[key]))
    return ReportResult(
        title="Görev Raporu",
        subtitle=" · ".join(parts),
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


# 4. Dosya raporu ---------------------------------------------------------------------------
class CaseReportForm(PeriodForm):
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
    intern = forms.ModelChoiceField(
        label="Yardımcı sorumlu",
        queryset=User.objects.filter(role__in=["intern", "paralegal"]),
        required=False,
    )
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all(), required=False)
    stage = forms.ChoiceField(label="Aşama", required=False)
    field_order = ["case_type", "status", "lawyer", "intern", "client", "stage", "start", "end"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start"].label = "Kayıt tarihi: başlangıç"
        self.fields["end"].label = "Kayıt tarihi: bitiş"
        self.fields["stage"].choices = [
            ("", "Tüm aşamalar"),
            *[
                (label, [(f"{kind}:{key}", text) for key, text in stages.open_stages(kind)])
                for kind, label in CaseType.choices
            ],
        ]


def _linked_name(case) -> str:
    """Bağlı dosyalar raporlarda art arda gelir; ad önüne bağ işareti, sonuna bağlı sayısı eklenir."""
    name = case.display_name
    if getattr(case, "chain_prev", False):
        name = "↔ " + name
    if getattr(case, "linked_others", 0):
        name += f" (+{case.linked_others} dosya bağlı)"
    return name


def build_cases(d, user):
    from apps.cases.models import Hearing, HearingStatus

    qs = filter_visible_cases(
        Case.objects.select_related("client", "responsible_lawyer", "responsible_intern"), user
    )
    if d.get("case_type"):
        qs = qs.filter(case_type=d["case_type"])
    st = d.get("status") or "open"
    if st == "open":
        qs = qs.exclude(status=CaseStatus.CLOSED)
    elif st in CaseStatus.values:
        qs = qs.filter(status=st)
    if d.get("lawyer"):
        qs = qs.filter(responsible_lawyer=d["lawyer"])
    if d.get("intern"):
        qs = qs.filter(responsible_intern=d["intern"])
    if d.get("client"):
        qs = qs.filter(Q(client=d["client"]) | Q(co_clients=d["client"])).distinct()
    if d.get("stage"):
        kind, key = d["stage"].split(":", 1)
        qs = qs.filter(case_type=kind, stage=key, status=CaseStatus.OPEN)
    qs = _date_filter(qs, d, "created_at__date")
    tasks_sq = (
        Task.objects.filter(case=OuterRef("pk"), status__in=OPEN_STATUSES)
        .order_by().values("case").annotate(n=Count("pk")).values("n")
    )  # fmt: skip
    last_sq = CaseEvent.objects.filter(case=OuterRef("pk")).order_by("-date", "-created_at")
    next_sq = Hearing.objects.filter(
        case=OuterRef("pk"), status=HearingStatus.PLANNED, starts_at__gte=timezone.now()
    ).order_by("starts_at")
    qs = qs.annotate(
        open_tasks=Coalesce(Subquery(tasks_sq, output_field=IntegerField()), Value(0)),
        last_date=Subquery(last_sq.values("date")[:1]),
        last_title=Subquery(last_sq.values("title")[:1]),
        upcoming_hearing=Subquery(next_sq.values("starts_at")[:1]),
    ).order_by("archive_no", "pk")
    rows = [
        [k.archive_reference, _linked_name(k), k.get_case_type_display(), k.client.name if k.client else "—",
         f"{k.authority} {k.official_no_display}".strip(), k.get_status_display(),
         k.status_detail or k.uyap_stage, k.responsible_lawyer, k.responsible_intern, k.open_tasks,
         f"{k.last_date:%d.%m.%Y} {k.last_title}" if k.last_date else "",
         timezone.localtime(k.upcoming_hearing).date() if k.upcoming_hearing else None]
        for k in cluster(qs)
    ]  # fmt: skip
    parts = [
        dict(CaseType.choices).get(d.get("case_type"), "Tüm türler"),
        dict(CaseReportForm.base_fields["status"].choices)[st],
    ]
    for key in ("lawyer", "intern", "client"):
        if d.get(key):
            parts.append(str(d[key]))
    if d.get("start") or d.get("end"):
        parts.append(f"kayıt: {_period(d)}")
    return ReportResult(
        title="Dosya Raporu",
        subtitle=" · ".join(parts),
        columns=[
            Column("Arşiv yeri", "text", 0.9),
            Column("Dosya", "text", 2),
            Column("Tür", "text", 1),
            Column("Müvekkil", "text", 1.6),
            Column("Merci / Resmi no", "text", 1.8),
            Column("Durum", "text", 0.8),
            Column("Aşama / Kapanma nedeni", "text", 1.4),
            Column("Sorumlu avukat", "text", 1.2),
            Column("Yardımcı sorumlu", "text", 1.2),
            Column("Açık görev", "int", 0.6),
            Column("Son gelişme", "text", 2),
            Column("Sonraki duruşma", "date", 0.9),
        ],  # fmt: skip
        rows=rows,
        summary=[("Dosya sayısı", str(len(rows)))],
    )


# 5. Müvekkil raporları ---------------------------------------------------------------------
class ClientReportForm(BootstrapMixin, forms.Form):
    kind = forms.ChoiceField(
        label="Müvekkil türü", choices=[("", "Tümü"), *PersonKind.choices], required=False
    )
    lawyer = forms.ModelChoiceField(
        label="Sorumlu avukat",
        queryset=User.objects.filter(role__in=["admin", "senior", "lawyer"]),
        required=False,
    )
    intern = forms.ModelChoiceField(
        label="Yardımcı sorumlu",
        queryset=User.objects.filter(role__in=["intern", "paralegal"]),
        required=False,
    )
    poa = forms.ChoiceField(
        label="Vekaletname",
        choices=[("", "Tümü"), ("yes", "Vekaletnamesi var"), ("no", "Vekaletnamesi yok")],
        required=False,
    )
    tasks = forms.ChoiceField(
        label="Açık görev",
        choices=[("", "Tümü"), ("yes", "Açık görevi olan"), ("no", "Açık görevi olmayan")],
        required=False,
    )


def build_clients(d, user):
    from apps.accounting.permissions import can_view_balances
    from apps.clients.views import annotate_list_values

    qs = annotate_list_values(
        filter_visible_clients(
            Client.objects.select_related(
                "responsible_lawyer", "responsible_intern"
            ).prefetch_related("contacts"),
            user,
        )
    )
    if d.get("kind"):
        qs = qs.filter(kind=d["kind"])
    if d.get("lawyer"):
        qs = qs.filter(responsible_lawyer=d["lawyer"])
    if d.get("intern"):
        qs = qs.filter(responsible_intern=d["intern"])
    if d.get("poa") == "yes":
        qs = qs.filter(has_poa=True)
    elif d.get("poa") == "no":
        qs = qs.filter(has_poa=False)
    if d.get("tasks") == "yes":
        qs = qs.filter(open_task_count__gt=0)
    elif d.get("tasks") == "no":
        qs = qs.filter(open_task_count=0)
    show_balance = can_view_balances(user)
    rows = []
    for c in qs.order_by("name"):
        row = [
            c.name, c.get_kind_display(), c.primary_phone or "", c.responsible_lawyer,
            c.responsible_intern, c.case_count, c.open_task_count, "Var" if c.has_poa else "Yok",
        ]  # fmt: skip
        if show_balance:
            row.append(c.balance)
        rows.append(row)
    columns = [
        Column("Müvekkil", "text", 2.4),
        Column("Tür", "text", 0.9),
        Column("Telefon", "text", 1.2),
        Column("Sorumlu avukat", "text", 1.3),
        Column("Yardımcı sorumlu", "text", 1.3),
        Column("Dosya", "int", 0.6),
        Column("Açık görev", "int", 0.7),
        Column("Vekaletname", "text", 0.8),
    ]
    if show_balance:
        columns.append(Column("Bakiye", "money", 1.1))
    return ReportResult(
        title="Müvekkil Listesi",
        subtitle=" · ".join(
            x
            for x in [
                dict(PersonKind.choices).get(d.get("kind"), "Tüm türler"),
                str(d["lawyer"]) if d.get("lawyer") else "",
                str(d["intern"]) if d.get("intern") else "",
            ]
            if x
        ),
        columns=columns,
        rows=rows,
        summary=[("Müvekkil sayısı", str(len(rows)))],
    )


class ClientCasesForm(BootstrapMixin, forms.Form):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all())
    status = forms.ChoiceField(
        label="Durum",
        choices=[("open", "Açık dosyalar"), ("closed", "Kapalı dosyalar"), ("all", "Tümü")],
        initial="open",
        required=False,
    )
    case_type = forms.ChoiceField(
        label="Dosya türü", choices=[("", "Tümü"), *CaseType.choices], required=False
    )


def _own_client(d, user):
    client = d["client"]
    if not filter_visible_clients(Client.objects.filter(pk=client.pk), user).exists():
        raise PermissionDenied
    return client


def build_client_cases(d, user):
    """Müvekkile gönderilecek dosya durum raporu: ofis içi bilgi (sorumlu, arşiv yeri, görev) yok.

    Ortak dosyalarda diğer müvekkillerin adı yazılmaz.
    """
    from apps.cases.models import Hearing, HearingStatus

    client = _own_client(d, user)
    qs = (
        filter_visible_cases(Case.objects.all(), user)
        .filter(Q(client=client) | Q(co_clients=client))
        .distinct()
    )
    if d.get("case_type"):
        qs = qs.filter(case_type=d["case_type"])
    st = d.get("status") or "open"
    if st == "open":
        qs = qs.exclude(status=CaseStatus.CLOSED)
    elif st in CaseStatus.values:
        qs = qs.filter(status=st)
    # Zaman çizelgesindeki serbest notlar ofis içidir; müvekkile gösterilmez.
    last_sq = (
        CaseEvent.objects.filter(case=OuterRef("pk"))
        .exclude(kind=CaseEvent.Kind.NOTE)
        .order_by("-date", "-created_at")
    )
    next_sq = Hearing.objects.filter(
        case=OuterRef("pk"), status=HearingStatus.PLANNED, starts_at__gte=timezone.now()
    ).order_by("starts_at")
    qs = qs.annotate(
        last_date=Subquery(last_sq.values("date")[:1]),
        last_title=Subquery(last_sq.values("title")[:1]),
        upcoming_hearing=Subquery(next_sq.values("starts_at")[:1]),
    ).order_by("case_type", "archive_no", "pk")
    rows = [
        [
            tr_title(k.display_name), k.get_case_type_display(),
            tr_title(f"{k.authority} {k.official_no_display}".strip()), k.get_status_display(),
            k.status_detail or k.uyap_stage,
            f"{k.last_date:%d.%m.%Y} {k.last_title}" if k.last_date else "",
            timezone.localtime(k.upcoming_hearing).date() if k.upcoming_hearing else None,
        ]
        for k in qs
    ]  # fmt: skip
    return ReportResult(
        title="Dosya Durum Raporu",
        subtitle=f"{tr_title(client.name)} · {timezone.localdate():%d.%m.%Y} itibarıyla",
        columns=[
            Column("Dosya", "text", 2.2),
            Column("Tür", "text", 1),
            Column("Mahkeme / Esas no", "text", 2.2),
            Column("Durum", "text", 0.8),
            Column("Dosyanın durumu", "text", 1.4),
            Column("Son gelişme", "text", 2.4),
            Column("Sonraki duruşma", "date", 1),
        ],
        rows=rows,
        summary=[("Dosya sayısı", str(len(rows)))],
    )


class ClientHearingsForm(PeriodForm):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all())
    field_order = ["client", "start", "end"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start"].label = "Duruşma tarihi: başlangıç"
        self.fields["end"].label = "Duruşma tarihi: bitiş"


def build_client_hearings(d, user):
    """Müvekkile gönderilecek duruşma raporu: katılma durumu, sorumlu ve iç sonuç notu yok."""
    from apps.cases.hearing_list import base_hearings
    from apps.cases.models import LIST_KINDS

    client = _own_client(d, user)
    qs = base_hearings(user).filter(kind__in=LIST_KINDS)
    qs = qs.filter(
        Q(client=client) | Q(case__client=client) | Q(case__co_clients=client)
    ).distinct()
    qs = _date_filter(qs, d, "starts_at__date").order_by("starts_at")
    rows = []
    for h in qs:
        local = timezone.localtime(h.starts_at)
        rows.append(
            [
                local.date(), local.strftime("%H:%M"), h.get_kind_display(),
                tr_title(h.authority or (h.case.authority if h.case else "")),
                tr_title(h.case.display_name) if h.case else "", h.client_note,
            ]
        )  # fmt: skip
    return ReportResult(
        title="Duruşma Raporu",
        subtitle=f"{tr_title(client.name)} · {_period(d)}",
        columns=[
            Column("Tarih", "date", 0.8),
            Column("Saat", "text", 0.5),
            Column("Tür", "text", 0.9),
            Column("Mahkeme", "text", 2),
            Column("Dosya", "text", 2),
            Column("Açıklama", "text", 2.4),
        ],
        rows=rows,
        summary=[("Duruşma sayısı", str(len(rows)))],
    )


class ClientSummaryForm(PeriodForm):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all())
    field_order = ["client", "start", "end"]


def build_client_summary(d, user):
    """Müvekkile gönderilecek masraf ve tahsilat özeti: dosya bazında geçerli hareket toplamları."""
    client = _own_client(d, user)
    entries = _date_filter(
        client.ledger_entries.counted().select_related("case").order_by("date", "pk"), d
    )
    kinds = [
        EntryKind.FEE,
        EntryKind.EXPENSE,
        EntryKind.COLLECTION,
        EntryKind.TRUST_IN,
        EntryKind.TRUST_OUT,
    ]
    by_case: dict = {}
    for e in entries:
        label = tr_title(e.case.display_name) if e.case_id else "Dosyasız hareketler"
        row = by_case.setdefault(label, {"sums": {k: ZERO for k in kinds}, "balance": ZERO})
        row["sums"][e.kind] += e.amount
        row["balance"] += e.balance_effect
    rows, total = [], {k: ZERO for k in kinds}
    total_balance = ZERO
    for label in sorted(by_case):
        data = by_case[label]
        rows.append([label, *[data["sums"][k] for k in kinds], data["balance"]])
        for k in kinds:
            total[k] += data["sums"][k]
        total_balance += data["balance"]
    labels = dict(EntryKind.choices)
    return ReportResult(
        title="Masraf ve Tahsilat Özeti",
        subtitle=f"{tr_title(client.name)} · {_period(d)}",
        columns=[Column("Dosya", "text", 2.4)]
        + [Column(labels[k], "money", 1) for k in kinds]
        + [Column("Bakiye", "money", 1)],
        rows=rows,
        totals=["Toplam", *[total[k] for k in kinds], total_balance],
        summary=[("Dönem sonu bakiye", _tl(total_balance))],
    )


class ClientNoticesForm(PeriodForm):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all())
    field_order = ["client", "start", "end"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start"].label = "Geliş tarihi: başlangıç"
        self.fields["end"].label = "Geliş tarihi: bitiş"


def build_client_notices(d, user):
    """Müvekkile gönderilecek tebligat listesi: ofis içi işlem notu ve kişi bilgisi yok."""
    from apps.imports.models import PortalNotice

    client = _own_client(d, user)
    qs = PortalNotice.objects.filter(resolution_client=client).select_related("resolution_case")
    qs = _date_filter(qs, d, "delivered_at__date").order_by("-delivered_at", "-pk")
    rows = [
        [
            n.delivered_at.date() if n.delivered_at else None, n.sender, n.subject or "Tebligat",
            tr_title(n.resolution_case.display_name) if n.resolution_case else "",
        ]
        for n in qs
    ]  # fmt: skip
    return ReportResult(
        title="Tebligat Raporu",
        subtitle=f"{tr_title(client.name)} · {_period(d)}",
        columns=[
            Column("Geliş tarihi", "date", 0.9),
            Column("Gönderen", "text", 1.6),
            Column("Konu", "text", 3.4),
            Column("Dosya", "text", 2),
        ],
        rows=rows,
        summary=[("Tebligat sayısı", str(len(rows)))],
    )


class ClientTasksForm(BootstrapMixin, forms.Form):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all())
    status = forms.ChoiceField(
        label="Durum", choices=TaskReportForm.STATUS, initial="open", required=False
    )


def build_client_tasks(d, user):
    """Seçilen müvekkilin görevleri (görev raporunun müvekkile özel hali)."""
    _own_client(d, user)
    result = build_tasks(d, user)
    result.title = "Müvekkil Görev Raporu (ofis içi)"
    return result


# 5. Dönem muhasebe raporu ------------------------------------------------------------------
class PeriodAccountingForm(PeriodForm):
    pass


def build_period_accounting(d, user):
    qs = LedgerEntry.objects.active()
    if not can_view_all_office_data(user):
        qs = qs.filter(client__in=filter_visible_clients(Client.objects.all(), user))
    qs = _date_filter(qs, d)
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


# 6. Muhasebe hareketleri -------------------------------------------------------------------
class LedgerReportForm(PeriodForm):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all(), required=False)
    kind = forms.ChoiceField(
        label="Hareket türü", choices=[("", "Tümü"), *EntryKind.choices], required=False
    )
    state = forms.ChoiceField(
        label="Kayıt durumu",
        choices=[
            ("active", "Geçerli kayıtlar"),
            ("cancelled", "İptal edilenler"),
            ("excluded", "Hesap dışı bırakılanlar"),
            ("all", "Tümü"),
        ],
        initial="active",
        required=False,
    )
    source = forms.ChoiceField(
        label="Kaynak",
        choices=[("", "Tümü"), ("office", "Büro kaydı"), ("uyap", "UYAP'tan gelen")],
        required=False,
    )
    field_order = ["client", "kind", "state", "source", "start", "end"]


def build_ledger(d, user):
    qs = LedgerEntry.objects.select_related("client", "case")
    if not can_view_all_office_data(user):
        qs = qs.filter(client__in=filter_visible_clients(Client.objects.all(), user))
    if d.get("client"):
        qs = qs.filter(client=d["client"])
    if d.get("kind"):
        qs = qs.filter(kind=d["kind"])
    state = d.get("state") or "active"
    if state == "active":
        qs = qs.filter(is_cancelled=False, excluded_from_balance=False)
    elif state == "cancelled":
        qs = qs.filter(is_cancelled=True)
    elif state == "excluded":
        qs = qs.filter(excluded_from_balance=True, is_cancelled=False)
    if d.get("source") == "uyap":
        qs = qs.filter(portal_ref__isnull=False)
    elif d.get("source") == "office":
        qs = qs.filter(portal_ref__isnull=True)
    qs = _date_filter(qs, d).order_by("date", "pk")
    rows = []
    for e in qs:
        status = (
            "İptal" if e.is_cancelled else ("Hesap dışı" if e.excluded_from_balance else "Geçerli")
        )
        rows.append(
            [
                e.date, e.get_kind_display(), e.client.name, e.case.archive_reference if e.case else "",
                e.description, e.amount, status, "UYAP" if e.portal_ref else "Büro",
            ]
        )  # fmt: skip
    counted = qs.filter(is_cancelled=False, excluded_from_balance=False)
    totals = counted.totals_by_kind()
    parts = [dict(LedgerReportForm.base_fields["state"].choices)[state], _period(d)]
    if d.get("client"):
        parts.append(str(d["client"]))
    return ReportResult(
        title="Muhasebe Hareketleri",
        subtitle=" · ".join(parts),
        columns=[
            Column("Tarih", "date", 0.8),
            Column("Hareket", "text", 1.3),
            Column("Müvekkil", "text", 1.8),
            Column("Dosya", "text", 0.9),
            Column("Açıklama", "text", 2.4),
            Column("Tutar", "money", 1),
            Column("Durum", "text", 0.8),
            Column("Kaynak", "text", 0.7),
        ],  # fmt: skip
        rows=rows,
        summary=[("Kayıt sayısı", str(len(rows)))]
        + [(label, _tl(totals[k])) for k, label in EntryKind.choices],
    )


# 7. Duruşma raporu -------------------------------------------------------------------------
class HearingReportForm(PeriodForm):
    lawyer = forms.ModelChoiceField(
        label="Sorumlu avukat",
        queryset=User.objects.filter(role__in=["admin", "senior", "lawyer", "intern"]),
        required=False,
    )
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all(), required=False)
    attendance = forms.ChoiceField(
        label="Katılma durumu",
        choices=[
            ("", "Tümü"),
            ("attend", "Katılınacak"),
            ("remote", "E-duruşma"),
            ("excuse", "Mazeret"),
        ],
        required=False,
    )
    missing = forms.BooleanField(
        label="Yalnızca eksik bilgisi olanlar (sonuç, bilgilendirme, sorumlu)", required=False
    )
    field_order = ["start", "end", "lawyer", "client", "attendance", "missing"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start"].label = "Duruşma tarihi: başlangıç"
        self.fields["end"].label = "Duruşma tarihi: bitiş"


def build_hearings(d, user):
    from apps.cases.hearing_list import base_hearings, missing_info_q, needs_action_q
    from apps.cases.models import LIST_KINDS

    qs = base_hearings(user).filter(kind__in=LIST_KINDS)
    if d.get("lawyer"):
        qs = qs.filter(assigned_to=d["lawyer"])
    if d.get("client"):
        qs = qs.filter(Q(client=d["client"]) | Q(case__client=d["client"]))
    att = d.get("attendance")
    if att == "excuse":
        qs = qs.filter(excuse_submitted=True)
    elif att == "remote":
        qs = qs.filter(is_remote=True, excuse_submitted=False)
    elif att == "attend":
        qs = qs.filter(is_remote=False, excuse_submitted=False)
    if d.get("missing"):
        today = timezone.localdate()
        qs = qs.filter(missing_info_q(today) | needs_action_q(today))
    qs = _date_filter(qs, d, "starts_at__date").order_by("starts_at")
    rows = []
    for h in qs:
        local = timezone.localtime(h.starts_at)
        if not h.effective_client:
            informed = "—"
        elif h.client_informed_at or h.client_informed:
            informed = "Bilgilendirildi"
        else:
            informed = "Bekliyor" if h.is_done else "—"
        rows.append(
            [
                local.date(), local.strftime("%H:%M"), h.get_kind_display(),
                h.authority or (h.case.authority if h.case else ""),
                h.case.display_name if h.case else h.title_display, h.effective_client,
                h.assigned_to or "Seçilmedi", h.attendance_label, h.result, informed,
            ]
        )  # fmt: skip
    return ReportResult(
        title="Duruşma Raporu",
        subtitle=f"Duruşma tarihi: {_period(d)}" + (f" · {d['lawyer']}" if d.get("lawyer") else ""),
        columns=[
            Column("Tarih", "date", 0.8),
            Column("Saat", "text", 0.5),
            Column("Tür", "text", 0.9),
            Column("Mahkeme", "text", 1.8),
            Column("Dosya", "text", 1.8),
            Column("Müvekkil", "text", 1.5),
            Column("Sorumlu avukat", "text", 1.2),
            Column("Katılma", "text", 0.9),
            Column("Sonuç", "text", 2.2),
            Column("Müvekkil bilgilendirme", "text", 1.1),
        ],  # fmt: skip
        rows=rows,
        summary=[("Duruşma sayısı", str(len(rows)))],
    )


# 8. Tebligat raporu ------------------------------------------------------------------------
class NoticeReportForm(PeriodForm):
    state = forms.ChoiceField(
        label="İşlem durumu",
        choices=[
            ("all", "Tümü"),
            ("pending", "İşlem bekleyenler"),
            ("task", "Görev oluşturulanlar"),
            ("no_task", "Görev yok denilenler"),
        ],
        initial="all",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start"].label = "Geliş tarihi: başlangıç"
        self.fields["end"].label = "Geliş tarihi: bitiş"


def build_notices(d, user):
    from apps.imports.models import PortalNotice

    qs = PortalNotice.objects.select_related("resolution_case", "resolution_task")
    state = d.get("state") or "all"
    if state == "pending":
        qs = qs.filter(resolved_at__isnull=True)
    elif state == "task":
        qs = qs.filter(resolution_task__isnull=False)
    elif state == "no_task":
        qs = qs.filter(resolved_at__isnull=False, resolution_task__isnull=True)
    qs = _date_filter(qs, d, "delivered_at__date").order_by("-delivered_at", "-pk")
    rows = []
    for n in qs:
        status = (
            "Görev oluşturuldu"
            if n.resolution_task_id
            else ("Görev yok" if n.resolved_at else "Bekliyor")
        )
        rows.append(
            [
                n.delivered_at.date() if n.delivered_at else None,
                n.sender, n.subject or "Tebligat",
                n.resolution_case.display_name if n.resolution_case else "", status,
            ]
        )  # fmt: skip
    return ReportResult(
        title="Tebligat Raporu",
        subtitle=f"{dict(NoticeReportForm.base_fields['state'].choices)[state]} · {_period(d)}",
        columns=[
            Column("Geliş tarihi", "date", 0.9),
            Column("Gönderen", "text", 1.6),
            Column("Konu", "text", 3.4),
            Column("Eşleşen dosya", "text", 2),
            Column("Durum", "text", 1.1),
        ],  # fmt: skip
        rows=rows,
        summary=[("Tebligat sayısı", str(len(rows)))],
    )


REPORTS = {
    # --- Müvekkile gönderilecek raporlar: ofis içi bilgi (sorumlu, arşiv yeri, görev) içermez.
    "muvekkil-dosya-durumu": {
        "title": "Dosya durum raporu", "icon": "bi-folder-symlink", "financial": False,
        "audience": "client", "group": "cases", "form": ClientCasesForm, "build": build_client_cases,
        "desc": "Müvekkilin dosyaları: durum, mahkeme, son gelişme ve sonraki duruşma.",
    },
    "muvekkil-durusmalari": {
        "title": "Duruşma raporu", "icon": "bi-calendar-event", "financial": False,
        "audience": "client", "group": "hearings", "form": ClientHearingsForm,
        "build": build_client_hearings,
        "desc": "Müvekkilin duruşma, ön inceleme ve keşifleri: tarih, saat, mahkeme, açıklama.",
    },
    "cari-ekstre": {
        "title": "Hesap ekstresi", "icon": "bi-journal-text", "financial": True,
        "audience": "client", "group": "accounting", "form": StatementForm, "build": build_statement,
        "desc": "Müvekkilin dönem içindeki geçerli hareketleri, devir ve bakiyesi.",
    },
    "muvekkil-masraf-ozeti": {
        "title": "Masraf ve tahsilat özeti", "icon": "bi-cash-coin", "financial": True,
        "audience": "client", "group": "accounting", "form": ClientSummaryForm,
        "build": build_client_summary,
        "desc": "Dosya bazında vekalet ücreti, masraf, tahsilat ve bakiye toplamları.",
    },
    "muvekkil-tebligatlari": {
        "title": "Tebligat raporu", "icon": "bi-envelope-paper", "financial": False,
        "audience": "client", "group": "notices", "form": ClientNoticesForm,
        "build": build_client_notices,
        "desc": "Müvekkilin dosyalarına gelen tebligatlar: geliş tarihi, gönderen, konu.",
    },
    # --- Ofis raporları (iç kullanım)
    "dosya-raporu": {
        "title": "Dosya raporu", "icon": "bi-folder2-open", "financial": False,
        "audience": "office", "group": "cases", "form": CaseReportForm, "build": build_cases,
        "desc": "Dosyalar türe, duruma, sorumluya, yardımcı sorumluya, müvekkile ve aşamaya göre.",
    },
    "muvekkil-listesi": {
        "title": "Müvekkil listesi", "icon": "bi-people", "financial": False,
        "audience": "office", "group": "clients", "form": ClientReportForm, "build": build_clients,
        "desc": "Müvekkiller türe, sorumluya, vekaletname ve açık görev durumuna göre.",
    },
    "muvekkil-gorevleri": {
        "title": "Müvekkil görev raporu", "icon": "bi-list-check", "financial": False,
        "audience": "office", "group": "tasks", "form": ClientTasksForm, "build": build_client_tasks,
        "desc": "Seçilen müvekkile bağlı görevler (ofis içi).",
    },
    "gorevler": {
        "title": "Görev raporu", "icon": "bi-check2-square", "financial": False,
        "audience": "office", "group": "tasks", "form": TaskReportForm, "build": build_tasks,
        "desc": "Görevler duruma, türe, sorumluya, kontrolcüye, müvekkile ve son güne göre.",
    },
    "borclu-muvekkiller": {
        "title": "Borçlu müvekkiller / alacak listesi", "icon": "bi-cash-stack", "financial": True,
        "audience": "office", "group": "accounting", "form": DebtorsForm, "build": build_debtors,
        "desc": "Bakiyesi (müvekkilin ofise borcu) olan müvekkiller ve toplam alacak.",
    },
    "muhasebe-hareketleri": {
        "title": "Muhasebe hareketleri", "icon": "bi-receipt", "financial": False,
        "audience": "office", "group": "accounting", "form": LedgerReportForm, "build": build_ledger,
        "desc": "Hareketler müvekkile, türe, kayıt durumuna, kaynağa (büro/UYAP) ve tarihe göre.",
    },
    "donem-muhasebe": {
        "title": "Dönem muhasebe raporu", "icon": "bi-bar-chart-line", "financial": True,
        "audience": "office", "group": "accounting", "form": PeriodAccountingForm,
        "build": build_period_accounting,
        "desc": "Aylara göre vekalet ücreti, masraf, tahsilat ve ödeme toplamları.",
    },
    "durusma-raporu": {
        "title": "Duruşma raporu (ofis)", "icon": "bi-calendar2-week", "financial": False,
        "audience": "office", "group": "calendar", "form": HearingReportForm,
        "build": build_hearings,
        "desc": "Duruşma, ön inceleme ve keşifler tarihe, avukata, müvekkile ve katılma durumuna göre.",
    },
    "tebligat-raporu": {
        "title": "Tebligat raporu", "icon": "bi-envelope-paper", "financial": False,
        "audience": "office", "group": "calendar", "form": NoticeReportForm, "build": build_notices,
        "desc": "Tebligatlar geliş tarihine ve işlem durumuna göre.",
    },
}  # fmt: skip

# Rapor kategorileri: müvekkil raporları 4, ofis raporları 5 kategoridir.
CLIENT_GROUPS = [
    ("cases", "Dosyalar"),
    ("hearings", "Duruşmalar"),
    ("accounting", "Hesap"),
    ("notices", "Tebligatlar"),
]
REPORT_GROUPS = [
    ("cases", "Dosya"),
    ("clients", "Müvekkil"),
    ("tasks", "Görev"),
    ("accounting", "Muhasebe"),
    ("calendar", "Duruşma ve tebligat"),
]
