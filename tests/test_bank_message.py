import pytest
from django.test import Client
from django.urls import reverse

from apps.core.whatsapp import get_case_wa_templates, get_client_wa_templates
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db

BANK = "Örnek Bankası\nHesap sahibi: Örnek Hukuk Bürosu\nTR00 0000 0000 0000 0000 0000 00"


def set_bank(value):
    office = OfficeSettings.load()
    office.bank_details = value
    office.save()


def test_no_bank_template_without_details(case_factory):
    case = case_factory()
    assert "Banka Bilgileri" not in get_client_wa_templates(case.client)
    assert "Banka Bilgileri" not in get_case_wa_templates(case)


def test_client_and_case_templates_include_bank_details(case_factory):
    case = case_factory()
    set_bank(BANK)
    client_templates = get_client_wa_templates(case.client)
    case_templates = get_case_wa_templates(case)
    for text in (client_templates["Banka Bilgileri"], case_templates["Banka Bilgileri"]):
        assert BANK in text
        assert "Sayın" in text
    assert case.display_name in case_templates["Banka Bilgileri"]


def test_advance_templates_carry_bank_details_when_set(case_factory):
    case = case_factory()
    set_bank(BANK)
    assert BANK in get_client_wa_templates(case.client)["Masraf / Avans Bilgisi"]
    assert BANK in get_case_wa_templates(case)["Masraf / Avans Talebi"]


def test_advance_templates_still_work_without_bank_details(case_factory):
    case = case_factory()
    assert (
        "iletişime geçmenizi rica ederiz"
        in get_client_wa_templates(case.client)["Masraf / Avans Bilgisi"]
    )
    assert "iletişime geçmenizi rica ederiz" in get_case_wa_templates(case)["Masraf / Avans Talebi"]


def test_admin_can_save_bank_details_in_office_settings(admin_user):
    client = Client()
    client.force_login(admin_user)
    office = OfficeSettings.load()
    data = {
        "section": "ofis",
        "name": office.name,
        "idle_minutes": office.idle_minutes,
        "notice_default_due_days": office.notice_default_due_days,
        "archive_folder_default_capacity": office.archive_folder_default_capacity or 8,
        "bank_details": BANK,
    }
    response = client.post(reverse("accounts:settings") + "?bolum=ofis", data)
    assert response.status_code in (200, 302)
    assert OfficeSettings.load().bank_details == BANK


def test_settings_page_shows_bank_field_to_admin(admin_user):
    client = Client()
    client.force_login(admin_user)
    html = client.get(reverse("accounts:settings") + "?bolum=ofis").content.decode()
    assert 'name="bank_details"' in html
