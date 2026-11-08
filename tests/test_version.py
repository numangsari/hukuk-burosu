"""Uygulama sürümü: paket içindeki VERSION dosyası, yoksa pyproject.toml."""

import tomllib

import pytest
from django.urls import reverse

from apps.core import version


@pytest.fixture(autouse=True)
def clear_cache():
    version.app_version.cache_clear()
    yield
    version.app_version.cache_clear()


def test_version_comes_from_pyproject_when_no_version_file(settings):
    with (settings.BASE_DIR / "pyproject.toml").open("rb") as f:
        expected = tomllib.load(f)["project"]["version"]
    if (settings.BASE_DIR / "VERSION").exists():
        pytest.skip("Geliştirme klasöründe VERSION dosyası var.")
    assert version.app_version() == expected


def test_version_file_wins(settings, tmp_path):
    (tmp_path / "VERSION").write_text("﻿9.9.9\n", encoding="utf-8")
    settings.BASE_DIR = tmp_path
    assert version.app_version() == "9.9.9"


def test_missing_sources_return_placeholder(settings, tmp_path):
    settings.BASE_DIR = tmp_path
    assert version.app_version() == "?"


@pytest.mark.django_db
def test_monitor_shows_product_and_version(admin_user, client):
    client.force_login(admin_user)
    html = client.get(reverse("accounts:settings") + "?bolum=monitor").content.decode()
    assert version.PRODUCT_NAME in html
    assert version.app_version() in html
