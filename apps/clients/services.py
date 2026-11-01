"""Müvekkili bağlı tüm kayıtlarıyla birlikte silme (yalnızca yönetici, onay sayfasıyla)."""

from django.db import transaction


def deletion_summary(client) -> list[tuple[str, int]]:
    """Silinince birlikte gidecek kayıtların sayısı (onay sayfasında gösterilir)."""
    from apps.accounting.models import LedgerEntry
    from apps.cases.models import Document, Hearing
    from apps.tasks.models import Task

    cases = client.cases.all()
    rows = [
        ("Dosya", cases.count()),
        ("Görev", Task.objects.filter(client=client).count()),
        ("Muhasebe hareketi", LedgerEntry.objects.filter(client=client).count()),
        ("Dosya belgesi", Document.objects.filter(case__in=cases).count()),
        ("Duruşma", Hearing.objects.filter(case__in=cases).count()),
        ("Randevu", client.appointments.count()),
        ("Vekalet", client.powers_of_attorney.count()),
        ("Avukatlık sözleşmesi", client.retainer_agreements.count()),
        (
            "İletişim / IBAN / yetkili",
            client.contacts.count() + client.ibans.count() + client.representatives.count(),
        ),  # fmt: skip
    ]
    return [(label, n) for label, n in rows if n]


@transaction.atomic
def delete_client(client) -> None:
    """Müvekkili; dosyaları, görevleri, muhasebe hareketleri ve randevularıyla birlikte siler.
    Karşı taraf kayıtları başka dosyalarda kullanılabileceği için silinmez. Yüklenen dosyalar
    diskte (ve yedeklerde) kalır."""
    from apps.accounting.models import LedgerEntry
    from apps.tasks.models import Task

    LedgerEntry.objects.filter(client=client).delete()
    Task.objects.filter(client=client).delete()
    client.appointments.all().delete()
    client.cases.all().delete()
    client.delete()
