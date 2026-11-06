import pytest
from django.test import Client as HttpClient
from django.test import RequestFactory
from django.views.defaults import server_error

pytestmark = pytest.mark.django_db


def test_404_page_is_turkish(lawyer):
    c = HttpClient()
    c.force_login(lawyer)
    r = c.get("/olmayan-sayfa/")
    assert r.status_code == 404
    html = r.content.decode()
    assert "Sayfa bulunamadı" in html and "Page not found" not in html


def test_403_page_is_turkish(intern):
    c = HttpClient()
    c.force_login(intern)
    r = c.post("/dosyalar/1/sil/")  # yalnızca yönetici silebilir
    assert r.status_code == 403
    assert "Erişim yetkiniz yok" in r.content.decode()


def test_500_page_is_turkish_without_request_context():
    response = server_error(RequestFactory().get("/"))
    assert response.status_code == 500
    assert "Beklenmeyen bir hata oluştu" in response.content.decode()


def test_csrf_failure_page_is_turkish(lawyer):
    c = HttpClient(enforce_csrf_checks=True)
    c.force_login(lawyer)
    r = c.post("/gorevler/yeni/", {})
    assert r.status_code == 403
    assert "Oturum doğrulaması başarısız" in r.content.decode()


def test_base_template_loads_htmx_error_notifier(lawyer):
    c = HttpClient()
    c.force_login(lawyer)
    assert "js/htmx-errors.js" in c.get("/").content.decode()


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
