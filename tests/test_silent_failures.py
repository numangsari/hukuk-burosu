"""Sayfayı bozmaması gereken yardımcıların hatayı yutmadan günlüğe yazdığını sınar."""

import logging
import zipfile
from io import BytesIO

import pytest

from apps.core import module_stats, office_lists


def _boom():
    raise RuntimeError("deneme hatası")


def test_module_stats_returns_empty_and_logs_on_error(monkeypatch, caplog):
    monkeypatch.setitem(module_stats.BUILDERS, "deneme", _boom)
    with caplog.at_level(logging.ERROR, logger="apps.core.module_stats"):
        assert module_stats.module_stats("deneme") == []
    assert "deneme" in caplog.text


def test_module_stats_unknown_key_is_silent(caplog):
    assert module_stats.module_stats("olmayan-anahtar") == []
    assert caplog.text == ""


@pytest.mark.django_db
def test_lists_zip_skips_failed_list_and_logs_without_content(monkeypatch, caplog):
    monkeypatch.setattr(office_lists, "_calendar_report", _boom)
    with caplog.at_level(logging.WARNING, logger="apps.core.office_lists"):
        data = office_lists.export_all_lists_zip()
    names = zipfile.ZipFile(BytesIO(data)).namelist()
    assert "Takvim.xlsx" not in names
    assert names  # diğer listeler yine üretilir
    assert "Takvim" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "deneme hatası" not in caplog.text
