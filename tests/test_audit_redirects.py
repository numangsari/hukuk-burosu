"""Muhasebe dönüş adreslerinde tarayıcı ters eğik çizgi normalizasyonu."""

from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from apps.accounting.views import EntryCreateView


@pytest.mark.parametrize(
    "target,expected",
    [
        ("/dosyalar/1/", "/dosyalar/1/"),
        ("//example.invalid/", "/muvekkiller/1/#muhasebe"),
        ("/\\example.invalid/", "/muvekkiller/1/#muhasebe"),
        ("https://example.invalid/", "/muvekkiller/1/#muhasebe"),
    ],
)
def test_entry_return_url_stays_local(target, expected):
    view = EntryCreateView()
    view.request = RequestFactory().post("/muhasebe/yeni/", {"next": target})
    view.object = SimpleNamespace(
        client=SimpleNamespace(get_absolute_url=lambda: "/muvekkiller/1/")
    )
    assert view.get_success_url() == expected
