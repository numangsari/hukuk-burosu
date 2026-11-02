"""Açıkça virgülle ayrılmış kişilerin paylaştığı vekalet satırları."""

from collections import Counter
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.clients.models import Client

from .models import PowerOfAttorneyReview, PowerOfAttorneyReviewMember
from .poa_review import SourceRow, get_teams, mark_processed, read_source
from .poa_suggestions import name_key, suggest


@dataclass(frozen=True)
class SuggestedGroup:
    row: SourceRow
    members: tuple


def _parts(row):
    if not row.poa_no or not row.name:
        return ()
    parts = [part.strip() for part in row.name.split(",")]
    if any(not part for part in parts):
        return ()
    candidates = [suggest(SourceRow(row.number, row.reference, part, row.note)) for part in parts]
    if not all(candidate and candidate.kind == "person" for candidate in candidates):
        return ()
    return tuple(candidates)


def build_plan(source_hash, rows):
    """İsim veya numara çakışması olan grup satırlarını incelemeye bırakır."""
    mark_processed(source_hash, rows)
    parsed = {row.number: _parts(row) for row in rows}
    names = Counter()
    for row in rows:
        for part in row.name.split(","):
            candidate = suggest(SourceRow(row.number, row.reference, part.strip(), row.note))
            if candidate:
                names[name_key(candidate.name)] += 1
    numbers = Counter(row.poa_no for row in rows if row.poa_no)
    existing_names = {
        name_key(name) for name in Client.objects.values_list("search_key", flat=True)
    }
    existing_numbers = set(Client.objects.exclude(poa_no=None).values_list("poa_no", flat=True))
    previously_reviewed = set(
        PowerOfAttorneyReview.objects.filter(source_sha256=source_hash).values_list(
            "source_row", flat=True
        )
    )
    groups = []
    for row in rows:
        people = parsed[row.number]
        if row.status != "pending" or row.number in previously_reviewed or len(people) < 2:
            continue
        if numbers[row.poa_no] != 1 or row.poa_no in existing_numbers:
            continue
        if any(
            names[name_key(person.name)] != 1 or name_key(person.name) in existing_names
            for person in people
        ):
            continue
        groups.append(SuggestedGroup(row, people))
    return groups


@transaction.atomic
def execute(source_hash):
    """Her katılımcıyı aynı numarayla oluşturur; tüm satırları birlikte kaydeder."""
    teams = get_teams(lock=True)
    current_hash, rows = read_source()
    if current_hash != source_hash:
        raise ValidationError("Kaynak liste değişti; aktarım yapılmadı.")
    plan = build_plan(current_hash, rows)
    counts = [
        Client.objects.filter(responsible_lawyer=lawyer, responsible_intern=intern).count()
        for lawyer, intern in teams
    ]
    total = 0
    for group in plan:
        if Client.objects.filter(poa_no=group.row.poa_no).exists():
            raise ValidationError(
                "Bir vekalet numarası işlem sırasında kullanıldı; aktarım yapılmadı."
            )
        clients = []
        for person in group.members:
            if any(
                name_key(name) == name_key(person.name)
                for name in Client.objects.values_list("search_key", flat=True)
            ):
                raise ValidationError("Bir müvekkil işlem sırasında eklendi; aktarım yapılmadı.")
            team_index = min(range(len(teams)), key=counts.__getitem__)
            lawyer, intern = teams[team_index]
            notes = []
            if person.annotation:
                notes.append(f"Kaynak açıklaması: {person.annotation}")
            if group.row.note and group.row.note != ".":
                notes.append(f"Kaynak notu: {group.row.note}")
            client = Client(
                kind="person",
                first_name=person.first_name,
                last_name=person.last_name,
                poa_no=group.row.poa_no,
                notes="\n".join(notes),
                responsible_lawyer=lawyer,
                responsible_intern=intern,
            )
            client.full_clean()
            client.save()
            clients.append(client)
            counts[team_index] += 1
            total += 1
        review, _ = PowerOfAttorneyReview.objects.update_or_create(
            source_sha256=current_hash,
            source_row=group.row.number,
            defaults={
                "client": clients[0],
                "created_by": None,
                "source_reference": group.row.reference,
                "source_note": group.row.note,
                "automatic": True,
                "expected_clients": len(clients),
            },
        )
        for client in clients[1:]:
            PowerOfAttorneyReviewMember.objects.create(review=review, client=client)
    if read_source()[0] != current_hash:
        raise ValidationError("Kaynak liste aktarım sırasında değişti; işlem geri alındı.")
    return len(plan), total
