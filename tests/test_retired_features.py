import io

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.cases.models import Hearing
from apps.clients.models import WhatsAppMessage, WhatsAppSettings

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("role", ["intern", "lawyer", "admin_user"])
def test_retired_pages_and_actions_are_unavailable(client, request, role, case_factory):
    case = case_factory()
    hearing = Hearing.objects.create(case=case, starts_at=timezone.now())
    client.force_login(request.getfixturevalue(role))
    urls = [
        "/muvekkiller/mesajlar/",
        "/muvekkiller/mesajlar/ayarlar/",
        "/muvekkiller/mesajlar/bildirim/",
        f"/muvekkiller/mesajlar/muvekkil/{case.client_id}/",
        f"/muvekkiller/mesajlar/muvekkil/{case.client_id}/gonder/",
        f"/dosyalar/{case.pk}/durusma/",
        f"/dosyalar/{case.pk}/durusma/{hearing.pk}/sonuc/",
        f"/dosyalar/{case.pk}/durusma/{hearing.pk}/sil/",
    ]
    for url in urls:
        assert client.get(url).status_code == 404
        assert client.post(url, {}).status_code == 404
    assert Hearing.objects.filter(pk=hearing.pk).exists()
    assert (
        "/muvekkiller/mesajlar/" not in client.get(case.client.get_absolute_url()).content.decode()
    )


def test_retired_sender_ignores_enabled_channel(monkeypatch):
    from apps.clients.messaging import reminders, services

    office = WhatsAppSettings.load()
    office.enabled = True
    office.save()
    message = WhatsAppMessage.objects.create(
        phone_number="905000000001",
        direction="outgoing",
        status="queued",
        body="Örnek",
        occurred_at=timezone.now(),
    )

    def fail():
        pytest.fail("Kullanım dışı gönderici mesaj kuyruğunu işlememeli.")

    monkeypatch.setattr(services, "dispatch_pending", fail)
    monkeypatch.setattr(reminders, "queue_reminders", fail)
    output = io.StringIO()
    call_command("send_whatsapp", stdout=output)
    message.refresh_from_db()
    assert message.status == "queued"
    assert "0 mesaj" in output.getvalue()
