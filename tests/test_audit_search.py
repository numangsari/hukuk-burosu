"""Genel aramanın kayıt görünürlüğü ve boş sorgu regresyonları."""

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.cases.models import CaseParty, Document
from apps.clients.models import Party
from apps.office.models import OfficeSettings, TaskType
from apps.search.views import search_querysets
from apps.tasks.models import Task
from tests.conftest import make_user

pytestmark = pytest.mark.django_db


def test_search_hides_private_records_and_shared_party_links(
    client, case_factory, lawyer, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    office = OfficeSettings.load()
    office.case_visibility_mode = "restricted"
    office.save()
    stranger = make_user("arama-yabanci", User.Role.LAWYER)
    hidden = case_factory()
    visible = case_factory(responsible_lawyer=stranger)
    task = Task.objects.create(
        title="Denetim görev",
        case=hidden,
        client=hidden.client,
        assignee=lawyer,
        task_type=TaskType.objects.first(),
        due_date=timezone.localdate(),
        created_by=lawyer,
    )
    document = Document.objects.create(
        case=hidden, title="Denetim belge", file=ContentFile(b"%PDF-test", name="test.pdf")
    )
    private_party = Party.objects.create(kind="person", name="Denetim gizli taraf")
    shared_party = Party.objects.create(kind="person", name="Denetim ortak taraf")
    CaseParty.objects.create(case=hidden, party=private_party)
    CaseParty.objects.create(case=hidden, party=shared_party)
    CaseParty.objects.create(case=visible, party=shared_party)
    result = search_querysets("denetim", user=stranger)
    assert not result["tasks"].exists()
    assert not result["documents"].exists()
    assert list(result["parties"].values_list("pk", flat=True)) == [shared_party.pk]
    assert [link.case_id for link in result["parties"].first().case_links.all()] == [visible.pk]
    owner = search_querysets("denetim", user=lawyer)
    assert owner["tasks"].filter(pk=task.pk).exists()
    assert owner["documents"].filter(pk=document.pk).exists()
    client.force_login(stranger)
    for params, headers in [
        ({"q": "denetim"}, {}),
        ({"q": "denetim", "canli": "1"}, {"HTTP_HX_REQUEST": "true"}),
    ]:
        response = client.get(reverse("search:search"), params, **headers)
        assert response.status_code == 200
        assert document.title not in response.content.decode()
        assert private_party.name not in response.content.decode()
    office.case_visibility_mode = "public"
    office.save()
    assert search_querysets("denetim", user=stranger)["documents"].filter(pk=document.pk).exists()


@pytest.mark.parametrize("query", ["", "x", "  "])
@pytest.mark.parametrize("kind", ["muvekkil", "dosya", "gorev", "karsi", "belge"])
def test_short_query_with_kind_returns_empty_page(lawyer_client, query, kind):
    response = lawyer_client.get(reverse("search:search"), {"q": query, "tur": kind})
    assert response.status_code == 200
    assert response.context["total"] == 0
