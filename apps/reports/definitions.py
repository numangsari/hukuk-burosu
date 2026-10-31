"""Rapor tanımları. Her rapor: parametre formu + build(params, user) -> ReportResult."""

from collections import defaultdict
from decimal import Decimal

from django import forms
from django.db.models import Count, Min, Q
from django.utils import timezone

from apps.accounting.models import EntryKind, LedgerEntry
from apps.accounts.models import User
from apps.cases.models import Case, CaseStatus, CaseType, HearingStatus
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
    opening_cari = opening_trust = ZERO
    if d.get("start"):
        before = entries.filter(date__lt=d["start"]).balances()
        opening_cari, opening_trust = before["cari"], before["trust"]
    entries = _date_filter(entries, d)
    cari, trust = opening_cari, opening_trust
    rows = []
    if d.get("start"):
        rows.append([d["start"], "Devir", "", "", None, cari, trust])
    for e in entries:
        cari += e.cari_effect
        trust += e.trust_effect
        rows.append(
            [
                e.date,
                e.get_kind_display(),
                e.case.archive_no if e.case else "",
                e.description,
                e.amount,
                cari,
                trust,
            ]
        )
    return ReportResult(
        title="Müvekkil Cari Hesap Ekstresi",
        subtitle=f"{client.name} · {_period(d)}",
        columns=[
            Column("Tarih", "date", 0.8),
            Column("Hareket", "text", 1.3),
            Column("Dosya", "text", 0.8),
            Column("Açıklama", "text", 2.2),
            Column("Tutar", "money", 1),
            Column("Cari bakiye", "money", 1),
            Column("Emanet", "money", 1),
        ],  # fmt: skip
        rows=rows,
        summary=[
            ("Müvekkil", client.name),
            ("Kimlik no", client.identity_no or "—"),
            ("Dönem sonu cari bakiye", _tl(cari)),
            ("Dönem sonu emanet", _tl(trust)),
        ],
    )


# 2. Borçlu müvekkiller ---------------------------------------------------------------------
class DebtorsForm(BootstrapMixin, forms.Form):
    lawyer = forms.ModelChoiceField(
        label="Sorumlu avukat",
        queryset=User.objects.filter(role__in=["admin", "lawyer"]),
        required=False,
    )
    include_zero = forms.BooleanField(label="Borcu olmayanları da göster", required=False)


def build_debtors(d, user):
    from apps.clients.views import annotate_list_values

    qs = annotate_list_values(Client.objects.select_related("responsible_lawyer")).filter(
        is_active=True
    )
    if d.get("lawyer"):
        qs = qs.filter(responsible_lawyer=d["lawyer"])
    if not d.get("include_zero"):
        qs = qs.filter(balance__gt=0)
    rows, total = [], ZERO
    for c in qs.order_by("-balance", "name"):
        trust = c.ledger_entries.balances()["trust"]
        rows.append(
            [c.name, c.responsible_lawyer, c.case_count, c.balance, trust, c.balance - trust]
        )
        total += c.balance
    return ReportResult(
        title="Borçlu Müvekkiller / Alacak Listesi",
        subtitle=f"{timezone.localdate():%d.%m.%Y} itibarıyla"
        + (f" · {d['lawyer']}" if d.get("lawyer") else ""),
        columns=[
            Column("Müvekkil", "text", 2.2),
            Column("Sorumlu avukat", "text", 1.4),
            Column("Dosya", "int", 0.6),
            Column("Cari bakiye", "money", 1.1),
            Column("Emanet", "money", 1.1),
            Column("Net", "money", 1.1),
        ],  # fmt: skip
        rows=rows,
        totals=["Toplam", "", "", total, None, None],
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
        [t.due_date, t.title, t.task_type.name, f"{t.case.archive_no} · {t.client}", t.assignee, t.reviewer,
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
        choices=[("open", "Açık dosyalar"), *CaseStatus.choices, ("all", "Tümü")],
        initial="open",
        required=False,
    )
    lawyer = forms.ModelChoiceField(
        label="Sorumlu avukat",
        queryset=User.objects.filter(role__in=["admin", "lawyer"]),
        required=False,
    )


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
    qs = qs.annotate(open_tasks=Count("tasks", filter=Q(tasks__status__in=OPEN_STATUSES))).order_by(
        "archive_no"
    )
    rows = [
        [k.archive_no, k.get_case_type_display(), k.subject, k.client.name, f"{k.authority} {k.official_no}".strip(),
         k.get_status_display() + (f" / {k.get_stage_display()}" if k.stage else ""), k.responsible_lawyer, k.open_tasks]
        for k in qs
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
            Column("Konu", "text", 2),
            Column("Müvekkil", "text", 1.6),
            Column("Merci / Resmi no", "text", 1.8),
            Column("Durum", "text", 1),
            Column("Avukat", "text", 1.2),
            Column("Açık görev", "int", 0.6),
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
            ("Ofis geliri (müvekkilden tahsilat + mahsup)", _tl(t["collection"] + t["offset"])),
            ("Tahakkuk eden vekalet ücreti", _tl(t["fee"])),
            ("Müvekkil adına masraf", _tl(t["expense"])),
            ("Emanet hareketi (giren / çıkan)", f"{_tl(t['trust_in'])} / {_tl(t['trust_out'])}"),
        ],
    )


def _tl(v):
    from .base import fmt

    return fmt(v, "money")


# 6. Müvekkil bazlı dosya son durum raporu --------------------------------------------------
class ClientCasesForm(BootstrapMixin, forms.Form):
    client = forms.ModelChoiceField(label="Müvekkil", queryset=Client.objects.all(), required=False,
                                    help_text="Boş bırakılırsa tüm aktif müvekkiller")  # fmt: skip
    include_closed = forms.BooleanField(label="Kapanmış dosyaları da göster", required=False)


def build_client_cases(d, user):
    clients = (
        [d["client"]] if d.get("client") else Client.objects.filter(is_active=True).order_by("name")
    )
    now = timezone.now()
    rows = []
    for c in clients:
        cases = c.cases.all()
        if not d.get("include_closed"):
            cases = cases.exclude(status=CaseStatus.CLOSED)
        cases = cases.annotate(
            next_hearing=Min("hearings__starts_at", filter=Q(hearings__status=HearingStatus.PLANNED, hearings__starts_at__gte=now)),
            open_tasks=Count("tasks", filter=Q(tasks__status__in=OPEN_STATUSES), distinct=True),
        ).order_by("archive_no")  # fmt: skip
        for k in cases:
            last = k.events.order_by("-date", "-created_at").first()
            rows.append([
                c.name, k.archive_no, k.subject, k.get_status_display() + (f" / {k.get_stage_display()}" if k.stage else ""),
                f"{timezone.localtime(k.next_hearing):%d.%m.%Y %H:%M}" if k.next_hearing else "",
                k.open_tasks, f"{last.date:%d.%m.%Y} {last.title}" if last else "",
            ])  # fmt: skip
    return ReportResult(
        title="Dosyaların Son Durumu",
        subtitle=(d["client"].name if d.get("client") else "Tüm aktif müvekkiller")
        + f" · {timezone.localdate():%d.%m.%Y}",
        columns=[
            Column("Müvekkil", "text", 1.5),
            Column("Arşiv no", "text", 0.7),
            Column("Konu", "text", 1.7),
            Column("Durum", "text", 1),
            Column("Sonraki duruşma", "text", 1),
            Column("Açık görev", "int", 0.6),
            Column("Son gelişme", "text", 2.4),
        ],  # fmt: skip
        rows=rows,
        summary=[("Dosya sayısı", str(len(rows)))],
    )


REPORTS = {
    "cari-ekstre": {
        "title": "Müvekkil cari ekstresi", "icon": "bi-journal-text", "financial": True, "form": StatementForm,
        "build": build_statement, "desc": "Bir müvekkilin dönem içindeki tüm hareketleri, devir ve bakiyeleri.",
    },
    "borclu-muvekkiller": {
        "title": "Borçlu müvekkiller / alacak listesi", "icon": "bi-cash-stack", "financial": True,
        "form": DebtorsForm, "build": build_debtors, "desc": "Cari bakiyesi olan müvekkiller ve toplam alacak.",
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
        "desc": "Aylara göre vekalet ücreti, masraf, tahsilat, emanet ve mahsup toplamları.",
    },
    "dosya-son-durum": {
        "title": "Müvekkil bazlı dosya son durumu", "icon": "bi-clipboard-data", "financial": False,
        "form": ClientCasesForm, "build": build_client_cases,
        "desc": "Her dosyanın durumu, sonraki duruşması, açık görevleri ve son gelişmesi.",
    },
}  # fmt: skip
