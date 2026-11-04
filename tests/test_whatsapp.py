import datetime as dt

import pytest
from django.utils import timezone

from apps.cases.models import Hearing, HearingKind, HearingStatus
from apps.clients.models import Client, ClientContact, ClientRepresentative, ContactKind, PersonKind
from apps.core.templatetags.ui import clean_wa_phone, json_attr, wa_url
from apps.core.whatsapp import (
    build_whatsapp_url,
    clean_phone_for_whatsapp,
    format_case_info_message,
    format_hearing_reminder_message,
    format_hearing_result_message,
    get_case_wa_templates,
    get_hearing_wa_templates,
)
from apps.office.models import OfficeSettings


@pytest.mark.parametrize(
    "input_val, expected",
    [
        ("0532 123 45 67", "905321234567"),
        ("+90 (532) 123 45 67", "905321234567"),
        ("5321234567", "905321234567"),
        ("0212 234 56 78", "902122345678"),
        ("+49 170 1234567", "491701234567"),
        ("0049 170 1234567", "491701234567"),
        ("+1 555 123 4567", "15551234567"),
        ("", ""),
        (None, ""),
        ("123", ""),  # çok kısa
        ("01234567890123456789", ""),  # çok uzun
        ("gecersiz", ""),
    ],
)
def test_clean_phone_for_whatsapp(input_val, expected):
    assert clean_phone_for_whatsapp(input_val) == expected


def test_build_whatsapp_url():
    # Doğrudan masaüstü WhatsApp URI'si
    assert build_whatsapp_url("0532 123 45 67") == "whatsapp://send?phone=905321234567"
    url_app = build_whatsapp_url("0532 123 45 67", "Merhaba Dünya! Test 123.")
    assert url_app.startswith("whatsapp://send?phone=905321234567&text=")
    assert "Merhaba%20D%C3%BCnya%21%20Test%20123." in url_app

    # Geçersiz numara
    assert build_whatsapp_url("invalid", "Mesaj") == ""


@pytest.mark.django_db
def test_whatsapp_message_formatters(case_factory):
    office = OfficeSettings.load()
    office.name = "Adalet Hukuk Bürosu"
    office.save(update_fields=["name"])

    case = case_factory(subject="Alacak davası")
    hearing_dt = timezone.make_aware(dt.datetime(2026, 6, 15, 10, 30))
    hearing = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=hearing_dt,
        authority="İstanbul 3. Asliye Hukuk Mahkemesi",
        room="D-4",
        is_remote=True,
        result="Bilirkişi raporu bekleniyor.",
        decisions="1. Bilirkişiye ek süre verildi.\n2. Gelecek celseye kadar rapor tanzim edilecek.",
    )

    # Duruşma sonucu mesajı
    result_msg = format_hearing_result_message(
        hearing, next_hearing_dt="20.10.2026 saat 11:00", office_name=office.name
    )
    assert case.client.name in result_msg
    assert "İstanbul 3. Asliye Hukuk Mahkemesi" in result_msg
    assert "Bilirkişiye ek süre verildi." in result_msg
    assert "20.10.2026 saat 11:00" in result_msg
    assert "Adalet Hukuk Bürosu" in result_msg

    # Duruşma hatırlatma mesajı
    reminder_msg = format_hearing_reminder_message(hearing, office_name=office.name)
    assert case.client.name in reminder_msg
    assert "15.06.2026 saat 10:30" in reminder_msg
    assert "Salon: D-4" in reminder_msg
    assert "E-duruşma" in reminder_msg

    # Dosya bilgilendirme mesajı
    case_msg = format_case_info_message(case, office_name=office.name)
    assert case.display_name in case_msg
    assert case.client.name in case_msg

    # Şablon sözlükleri
    h_templates = get_hearing_wa_templates(hearing, office_name=office.name)
    assert "Duruşma Sonucu" in h_templates
    assert "Duruşma Hatırlatması" in h_templates

    c_templates = get_case_wa_templates(case, office_name=office.name)
    assert "Dosya Bilgilendirmesi" in c_templates
    assert "Masraf / Avans Talebi" in c_templates


@pytest.mark.django_db
def test_client_and_hearing_whatsapp_properties(case_factory):
    case = case_factory()
    client = case.client

    # Başlangıçta telefon yok
    assert client.primary_phone == ""
    assert client.whatsapp_phone == ""

    # İkincil telefon ekle
    sec_contact = ClientContact.objects.create(
        client=client,
        kind=ContactKind.PHONE,
        value="0212 999 88 77",
        is_primary=False,
    )
    assert client.primary_phone == "0212 999 88 77"
    assert client.whatsapp_phone == "902129998877"
    assert sec_contact.whatsapp_phone == "902129998877"

    # Birincil cep telefonu ekle
    prim_contact = ClientContact.objects.create(
        client=client,
        kind=ContactKind.PHONE,
        value="0532 999 00 11",
        is_primary=True,
    )
    # primary_phone artık birincili getirmeli
    assert client.primary_phone == "0532 999 00 11"
    assert client.whatsapp_phone == "905329990011"
    assert prim_contact.whatsapp_phone == "905329990011"

    # Tüzel kişi temsilcisi
    company = Client.objects.create(
        kind=PersonKind.COMPANY,
        title="ABC Anonim Şirketi",
        responsible_lawyer=case.responsible_lawyer,
    )
    rep = ClientRepresentative.objects.create(
        client=company,
        name="Mehmet Yetkili",
        phone="0542 111 22 33",
    )
    assert rep.whatsapp_phone == "905421112233"

    # Hearing üzerinden client_phone kontrolü
    hearing = Hearing.objects.create(
        case=case,
        starts_at=timezone.now(),
    )
    assert hearing.effective_client == client
    assert hearing.client_phone == "0532 999 00 11"
    assert hearing.client_whatsapp_phone == "905329990011"


def test_ui_whatsapp_template_tags():
    assert clean_wa_phone("0532 123 45 67") == "905321234567"
    assert wa_url("0532 123 45 67", "Selam") == "whatsapp://send?phone=905321234567&text=Selam"

    # json_attr filtresi
    assert json_attr(None) == ""
    assert json_attr("test") == "test"
    escaped = json_attr({"baslik": "Duruşma:\nSaat 10:00", "not": 'Önemli "Not"'})
    assert "&quot;baslik&quot;" in escaped
    assert "Duruşma:\\nSaat 10:00" in escaped


@pytest.mark.django_db
def test_whatsapp_ui_pages_render(lawyer_client, case_factory):
    from django.urls import reverse

    case = case_factory(subject="Test Dosyası")
    client = case.client
    ClientContact.objects.create(
        client=client,
        kind=ContactKind.PHONE,
        value="0532 111 22 33",
        is_primary=True,
    )
    Hearing.objects.create(
        case=case,
        starts_at=timezone.now() + dt.timedelta(days=2),
        authority="İstanbul 1. Asliye Hukuk Mahkemesi",
        status=HearingStatus.PLANNED,
    )

    # Müvekkil sayfası WhatsApp modal ve butonlarını içermeli
    resp_client = lawyer_client.get(client.get_absolute_url())
    assert resp_client.status_code == 200
    assert "whatsappModal" in resp_client.content.decode("utf-8")
    assert "bi-whatsapp" in resp_client.content.decode("utf-8")

    # Dosya sayfası
    resp_case = lawyer_client.get(case.get_absolute_url())
    assert resp_case.status_code == 200
    assert "whatsappModal" in resp_case.content.decode("utf-8")
    assert "bi-whatsapp" in resp_case.content.decode("utf-8")

    # Takvim / duruşma listesi
    resp_cal = lawyer_client.get(reverse("agenda:calendar") + "?view=list")
    assert resp_cal.status_code == 200
    assert "whatsappModal" in resp_cal.content.decode("utf-8")
