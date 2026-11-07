import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.clients.models import Client

pytestmark = pytest.mark.django_db


def activity_page(client):
    params = {"islem": "0", "tur": ContentType.objects.get_for_model(Client).pk}
    with CaptureQueriesContext(connection) as captured:
        response = client.get(reverse("activity:list"), params)
    assert response.status_code == 200
    return len(captured), response


def test_activity_list_query_count_does_not_grow_with_entries(admin_client_logged, client_factory):
    for _ in range(3):
        client_factory()
    activity_page(admin_client_logged)  # ContentType önbelleğini ısıtır; sayım gürültüsünü önler.
    few, first = activity_page(admin_client_logged)
    for _ in range(12):
        client_factory()
    many, second = activity_page(admin_client_logged)
    assert len(second.context["entries"]) - len(first.context["entries"]) == 12
    assert many == few


def test_activity_list_links_existing_records_and_skips_deleted(
    admin_client_logged, client_factory
):
    kept = client_factory(first_name="Kalan")
    gone = client_factory(first_name="Silinen")
    gone_pk = gone.pk
    gone.delete()
    _, response = activity_page(admin_client_logged)
    links = {e.object_pk: e.link for e in response.context["entries"]}
    assert links[str(kept.pk)] == kept.get_absolute_url()
    assert links[str(gone_pk)] == ""
