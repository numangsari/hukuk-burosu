import pytest
from django.core.paginator import Paginator
from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import RequestFactory

from apps.core.pagination import page_size


def test_page_size_is_validated_and_saved_per_page():
    factory = RequestFactory()
    request = factory.get("/bir/", {"sayfa_boyutu": 50})
    request.session = {}
    assert page_size(request) == 50
    session = request.session
    other = factory.get("/iki/")
    other.session = session
    assert page_size(other) == 25
    first = factory.get("/bir/", {"sayfa_boyutu": "999999"})
    first.session = session
    assert page_size(first) == 50
    assert page_size(other) == 25


@pytest.mark.django_db
def test_pagination_is_compact_and_preserves_filters():
    request = RequestFactory().get("/dosyalar/?q=ornek&sort=ad&sayfa_boyutu=25&page=60")
    request.session = {}
    page = Paginator(range(2500), 25).page(60)
    html = render_to_string("partials/pagination.html", {"page_obj": page}, request=request)
    assert html.count('class="page-item') <= 9
    assert "…" in html
    assert 'aria-current="page">60' in html
    assert "q=ornek" in html and "sort=ad" in html
    assert 'value="25" selected' in html
    assert 'aria-label="Sayfada gösterilecek kayıt sayısı"' in html


def test_page_size_ignores_non_numeric_values():
    request = RequestFactory().get("/liste/")
    request.GET = QueryDict("sayfa_boyutu=abc")
    request.session = {}
    assert page_size(request) == 25


@pytest.mark.django_db
def test_client_list_uses_selected_count_and_keeps_it(lawyer_client, client_factory):
    from django.urls import reverse

    for number in range(12):
        client_factory(first_name=f"Örnek{number}", last_name="Deneme")
    url = reverse("clients:list")
    response = lawyer_client.get(url, {"sayfa_boyutu": "10", "page": "2"})
    assert response.context["paginator"].per_page == 10
    assert len(response.context["page_obj"]) == 2
    response = lawyer_client.get(url, {"q": "Deneme"})
    assert response.context["paginator"].per_page == 10
    assert len(response.context["page_obj"]) == 10


@pytest.mark.django_db
def test_notice_list_paginates(lawyer_client):
    from django.urls import reverse

    from apps.imports.models import PortalNotice

    PortalNotice.objects.bulk_create(
        [PortalNotice(fingerprint=f"ornek-{number}", subject="Örnek") for number in range(12)]
    )
    response = lawyer_client.get(reverse("notice_list"), {"sayfa_boyutu": 10, "page": 2})
    assert response.context["page_obj"].paginator.count == 12
    assert len(response.context["notices"]) == 2
