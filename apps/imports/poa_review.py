"""Ofisin vekalet listesini kullanıcının satır satır incelemesi."""

import hashlib
import io
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.text import fold, poa_reference_number, tr_upper

from .models import PowerOfAttorneyReview, PowerOfAttorneyReviewMember

DEFAULT_TEAMS = ()


@dataclass
class SourceRow:
    number: int
    reference: str
    name: str
    note: str
    status: str = "pending"
    client_id: int | None = None
    client_ids: tuple[int, ...] = ()
    automatic: bool = False

    @property
    def poa_no(self):
        return poa_reference_number(self.reference)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def source_path():
    return Path(
        getattr(
            settings,
            "POA_REVIEW_FILE",
            settings.BASE_DIR / "veritabanı entegrasyon" / "-LİSTE VEKALETNAME.xlsx",
        )
    )


def read_source():
    """Dosyayı tek seferde okuyup içeriğe bağlı satır listesini üretir."""
    try:
        data = source_path().read_bytes()
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = workbook.active
        records = sheet.iter_rows(values_only=True)
        header = next(records, ())
        if len(header) < 2 or [fold(_text(v)) for v in header[:2]] != ["sira no", "isim"]:
            raise ValueError("Vekalet listesinin başlıkları tanınmadı.")
        rows = []
        for index, record in enumerate(records, 2):
            values = list(record[:3]) + [None] * max(0, 3 - len(record))
            reference, name, note = (_text(value) for value in values[:3])
            # Adı ve notu boş satır (yalnızca V-numarası) bilgi taşımaz; incelemeye alınmaz.
            if name or note:
                rows.append(SourceRow(index, reference, name, note))
        workbook.close()
    except FileNotFoundError as exc:
        raise ValueError("Vekalet listesi sunucuda bulunamadı.") from exc
    except (OSError, BadZipFile, InvalidFileException, KeyError) as exc:
        raise ValueError("Vekalet listesi okunamadı.") from exc
    return hashlib.sha256(data).hexdigest(), rows


def _exact_name(value):
    return tr_upper(unicodedata.normalize("NFC", " ".join(value.split())))


def row_match_keys(row):
    """Kullanıcının seçebileceği tam isim ve virgülle ayrılmış bölüm anahtarları."""
    values = [row.name, *row.name.split(",")]
    return {
        fold(unicodedata.normalize("NFC", " ".join(value.split())))
        for value in values
        if value.strip()
    }


def mark_processed(source_hash, rows):
    """Önceki aktarımı numara ve tam adla; yeni işlemleri satır bağlantısıyla tanır."""
    reviewed = {
        review.source_row: review
        for review in PowerOfAttorneyReview.objects.filter(
            source_sha256=source_hash
        ).prefetch_related("members")
    }
    numbers = defaultdict(list)
    for client in Client.objects.filter(poa_no__isnull=False):
        numbers[client.poa_no].append(client)
    for row in rows:
        row.status, row.client_id, row.client_ids, row.automatic = "pending", None, (), False
        review = reviewed.get(row.number)
        if review:
            ids = [review.client_id] + [member.client_id for member in review.members.all()]
            ids = [pk for pk in ids if pk is not None]
            if ids:
                row.client_ids = tuple(ids)
                row.client_id, row.automatic = ids[0], review.automatic
                row.status = "done" if len(set(ids)) == review.expected_clients else "incomplete"
                continue
        if row.poa_no in numbers:
            owners = numbers[row.poa_no]
            exact = [
                client
                for client in owners
                if row.name and _exact_name(client.name) == _exact_name(row.name)
            ]
            row.client_ids = tuple(client.pk for client in owners)
            row.client_id = (exact[0] if len(exact) == 1 else owners[0]).pk
            row.status = "done" if len(exact) == 1 else "conflict"
            if row.status == "done":
                row.client_ids = (row.client_id,)
    return rows


def get_teams(*, lock=False):
    configured = getattr(settings, "POA_REVIEW_TEAMS", DEFAULT_TEAMS)
    usernames = {username for team in configured for username in team}
    qs = User.objects.filter(username__in=usernames, is_active=True).order_by("pk")
    if lock:
        qs = qs.select_for_update()
    users = {user.username: user for user in qs}
    teams = []
    for lawyer_name, intern_name in configured:
        lawyer, intern = users.get(lawyer_name), users.get(intern_name)
        if (
            not lawyer
            or not intern
            or lawyer.role not in (User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER)
        ):
            raise ValidationError("Sorumlu ekip bulunamadı; kullanıcı ayarlarını kontrol edin.")
        if intern.role not in (User.Role.INTERN, User.Role.PARALEGAL):
            raise ValidationError("Sorumlu ekip bulunamadı; kullanıcı ayarlarını kontrol edin.")
        teams.append((lawyer, intern))
    if not teams:
        raise ValidationError("Sorumlu ekip bulunamadı; kullanıcı ayarlarını kontrol edin.")
    return teams


def _attach_review(existing, *, client, source_hash, row, user):
    if not existing:
        return PowerOfAttorneyReview.objects.create(
            source_sha256=source_hash,
            source_row=row.number,
            source_reference=row.reference,
            source_note=row.note,
            client=client,
            created_by=user,
        )
    member_ids = list(existing.members.values_list("client_id", flat=True))
    linked = {pk for pk in [existing.client_id, *member_ids] if pk is not None}
    if client.pk in linked or len(linked) >= existing.expected_clients:
        raise ValidationError("Bu satır daha önce kaydedilmiş. Listeyi yenileyin.")
    if existing.client_id is None:
        existing.client = client
    else:
        vacant = existing.members.filter(client__isnull=True).first()
        if vacant:
            vacant.client = client
            vacant.save(update_fields=["client"])
        else:
            PowerOfAttorneyReviewMember.objects.create(review=existing, client=client)
    existing.created_by = user
    existing.automatic = False
    existing.source_reference, existing.source_note = row.reference, row.note
    existing.save(
        update_fields=["client", "created_by", "source_reference", "source_note", "automatic"]
    )
    return existing


@transaction.atomic
def save_review(*, form, source_hash, row, user):
    """Seçilen kaydı ve satır bağlantısını tek işlemde yazar."""
    if read_source()[0] != source_hash:
        raise ValidationError("Kaynak liste değişmiş. Sayfayı yenileyip satırı yeniden inceleyin.")
    teams = get_teams(lock=True)
    existing = (
        PowerOfAttorneyReview.objects.select_for_update()
        .filter(source_sha256=source_hash, source_row=row.number)
        .first()
    )
    if existing and existing.client_id and existing.expected_clients == 1:
        raise ValidationError("Bu satır daha önce kaydedilmiş. Listeyi yenileyin.")
    if mark_processed(source_hash, [row])[0].status == "done":
        raise ValidationError("Bu satır zaten sistemde bulunuyor. Listeyi yenileyin.")

    client = form.save(commit=False)
    if client.poa_no and Client.objects.filter(poa_no=client.poa_no).exists():
        known_group = existing and existing.expected_clients > 1 and client.poa_no == row.poa_no
        if not known_group and not form.cleaned_data["confirm_shared_poa"]:
            raise ValidationError("Bu vekalet numarası kullanılıyor. Paylaşıldığını doğrulayın.")
    display_name = (
        f"{client.first_name} {client.last_name}".strip()
        if client.kind == "person"
        else client.title.strip()
    )
    if (
        Client.objects.filter(search_key=fold(display_name)).exists()
        and not form.cleaned_data["confirm_duplicate"]
    ):
        raise ValidationError("Bu adla bir müvekkil var. Ayrı bir kişi olduğunu doğrulayın.")

    chosen = form.cleaned_data["team"]
    if chosen == "auto":
        lawyer, intern = min(
            teams,
            key=lambda pair: Client.objects.filter(
                responsible_lawyer=pair[0], responsible_intern=pair[1]
            ).count(),
        )
    else:
        lawyer, intern = next((team for team in teams if str(team[1].pk) == chosen), (None, None))
        if not lawyer or not intern:
            raise ValidationError("Seçilen ekip artık kullanılmıyor; sayfayı yenileyin.")
    client.responsible_lawyer = lawyer
    client.responsible_intern = intern
    client.created_by = user
    client.full_clean()
    client.save()
    _attach_review(existing, client=client, source_hash=source_hash, row=row, user=user)
    return client


@transaction.atomic
def link_existing(*, client_id, source_hash, row, user):
    """Kullanıcının seçtiği mevcut müvekkille satırı ilişkilendirir; müvekkili değiştirmez."""
    if read_source()[0] != source_hash:
        raise ValidationError("Kaynak liste değişmiş. Sayfayı yenileyip satırı yeniden inceleyin.")
    client = Client.objects.select_for_update().filter(pk=client_id).first()
    if not client or not (
        client.search_key in row_match_keys(row) or (row.poa_no and client.poa_no == row.poa_no)
    ):
        raise ValidationError("Bu satır için seçilen müvekkil bulunamadı. Sayfayı yenileyin.")
    existing = (
        PowerOfAttorneyReview.objects.select_for_update()
        .filter(source_sha256=source_hash, source_row=row.number)
        .first()
    )
    if (existing and existing.client_id and existing.expected_clients == 1) or mark_processed(
        source_hash, [row]
    )[0].status == "done":
        raise ValidationError("Bu satır daha önce kaydedilmiş. Listeyi yenileyin.")
    _attach_review(existing, client=client, source_hash=source_hash, row=row, user=user)
