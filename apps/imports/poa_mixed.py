"""Kaynakta birden fazla kişiyi içeren eski birleşik unvanları ayırır."""

import re
import unicodedata
from dataclasses import dataclass

from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import connection, transaction

from apps.clients.models import Client
from apps.core.text import fold

from .models import PowerOfAttorneyReview, PowerOfAttorneyReviewMember
from .poa_review import SourceRow, get_teams, read_source
from .poa_suggestions import name_key, suggest


@dataclass(frozen=True)
class MixedEntry:
    row: SourceRow
    company: str
    other_kind: str
    other_name: str
    other_first: str = ""
    other_last: str = ""
    annotation: str = ""


def _company(value):
    text = fold(value)
    return bool(
        re.search(r"\b(?:ltd|sti|limited|anonim)\b", text) or re.search(r"\ba\s*\.\s*s\s*\.", text)
    )


def _person(value, row):
    candidate = suggest(SourceRow(row.number, row.reference, value.strip(), row.note))
    return candidate if candidate and candidate.kind == "person" else None


def split_row(row, person_prefix_words=None):
    """Açık ayraçları veya kullanıcının belirlediği isim sınırını kullanır."""
    if not row.poa_no or not row.name:
        return None
    text = unicodedata.normalize("NFC", row.name).strip()
    annotation = ""
    match = re.search(r"\s*\(([^()]*)\)\s*$", text)
    if match and fold(match.group(1)) in {"azil", "azilname"}:
        annotation = match.group(0).strip()
        text = text[: match.start()].strip()
    if person_prefix_words is not None:
        if person_prefix_words not in (2, 3):
            return None
        parts = text.split(None, person_prefix_words)
        if len(parts) != person_prefix_words + 1:
            return None
        person = _person(" ".join(parts[:person_prefix_words]), row)
        company = parts[-1].strip()
        if person and _company(company):
            return MixedEntry(
                row, company, "person", person.name, person.first_name, person.last_name, annotation
            )
        return None
    dash = re.search(r"\s+[-–—]\s+", text)
    if dash and "," not in text[: dash.start()]:
        first, remaining = text[: dash.start()].strip(), text[dash.end() :].strip()
        person = _person(first, row)
        if person and _company(remaining):
            return MixedEntry(
                row,
                remaining,
                "person",
                person.name,
                person.first_name,
                person.last_name,
                annotation,
            )
        person = _person(remaining, row)
        if _company(first) and person:
            return MixedEntry(
                row, first, "person", person.name, person.first_name, person.last_name, annotation
            )
    if "," not in text:
        return None
    first, _, remaining = text.partition(",")
    first, remaining = first.strip(), remaining.strip()
    person = _person(first, row)
    if person and _company(remaining):
        return MixedEntry(
            row, remaining, "person", person.name, person.first_name, person.last_name, annotation
        )
    if _company(first) and _company(remaining):
        return MixedEntry(row, first, "company", remaining, annotation=annotation)
    company, _, final = text.rpartition(",")
    company, final = company.strip(), final.strip()
    person = _person(final, row)
    if person and _company(company):
        return MixedEntry(
            row, company, "person", person.name, person.first_name, person.last_name, annotation
        )
    return None


def _unchanged(client):
    """Kullanıcının üzerinde çalıştığı veya bağlı kayıtları olan birleşikleri değiştirmez."""
    if client.folder_name or client.created_by_id:
        return False
    for relation in client._meta.related_objects:
        try:
            related = getattr(client, relation.get_accessor_name())
            if relation.one_to_one or related.exists():
                return False
        except ObjectDoesNotExist:
            continue
    content_type = ContentType.objects.get_for_model(Client)
    return not LogEntry.objects.filter(
        content_type=content_type, object_pk=str(client.pk), action=LogEntry.Action.UPDATE
    ).exists()


def build_plan(source_hash, rows, approved_existing=None, approved_splits=None):
    """Yalnızca kaynakla aynı ve daha önce değiştirilmemiş birleşik kayıtları seçer."""
    approved_existing = approved_existing or {}
    approved_splits = approved_splits or {}
    previously_reviewed = set(
        PowerOfAttorneyReview.objects.filter(source_sha256=source_hash).values_list(
            "source_row", flat=True
        )
    )
    plan = []
    for row in rows:
        entry = split_row(row, person_prefix_words=approved_splits.get(row.number))
        if not entry or row.number in previously_reviewed:
            continue
        originals = [
            client
            for client in Client.objects.filter(kind="company", poa_no=row.poa_no)
            if name_key(" ".join(client.name.split())) == name_key(" ".join(row.name.split()))
        ]
        if len(originals) != 1 or not _unchanged(originals[0]):
            continue
        original = originals[0]
        if (
            Client.objects.filter(search_key=name_key(entry.company))
            .exclude(pk=original.pk)
            .exists()
        ):
            continue
        others = list(
            Client.objects.filter(search_key=name_key(entry.other_name)).exclude(pk=original.pk)
        )
        if len(others) > 1:
            continue
        if others and not (
            others[0].kind == entry.other_kind
            and (
                others[0].poa_no == row.poa_no or approved_existing.get(row.number) == others[0].pk
            )
        ):
            continue
        plan.append((entry, original.pk, others[0].pk if others else None))
    return plan


@transaction.atomic
def execute(source_hash, approved_existing=None, approved_splits=None):
    """Unvanı düzeltir, diğer kişiyi ekler veya onaylı mevcut kayıtla ilişkilendirir."""
    teams = get_teams(lock=True)
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "LOCK TABLE "
                + connection.ops.quote_name(Client._meta.db_table)
                + " IN SHARE ROW EXCLUSIVE MODE"
            )
    current_hash, rows = read_source()
    if current_hash != source_hash:
        raise ValidationError("Kaynak liste değişti; düzeltme yapılmadı.")
    plan = build_plan(current_hash, rows, approved_existing, approved_splits)
    counts = [
        Client.objects.filter(responsible_lawyer=lawyer, responsible_intern=intern).count()
        for lawyer, intern in teams
    ]
    created = 0
    for entry, original_pk, other_pk in plan:
        original = Client.objects.select_for_update().get(pk=original_pk)
        annotation = f"Kaynak satırında açıklama: {entry.annotation}" if entry.annotation else ""
        if annotation and annotation not in original.notes:
            original.notes = "\n".join(part for part in (original.notes, annotation) if part)
        original.title = entry.company
        original.full_clean()
        original.save()
        if other_pk:
            other = Client.objects.select_for_update().get(pk=other_pk)
        else:
            team_index = min(range(len(teams)), key=counts.__getitem__)
            lawyer, intern = teams[team_index]
            notes = []
            if entry.row.note and entry.row.note != ".":
                notes.append(f"Kaynak notu: {entry.row.note}")
            if annotation:
                notes.append(annotation)
            other = Client(
                kind=entry.other_kind,
                first_name=entry.other_first,
                last_name=entry.other_last,
                title=entry.other_name if entry.other_kind == "company" else "",
                poa_no=entry.row.poa_no,
                notes="\n".join(notes),
                responsible_lawyer=lawyer,
                responsible_intern=intern,
            )
            other.full_clean()
            other.save()
            counts[team_index] += 1
            created += 1
        source_note = "\n".join(
            part for part in (entry.row.note, annotation) if part and part != "."
        )
        review = PowerOfAttorneyReview.objects.create(
            source_sha256=current_hash,
            source_row=entry.row.number,
            source_reference=entry.row.reference,
            source_note=source_note,
            client=original,
            expected_clients=2,
            automatic=True,
        )
        PowerOfAttorneyReviewMember.objects.create(review=review, client=other)
    if read_source()[0] != current_hash:
        raise ValidationError("Kaynak liste düzeltme sırasında değişti; işlem geri alındı.")
    return len(plan), created
