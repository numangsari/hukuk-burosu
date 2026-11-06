"""Sağlamlık testleri: yükleme içerik denetimi, Türkçe hata sayfaları, HTMX hata bildirimi,
haciz görevi middleware'inin istek akışını bozmaması."""

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import get_template
from django.urls import reverse

from apps.cases.models import Document
from apps.core.uploads import validate_upload

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "name, content",
    [
        ("belge.pdf", b"%PDF-1.7 icerik"),
        ("resim.png", b"\x89PNG\r\n\x1a\nicerik"),
        ("foto.jpg", b"\xff\xd8\xfficerik"),
        ("dilekce.docx", b"PK\x03\x04icerik"),
        ("eski.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1icerik"),
        ("tablo.xlsx", b"PK\x03\x04icerik"),
        ("tarama.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 icerik"),
        ("not.txt", b"serbest metin"),
    ],
)
def test_matching_signature_is_accepted(name, content):
    validate_upload(SimpleUploadedFile(name, content))


@pytest.mark.parametrize(
    "name, content",
    [
        ("sahte.pdf", b"<script>alert(1)</script>"),
        ("sahte.png", b"GIF89a icerik"),
        ("sahte.docx", b"%PDF-1.4 icerik"),
        ("sahte.doc", b"PK\x03\x04icerik"),
        ("bos.pdf", b""),
    ],
)
def test_mismatched_signature_is_rejected(name, content):
    with pytest.raises(ValidationError, match="içeriği"):
        validate_upload(SimpleUploadedFile(name, content))


def test_document_upload_view_rejects_fake_pdf(case_factory, lawyer_client):
    case = case_factory()
    r = lawyer_client.post(
        reverse("cases:document_upload", args=[case.pk]),
        {
            "title": "sahte",
            "category": "other",
            "file": SimpleUploadedFile("sahte.pdf", b"<html>"),
        },
    )
    assert "file" in r.context["document_form"].errors
    assert not Document.objects.exists()


def test_unknown_url_renders_turkish_404(lawyer_client):
    r = lawyer_client.get("/bu-adres-yok/")
    assert r.status_code == 404
    assert "Sayfa bulunamadı" in r.content.decode()


def test_500_template_is_turkish_and_context_free():
    html = get_template("500.html").render({})
    assert "Beklenmeyen bir hata oluştu" in html


def test_pages_include_htmx_error_notifier(lawyer_client):
    html = lawyer_client.get(reverse("tasks:list")).content.decode()
    assert "htmx:responseError" in html
    assert "htmx:sendError" in html


def test_seizure_check_failure_does_not_break_request(lawyer_client, monkeypatch):
    def broken():
        raise RuntimeError("geçici veritabanı hatası")

    monkeypatch.setattr("apps.cases.middleware.create_due_tasks", broken)
    cache.delete("seizure-tasks-check")
    try:
        r = lawyer_client.get(reverse("tasks:list"))
    finally:
        cache.delete("seizure-tasks-check")
    assert r.status_code == 200


def test_radio_and_checkbox_groups_do_not_get_full_width_form_control():
    from django import forms

    from apps.core.forms import BootstrapMixin

    class SampleForm(BootstrapMixin, forms.Form):
        choice = forms.ChoiceField(
            choices=[("var", "Var"), ("yok", "Yok")], widget=forms.RadioSelect
        )
        tags = forms.MultipleChoiceField(
            choices=[("a", "A")], widget=forms.CheckboxSelectMultiple, required=False
        )

    form = SampleForm()
    for name in ("choice", "tags"):
        css = form.fields[name].widget.attrs.get("class", "")
        assert "form-control" not in css
        assert "form-check-input" in css
