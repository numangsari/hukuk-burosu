import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.office import models as office_models
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db


def office_queries(captured):
    return [q for q in captured if "office_officesettings" in q["sql"]]


def test_load_outside_request_always_reads_database():
    OfficeSettings.load()
    OfficeSettings.objects.filter(pk=1).update(name="Yeni ad")
    assert OfficeSettings.load().name == "Yeni ad"


def test_load_inside_cache_scope_queries_once_and_returns_independent_copies():
    OfficeSettings.load()
    token = office_models.request_cache.set({})
    try:
        with CaptureQueriesContext(connection) as captured:
            first = OfficeSettings.load()
            second = OfficeSettings.load()
        assert len(office_queries(captured.captured_queries)) == 1
        first.name = "Kaydedilmemiş değişiklik"
        assert OfficeSettings.load().name != "Kaydedilmemiş değişiklik"
        assert second is not first
    finally:
        office_models.request_cache.reset(token)


def test_save_invalidates_cache_inside_scope():
    token = office_models.request_cache.set({})
    try:
        settings_obj = OfficeSettings.load()
        settings_obj.name = "Kaydedilen ad"
        settings_obj.save()
        assert OfficeSettings.load().name == "Kaydedilen ad"
    finally:
        office_models.request_cache.reset(token)


def test_request_reads_office_settings_at_most_once(lawyer_client):
    with CaptureQueriesContext(connection) as captured:
        response = lawyer_client.get(reverse("cases:list"))
    assert response.status_code == 200
    assert len(office_queries(captured.captured_queries)) <= 1


def test_cache_does_not_leak_between_requests(lawyer_client):
    lawyer_client.get(reverse("cases:list"))
    OfficeSettings.objects.filter(pk=1).update(name="İkinci istek adı")
    response = lawyer_client.get(reverse("cases:list"))
    assert response.context["office"].name == "İkinci istek adı"
