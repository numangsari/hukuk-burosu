import pytest
from django.test import override_settings
from django.urls import reverse

from apps.office.forms import AllowedHostsForm
from apps.office.models import OfficeSettings
from config.hosts import DynamicAllowedHosts, parse_hosts


def test_parse_hosts_accepts_mixed_separators():
    assert parse_hosts("Buro-Sunucu, 192.168.1.5;\n10.0.0.2  ") == [
        "buro-sunucu",
        "192.168.1.5",
        "10.0.0.2",
    ]


@pytest.mark.django_db
def test_list_merges_fixed_database_and_local_hosts():
    hosts = DynamicAllowedHosts(["sunucu"])
    office = OfficeSettings.load()
    office.allowed_hosts = "yeni-ad\n192.168.1.9"
    office.save()  # kayıt önbelleği sıfırlar
    assert "sunucu" in hosts
    assert "yeni-ad" in hosts
    assert "192.168.1.9" in hosts
    assert "localhost" in hosts and "127.0.0.1" in hosts
    assert "baska-ad" not in hosts


@pytest.mark.django_db
def test_wildcard_is_reported_and_kept():
    hosts = DynamicAllowedHosts(["*"])
    assert hosts.allows_everything
    assert not DynamicAllowedHosts(["sunucu"]).allows_everything


def test_list_survives_database_failure(monkeypatch):
    def boom(self, *args, **kwargs):
        raise RuntimeError("veritabanı yok")

    monkeypatch.setattr("django.db.models.query.QuerySet.first", boom)
    hosts = DynamicAllowedHosts(["sunucu"])
    assert list(hosts) == ["sunucu", "localhost", "127.0.0.1", "[::1]"]


@pytest.mark.parametrize(
    "value",
    ["*", "http://buro", "buro:8000", "buro/yol", "999.1.1.1", ".buro", "buro.", "bu_ro"],
)
def test_form_rejects_invalid_entries(value):
    form = AllowedHostsForm({"allowed_hosts": value}, instance=OfficeSettings())
    assert not form.is_valid()
    assert "allowed_hosts" in form.errors


def test_form_normalizes_turkish_name_and_dedupes():
    form = AllowedHostsForm({"allowed_hosts": "BÜRO-PC, büro-pc"}, instance=OfficeSettings())
    assert form.is_valid()
    assert form.cleaned_data["allowed_hosts"] == "xn--bro-pc-3ya"


def test_form_limits_entry_count():
    many = "\n".join(f"pc{i}" for i in range(AllowedHostsForm.MAX_HOSTS + 1))
    form = AllowedHostsForm({"allowed_hosts": many}, instance=OfficeSettings())
    assert not form.is_valid()


@pytest.mark.django_db
def test_admin_saves_hosts_and_new_host_is_accepted(admin_client_logged):
    hosts = DynamicAllowedHosts(["sunucu"])
    with override_settings(ALLOWED_HOSTS=hosts):
        c = admin_client_logged
        assert c.get("/", HTTP_HOST="yeni-ad").status_code == 400
        response = c.post(
            reverse("accounts:settings"),
            {"section": "erisim", "allowed_hosts": "yeni-ad"},
            HTTP_HOST="sunucu",
        )
        assert response.status_code == 302
        assert OfficeSettings.load().allowed_hosts == "yeni-ad"
        assert c.get("/", HTTP_HOST="yeni-ad").status_code != 400


@pytest.mark.django_db
def test_non_admin_cannot_change_hosts(lawyer_client):
    response = lawyer_client.post(
        reverse("accounts:settings"), {"section": "erisim", "allowed_hosts": "kotu-ad"}
    )
    assert response.status_code == 403
    assert OfficeSettings.load().allowed_hosts == ""


@pytest.mark.django_db
def test_settings_page_shows_hosts_section_to_admin(admin_client_logged):
    response = admin_client_logged.get(reverse("accounts:settings") + "?bolum=erisim")
    assert response.status_code == 200
    assert "Erişim adresleri" in response.content.decode()
