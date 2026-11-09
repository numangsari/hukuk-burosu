"""Ofis klasöründeki görüntüleme amaçlı tabloları güvenle günceller."""

import datetime as dt
import hashlib
import json
import logging
import os
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path

from django.apps import apps
from django.db import connection, models
from django.utils import timezone
from django.utils.text import capfirst

from apps.office.models import OfficeSettings
from apps.reports.base import Column, ReportResult
from apps.reports.renderers import to_xlsx

DIRECTORY = "Güncel Sistem Listeleri"
STATE_FILE = ".ofis-liste-durumu.json"
SIGNATURE = "hukuk-office-lists-v1"
LOCK_ID = 793401256

logger = logging.getLogger(__name__)

# Gizli bağlantılar, oturum bilgileri ve parolalar hiçbir listede bulunmaz.
# Kullanım dışı duruşma, mesajlaşma ve eski aktarım ekranları dışarıda bırakılır.
SPECS = (
    (
        "Büro Bilgileri",
        "office.OfficeSettings",
        ("name", "address", "phone", "email", "tax_office", "tax_number", "backup_time"),
    ),
    (
        "Kullanıcılar",
        "accounts.User",
        (
            "first_name",
            "last_name",
            "role",
            "title",
            "phone",
            "email",
            "supervisor",
            "is_active",
            "can_view_balances",
        ),
    ),
    (
        "Görev Türleri",
        "office.TaskType",
        ("name", "points", "requires_document", "is_active", "categories"),
    ),
    (
        "Müvekkiller",
        "clients.Client",
        (
            "id",
            "name",
            "kind",
            "tckn",
            "vkn",
            "tax_office",
            "mersis_no",
            "poa_no",
            "responsible_lawyer",
            "responsible_intern",
            "notes",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "Müvekkil İletişim",
        "clients.ClientContact",
        ("client", "kind", "label", "value", "is_primary"),
    ),
    ("Müvekkil Banka", "clients.ClientIban", ("client", "bank", "iban", "holder", "is_primary")),
    (
        "Yetkili Kişiler",
        "clients.ClientRepresentative",
        ("client", "name", "position", "phone", "email"),
    ),
    (
        "Vekaletler",
        "clients.PowerOfAttorney",
        ("client", "notary", "date", "journal_no", "archive_no", "notes", "folder_path"),
    ),
    (
        "Sözleşmeler",
        "clients.RetainerAgreement",
        ("client", "case", "signed_on", "fee_amount", "notes", "folder_path"),
    ),
    (
        "Karşı Taraflar",
        "clients.Party",
        ("id", "name", "kind", "identity_no", "address", "lawyer", "notes"),
    ),
    (
        "Dosyalar",
        "cases.Case",
        (
            "id",
            "client",
            "client_role",
            "case_type",
            "archive_folder_no",
            "archive_no",
            "authority",
            "official_no",
            "official_no_kind",
            "subject",
            "status",
            "stage",
            "uyap_stage",
            "uyap_subject",
            "next_hearing_at",
            "closing_reason",
            "closing_note",
            "value",
            "opened_on",
            "closed_on",
            "decision_date",
            "decision_no",
            "enforcement_type",
            "enforcement_basis",
            "enforcement_amount",
            "responsible_lawyer",
            "responsible_intern",
            "notes",
            "folder_name",
            "created_at",
            "updated_at",
        ),
    ),
    ("Dosya Ek Müvekkiller", "cases.CaseCoClient", ("case", "client", "role")),
    ("Dosya Tarafları", "cases.CaseParty", ("case", "party", "role")),
    (
        "Dosya Geçmişi",
        "cases.CaseEvent",
        ("case", "date", "kind", "title", "description", "created_by", "created_at"),
    ),
    (
        "Dosya Belgeleri",
        "cases.Document",
        (
            "case",
            "title",
            "category",
            "original_name",
            "notes",
            "folder_path",
            "created_by",
            "created_at",
        ),
    ),
    (
        "Hacizler",
        "cases.Seizure",
        (
            "case",
            "debtor",
            "kind",
            "state",
            "employer",
            "bank_name",
            "plate",
            "property_info",
            "address",
            "notice_stage",
            "recipient",
            "related_case_info",
            "asset",
            "seized_on",
            "renewal_on",
            "is_active",
            "notes",
            "created_by",
            "created_at",
        ),
    ),
    ("Haciz Yenilemeleri", "cases.SeizureRenewal", ("seizure", "due_date", "task", "created_at")),
    (
        "Görevler",
        "tasks.Task",
        (
            "id",
            "title",
            "task_type",
            "case",
            "client",
            "assignee",
            "reviewer",
            "due_date",
            "requires_accounting",
            "status",
            "notes",
            "created_by",
            "created_at",
            "completed_at",
        ),
    ),
    (
        "Görev Geçmişi",
        "tasks.TaskEvent",
        ("task", "actor", "kind", "from_status", "to_status", "comment", "created_at"),
    ),
    (
        "Görev Belgeleri",
        "tasks.TaskDocument",
        (
            "task",
            "kind",
            "original_name",
            "version",
            "is_current",
            "uploaded_by",
            "created_at",
            "folder_path",
        ),
    ),
    ("Personel Puanları", "tasks.TaskPoint", ("task", "user", "points", "earned_at")),
    (
        "Muhasebe",
        "accounting.LedgerEntry",
        (
            "id",
            "client",
            "case",
            "kind",
            "amount",
            "date",
            "description",
            "is_cancelled",
            "cancelled_at",
            "cancelled_by",
            "cancel_reason",
            "created_by",
            "created_at",
        ),
    ),
    (
        "Tebligatlar",
        "imports.PortalNotice",
        (
            "sender",
            "subject",
            "delivered_at",
            "read",
            "resolution_client",
            "resolution_case",
            "resolution_task",
            "no_task_reason",
            "resolved_by",
            "resolved_at",
        ),
    ),
    (
        "Tebligat Belgeleri",
        "imports.PortalNoticeDocument",
        ("notice", "original_name", "created_at"),
    ),
    ("UYAP Dosyaları", "imports.PortalCase", ("authority", "number", "category", "status", "case")),
)


class OfficeListsError(Exception):
    pass


def _value(instance, field):
    if instance._meta.label == "cases.Case" and field.name == "stage":
        return instance.stage_label
    if instance._meta.label == "cases.Case" and field.name == "client_role":
        return instance.get_client_role_display()
    if instance._meta.label == "cases.CaseCoClient" and field.name == "role":
        return instance.role_label
    if instance._meta.label == "cases.CaseParty" and field.name == "role":
        return instance.get_role_display()
    if instance._meta.label == "cases.Seizure" and field.name == "state":
        return instance.state_label
    if instance._meta.label == "tasks.Task" and field.name == "status":
        return instance.stage_label or instance.get_status_display()
    if instance._meta.label == "accounts.User" and field.name == "can_view_balances":
        from apps.core.permission_registry import has_perm

        allowed = has_perm(instance, "accounting.balances")
        return "Evet" if allowed else "Hayır"
    value = getattr(instance, field.name)
    if value is None:
        return ""
    if field.choices:
        return getattr(instance, f"get_{field.name}_display")()
    if field.is_relation:
        if value._meta.label in {"clients.Client", "cases.Case", "cases.Seizure", "tasks.Task"}:
            return f"{value} (No: {value.pk})"
        return str(value)
    if isinstance(value, bool):
        return "Evet" if value else "Hayır"
    if isinstance(value, dt.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return value


def _report(title, model_name, field_names):
    model = apps.get_model(model_name)
    fields = [model._meta.get_field(name) for name in field_names]
    relations = [
        field.name
        for field in fields
        if field.is_relation and (field.many_to_one or field.one_to_one)
    ]
    queryset = model.objects.select_related(*relations).order_by("pk")
    if model_name == "tasks.TaskEvent":
        queryset = queryset.exclude(kind="comment")
    rows = []
    for obj in queryset.iterator(chunk_size=500):
        row = [_value(obj, field) for field in fields]
        if model_name == "accounts.User":
            row.append("Evet" if obj.is_office_admin else "Hayır")
        if any(isinstance(value, str) and len(value) > 32767 for value in row):
            raise OfficeListsError("Bir kayıt tablo hücresine sığmayacak kadar uzun.")
        rows.append(row)
        if len(rows) > 1048570:
            raise OfficeListsError("Kayıt sayısı tablonun kapasitesini aşıyor.")
    columns = [
        Column(
            "Kayıt numarası" if field.name == "id" else capfirst(str(field.verbose_name)),
            kind="money"
            if isinstance(field, models.DecimalField)
            else "date"
            if isinstance(field, models.DateField) and not isinstance(field, models.DateTimeField)
            else "text",
            width=2.4
            if field.name
            in {"name", "title", "subject", "description", "notes", "value", "address"}
            else 1.4,
        )
        for field in fields
    ]
    if model_name == "accounts.User":
        columns.append(Column("Yönetici"))
    return ReportResult(
        title=title,
        subtitle="Görüntüleme içindir; buradaki değişiklikler sisteme aktarılmaz.",
        columns=columns,
        rows=rows,
    )


def _activity_report():
    from auditlog.models import LogEntry

    rows = []
    for item in (
        LogEntry.objects.select_related("actor", "content_type")
        .order_by("pk")
        .iterator(chunk_size=500)
    ):
        moment = timezone.localtime(item.timestamp).strftime("%d.%m.%Y %H:%M")
        rows.append(
            [
                moment,
                str(item.actor or ""),
                str(item.content_type),
                item.object_pk,
                item.get_action_display(),
            ]
        )
        if len(rows) > 1048570:
            raise OfficeListsError("İşlem sayısı tablonun kapasitesini aşıyor.")
    return ReportResult(
        title="İşlem Geçmişi",
        subtitle="Görüntüleme içindir; gizli alanlar ve işlem ayrıntıları gösterilmez.",
        columns=[
            Column(label) for label in ("Tarih", "Kullanıcı", "Kayıt türü", "Kayıt no", "İşlem")
        ],
        rows=rows,
    )


def _calendar_report():
    from apps.agenda.services import combined_events

    today = timezone.localdate()
    start = today - dt.timedelta(days=365)
    end = today + dt.timedelta(days=731)
    result = combined_events(start, end)
    if result.configured and result.error and not result.stale:
        raise OfficeListsError("Takvime ulaşılamadı; önceki tablo korundu.")
    rows = []
    for event in result.events:
        start_label = event.start.strftime("%d.%m.%Y" if event.all_day else "%d.%m.%Y %H:%M")
        end_label = (
            event.end.strftime("%d.%m.%Y" if event.all_day else "%d.%m.%Y %H:%M")
            if event.end
            else ""
        )
        rows.append(
            [
                start_label,
                end_label,
                event.title,
                event.location,
                event.description,
                "Görev" if event.source == "task" else "Takvim",
            ]
        )
    subtitle = f"{start:%d.%m.%Y} – {end - dt.timedelta(days=1):%d.%m.%Y}; görüntüleme içindir."
    if result.stale:
        subtitle += " Takvim bilgileri son erişilen kopyadan alındı."
    elif not result.configured:
        subtitle += " Dış takvim bağlı değil; görevler gösterilir."
    return ReportResult(
        title="Takvim",
        subtitle=subtitle,
        columns=[
            Column(label, width=1.4)
            for label in ("Başlangıç", "Bitiş", "Başlık", "Yer", "Açıklama", "Kaynak")
        ],
        rows=rows,
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".ofis-", suffix=".tmp", dir=path.parent, delete=False
        ) as stream:
            temp = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            with suppress(OSError):
                temp.unlink()


def _read_state(directory: Path) -> dict:
    path = directory / STATE_FILE
    if path.is_symlink():
        raise OfficeListsError("Liste durumu güvenli değil.")
    if not path.exists():
        return {"signature": SIGNATURE, "files": {}, "issues": []}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OfficeListsError("Liste durumu okunamadı.") from exc
    if (
        not isinstance(state, dict)
        or state.get("signature") != SIGNATURE
        or not isinstance(state.get("files"), dict)
    ):
        raise OfficeListsError("Liste durumu tanınmıyor; mevcut dosyalar korunuyor.")
    return state


def _save_state(directory: Path, state: dict) -> None:
    _atomic_write(
        directory / STATE_FILE,
        json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    )


@contextmanager
def _single_worker():
    acquired = True
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
            acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired and connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])


def update_office_lists() -> dict:
    """Yalnızca uygulamanın oluşturduğu, değiştirilmemiş tabloları yeniler."""
    root = OfficeSettings.load().documents_root.strip()
    if not root or not Path(root).is_dir():
        raise OfficeListsError("Ofis klasörü erişilebilir değil.")
    directory = Path(root) / DIRECTORY
    if directory.is_symlink():
        raise OfficeListsError("Liste klasörü güvenli değil.")
    with _single_worker() as acquired:
        if not acquired:
            return {"busy": True, "issues": []}
        try:
            directory.mkdir(exist_ok=True)
            state = _read_state(directory)
            if not (directory / STATE_FILE).exists():
                _save_state(directory, state)
            issues = []
            for title, model, fields in (
                *SPECS,
                ("İşlem Geçmişi", None, None),
                ("Takvim", "calendar", None),
            ):
                filename = title + ".xlsx"
                target = directory / filename
                try:
                    if target.is_symlink():
                        raise OfficeListsError("Dosya bağlantı olamaz.")
                    old = state["files"].get(filename, {})
                    if target.exists():
                        if not target.is_file() or not old.get("file_hash"):
                            raise OfficeListsError("Mevcut kullanıcı dosyası korundu.")
                        if _digest(target.read_bytes()) != old["file_hash"]:
                            raise OfficeListsError("Dosya değiştirilmiş; üzerine yazılmadı.")
                    if model is None:
                        report = _activity_report()
                    elif model == "calendar":
                        report = _calendar_report()
                    else:
                        report = _report(title, model, fields)
                    if len(report.rows) > 1048570 or any(
                        isinstance(value, str)
                        and (
                            len(value) > 32767
                            or any(ord(char) < 32 and char not in "\t\n\r" for char in value)
                        )
                        for row in report.rows
                        for value in row
                    ):
                        raise OfficeListsError(
                            "Bir kayıt tablo için çok uzun veya okunamayan karakter içeriyor."
                        )
                    digest = _digest(
                        json.dumps(
                            {
                                "columns": [column.label for column in report.columns],
                                "rows": report.rows,
                            },
                            ensure_ascii=False,
                            default=str,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                    if target.exists() and old.get("data_hash") == digest:
                        continue
                    data = to_xlsx(report, OfficeSettings.load().name)
                    _atomic_write(target, data)
                    state["files"][filename] = {"data_hash": digest, "file_hash": _digest(data)}
                    _save_state(directory, state)
                except (OfficeListsError, OSError) as exc:
                    issues.append(
                        {
                            "file": filename,
                            "reason": str(exc)
                            if isinstance(exc, OfficeListsError)
                            else "Dosya yazılamadı; açıksa kapatın.",
                        }
                    )
                except Exception:
                    # Kayıt içeriği veya gizli veriler hata metnine yazılmaz.
                    issues.append({"file": filename, "reason": "Liste hazırlanamadı."})
            state["checked_at"] = timezone.now().isoformat()
            state["issues"] = issues
            _save_state(directory, state)
            return {"busy": False, "issues": issues}
        except OSError as exc:
            raise OfficeListsError("Liste klasörüne erişilemiyor.") from exc


def office_lists_status() -> dict:
    root = OfficeSettings.load().documents_root.strip()
    if not root:
        return {"message": "Önce ofis klasörünü seçin."}
    directory = Path(root) / DIRECTORY
    if directory.is_symlink():
        return {"message": "Liste klasörü güvenli değil."}
    if not directory.is_dir() or not (directory / STATE_FILE).exists():
        return {"message": "Listeler henüz oluşturulmadı."}
    try:
        state = _read_state(directory)
        checked = dt.datetime.fromisoformat(state["checked_at"])
        if timezone.is_naive(checked):
            checked = timezone.make_aware(checked)
        stale = timezone.now() - checked > dt.timedelta(minutes=3)
        return {
            "checked": timezone.localtime(checked),
            "stale": stale,
            "issues": state.get("issues", []),
        }
    except (OfficeListsError, ValueError, KeyError):
        return {"message": "Liste güncelleme durumu okunamadı."}


def generate_list_files() -> list[tuple[str, bytes]]:
    """Tüm sistem listelerini veritabanının o anki hâlinden üretir: [(dosya adı, xlsx)].

    Üretilemeyen liste atlanır ve günlüğe yazılır (kayıt içeriği değil, yalnızca liste adı ve
    hata türü).
    """
    office_name = OfficeSettings.load().name
    files = []
    for title, model, fields in (
        *SPECS,
        ("İşlem Geçmişi", None, None),
        ("Takvim", "calendar", None),
    ):
        try:
            if model is None:
                report = _activity_report()
            elif model == "calendar":
                report = _calendar_report()
            else:
                report = _report(title, model, fields)
            files.append((f"{title}.xlsx", to_xlsx(report, office_name)))
        except Exception as exc:
            logger.warning("Liste hazırlanamadı (%s): %s", title, type(exc).__name__)
    return files


def export_all_lists_zip() -> bytes:
    """Tüm güncel sistem listelerini bellekte üretip tek bir ZIP arşivi olarak döndürür."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in generate_list_files():
            zf.writestr(name, data)
    return buffer.getvalue()
