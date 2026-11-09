"""Otomatik güncelleme: sağlık adresi, durum dosyası, Hakkında ve bakım sayfası."""

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from django.db import DatabaseError
from django.urls import reverse

from apps.core.updates import update_status
from apps.core.version import app_version

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.django_db
def test_health_is_public_and_reports_version(client):
    r = client.get(reverse("core:health"))
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": app_version()}
    assert "no-cache" in r.headers["Cache-Control"]


@pytest.mark.django_db
def test_health_reports_db_error(client, monkeypatch):
    from apps.core import views

    class BrokenConnection:
        def cursor(self):
            raise DatabaseError("yok")

    monkeypatch.setattr(views, "connection", BrokenConnection())
    r = client.get(reverse("core:health"))
    assert r.status_code == 503 and r.json()["status"] == "db_error"


def _write_status(tmp_path, settings, content):
    path = tmp_path / "status.json"
    path.write_text(content, encoding="utf-8")
    settings.UPDATE_STATUS_FILE = path
    return path


def test_update_status_missing_or_unset(tmp_path, settings):
    settings.UPDATE_STATUS_FILE = None
    assert update_status() is None
    settings.UPDATE_STATUS_FILE = tmp_path / "yok.json"
    assert update_status() is None


@pytest.mark.parametrize("content", ["bozuk{", "[]", '{"result": "bilinmeyen"}'])
def test_update_status_ignores_invalid_content(tmp_path, settings, content):
    _write_status(tmp_path, settings, content)
    assert update_status() is None


def test_update_status_reads_rollback(tmp_path, settings):
    data = {
        "result": "rolled_back",
        "version": "1.3.0",
        "from_version": "1.2.0",
        "at": "2026-11-09T08:01:00+03:00",
    }
    # Güncelleyici PowerShell 5.1'de BOM'lu yazabilir; okuyucu iki biçimi de kabul eder.
    _write_status(tmp_path, settings, "﻿" + json.dumps(data))
    status = update_status()
    assert status["problem"] is True and status["version"] == "1.3.0"
    assert status["at"].year == 2026


@pytest.mark.django_db
def test_about_shows_update_status(client, admin_user, tmp_path, settings):
    _write_status(
        tmp_path,
        settings,
        json.dumps({"result": "rolled_back", "version": "9.9.9", "at": "2026-11-09T08:00:00"}),
    )
    client.force_login(admin_user)
    html = client.get(reverse("accounts:settings"), {"bolum": "hakkinda"}).content.decode()
    assert "önceki sürüme dönüldü" in html and "9.9.9" in html
    assert "guncelleme.log" in html


@pytest.mark.django_db
def test_about_without_status(client, admin_user, settings):
    settings.UPDATE_STATUS_FILE = None
    client.force_login(admin_user)
    html = client.get(reverse("accounts:settings"), {"bolum": "hakkinda"}).content.decode()
    assert "Henüz otomatik güncelleme yapılmadı" in html


def test_maintenance_page_answers_every_path_with_503():
    from http.server import ThreadingHTTPServer

    spec = importlib.util.spec_from_file_location(
        "maintenance", ROOT / "installer/scripts/maintenance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.MaintenanceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path in ("/", "/gorevler/?x=1"):
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=5)
            assert err.value.code == 503
            assert err.value.headers["Retry-After"] == "15"
            assert "Program güncelleniyor" in err.value.read().decode()
    finally:
        server.shutdown()
        server.server_close()
