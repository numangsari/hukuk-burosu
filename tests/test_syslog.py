import datetime as dt

import pytest
from django.urls import reverse

from apps.core.syslog import count_since, read_recent_entries

SAMPLE = (
    "Serving on http://0.0.0.0:80\n"
    "Traceback (most recent call last):\n"
    "AttributeError: eski kayıt\n"
    "2026-11-09 14:02:11,123 ERROR django.request: Internal Server Error: /x/\n"
    "Traceback (most recent call last):\n"
    '  File "a.py", line 1, in f\n'
    "AttributeError: 'NoneType' object has no attribute 'name'\n"
    "2026-11-09 14:05:00,001 WARNING apps.agenda.services: Google Takvim etkinlikleri okunamadı: HttpError 403\n"
    "2026-11-09 14:06:00,001 INFO x: bilgi kaydı\n"
)


def write_log(tmp_path, text=SAMPLE):
    path = tmp_path / "app.log"
    path.write_text(text, encoding="utf-8")
    return path


def test_entries_are_newest_first_and_group_traceback(tmp_path):
    entries = read_recent_entries(write_log(tmp_path))
    assert [e.level for e in entries] == ["WARNING", "ERROR", ""]
    assert entries[0].title.endswith("HttpError 403")
    error = entries[1]
    assert error.time == dt.datetime(2026, 11, 9, 14, 2, 11)
    assert "line 1" in error.detail
    assert error.summary == "AttributeError: 'NoneType' object has no attribute 'name'"
    assert entries[2].time is None  # saatsiz eski biçimli satırlar tek blokta


def test_info_entries_are_hidden_and_limit_applies(tmp_path):
    path = write_log(tmp_path)
    assert all(e.level != "INFO" for e in read_recent_entries(path))
    assert len(read_recent_entries(path, limit=1)) == 1


def test_missing_log_returns_empty(tmp_path):
    assert read_recent_entries(tmp_path / "yok.log") == []


def test_count_since(tmp_path):
    entries = read_recent_entries(write_log(tmp_path))
    assert count_since(entries, dt.datetime(2026, 11, 9, 14, 0, 0)) == 1
    assert count_since(entries, dt.datetime(2026, 11, 9, 15, 0, 0)) == 0


@pytest.mark.django_db
def test_log_section_admin_only(admin_user, lawyer, settings, tmp_path):
    from django.test import Client

    settings.LOG_FILE = str(write_log(tmp_path))
    url = reverse("accounts:settings") + "?bolum=log"
    admin_http, lawyer_http = Client(), Client()
    admin_http.force_login(admin_user)
    lawyer_http.force_login(lawyer)
    html = admin_http.get(url).content.decode()
    assert "HttpError 403" in html
    assert "HttpError 403" not in lawyer_http.get(url).content.decode()
