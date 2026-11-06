"""Teknik inceleme (docs/inceleme-2026-11.md) UI maddelerinin sunucu çıktısı denetimleri."""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import LedgerEntry

pytestmark = pytest.mark.django_db


def test_client_balance_shows_direction_label(admin_client_logged, client_factory):
    debtor = client_factory(name="BORÇLU MÜVEKKİL")
    LedgerEntry.objects.create(
        client=debtor, kind="fee", amount=Decimal("100.00"), date=timezone.localdate()
    )
    creditor = client_factory(name="ALACAKLI MÜVEKKİL")
    LedgerEntry.objects.create(
        client=creditor, kind="trust_in", amount=Decimal("50.00"), date=timezone.localdate()
    )

    html = admin_client_logged.get(reverse("clients:list")).content.decode()

    assert 'class="bal-tag ms-1" title="Müvekkil ofise borçlu">Alacak<' in html
    assert 'class="bal-tag owed ms-1" title="Ofis müvekkile borçlu">Borç<' in html
    assert "text-debt" not in html


def test_client_detail_balance_strip_uses_label_not_red(admin_client_logged, client_factory):
    c = client_factory()
    LedgerEntry.objects.create(
        client=c, kind="fee", amount=Decimal("100.00"), date=timezone.localdate()
    )
    html = admin_client_logged.get(reverse("clients:detail", args=[c.pk])).content.decode()
    assert "balance-strip" in html
    assert "Alacağımız" in html
    assert 'class="bal-value neg"' not in html


def test_backup_alert_can_be_hidden_for_today(admin_client_logged):
    html = admin_client_logged.get("/").content.decode()
    assert "Son 2 gündür başarılı yedek alınmadı." in html
    assert 'aria-label="Bugün için gizle"' in html


def test_hearing_list_filters_apply_without_button(lawyer_client):
    html = lawyer_client.get(reverse("hearings:list")).content.decode()
    assert 'hx-trigger="input changed delay:300ms from:input[name=q], change, submit"' in html
    assert "Filtrele</button>" not in html


def test_case_form_number_row_wraps(lawyer_client):
    html = lawyer_client.get(reverse("cases:create")).content.decode()
    assert 'class="case-number-row"' in html
    assert "width: 125px" not in html
