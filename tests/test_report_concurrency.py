from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.utils import timezone

from apps.accounting.models import EntryKind, LedgerEntry
from apps.accounting.services import cancel_entry, create_entry
from apps.office.models import TaskType
from apps.tasks.models import Task
from apps.tasks.services import perform

pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)


@pytest.fixture(scope="module", autouse=True)
def preserve_seed_data(django_db_setup, django_db_blocker):
    # Gerçek işlem denemelerinin temizliği, sonraki çalıştırmanın başlangıç verisini silmesin.
    with django_db_blocker.unblock():
        seed_data = connection.creation.serialize_db_to_string()
    yield
    with django_db_blocker.unblock():
        connection.creation.deserialize_db_from_string(seed_data)


def run_together(operation):
    barrier = Barrier(2)

    def worker():
        try:
            barrier.wait(timeout=10)
            operation()
            return True
        except ValidationError:
            return False
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        return [future.result(timeout=20) for future in futures]


@pytest.mark.parametrize("kind", [EntryKind.TRUST_OUT, EntryKind.OFFSET])
def test_parallel_payments_cannot_overdraw_trust(client_factory, kind):
    owner = client_factory()
    LedgerEntry.objects.create(
        client=owner, kind=EntryKind.TRUST_IN, amount=10000, date=timezone.localdate()
    )

    def pay():
        create_entry(
            LedgerEntry(
                client_id=owner.pk, kind=kind, amount=Decimal("7000"), date=timezone.localdate()
            )
        )

    assert sorted(run_together(pay)) == [False, True]
    assert owner.ledger_entries.filter(kind=kind).count() == 1
    assert owner.ledger_entries.balances()["trust"] == Decimal("3000")


def test_parallel_cancellations_only_cancel_once(client_factory, admin_user):
    entry = LedgerEntry.objects.create(
        client=client_factory(), kind=EntryKind.FEE, amount=10, date=timezone.localdate()
    )

    def cancel():
        cancel_entry(LedgerEntry.objects.get(pk=entry.pk), admin_user, "Örnek düzeltme")

    assert sorted(run_together(cancel)) == [False, True]
    entry.refresh_from_db()
    assert entry.is_cancelled


def test_parallel_approvals_only_publish_once(case_factory, intern, lawyer):
    task = Task.objects.create(
        task_type=TaskType.objects.create(name="Eşzamanlı deneme", requires_document=False),
        title="Örnek görev",
        case=case_factory(),
        assignee=intern,
        reviewer=lawyer,
        due_date=timezone.localdate(),
        status="review",
    )

    def approve():
        perform(Task.objects.get(pk=task.pk), "approve", lawyer)

    assert sorted(run_together(approve)) == [False, True]
    assert task.events.filter(kind="approved").count() == 1
    assert task.case.events.filter(kind="task").count() == 1
