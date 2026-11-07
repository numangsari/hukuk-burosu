from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.cases.models import ArchiveFolder, Case, CaseParty, Document, Hearing, HearingStatus
from apps.clients.models import Party
from apps.core.text import tr_title

pytestmark = pytest.mark.django_db


def test_suggest_archive_no(case_factory):
    assert Case.suggest_archive_no() == "1"
    case_factory(archive_no="2026/0041")
    assert Case.suggest_archive_no() == "2026/0042"
    case_factory(archive_no="2026/0042-A")
    # Son kayıt "0042-A"; sıradaki "0043-A" önerilir.
    assert Case.suggest_archive_no() == "2026/0043-A"


def _case_data(client_obj, **kw):
    data = {
        "client": client_obj.pk,
        "case_type": "civil",
        "archive_folder_no": "1",
        "archive_no": "100",
        "authority": "Örnek Kurum",
        "official_year": 2026,
        "official_sequence": 1,
        "client_role": "plaintiff",
        "parties-TOTAL_FORMS": "0",
        "coclients-TOTAL_FORMS": "0",
        "coclients-INITIAL_FORMS": "0",
        "parties-INITIAL_FORMS": "0",
        "subject": "Tazminat",
        "opened_on": timezone.localdate().isoformat(),
        "status": "pending",
        "stage": "first",
        "responsible_lawyer": client_obj.responsible_lawyer_id,
        "responsible_intern": client_obj.responsible_intern_id,
    }
    data.update(kw)
    if "official_no" in kw and not kw["official_no"]:
        data.update(official_year="", official_sequence="")
    default_roles = {
        "consultancy": "party_one",
        "other": "applicant",
        "enforcement": "creditor",
        "criminal": "accused",
        "investigation": "suspect",
        "mediation": "applicant",
        "notice": "notifier",
    }
    if "client_role" not in kw:
        data["client_role"] = default_roles.get(data["case_type"], "plaintiff")
    folder = data.get("archive_folder_no", "").strip()
    if folder and not ArchiveFolder.objects.filter(name__iexact=folder).exists():
        ArchiveFolder.objects.create(name=folder, kind=ArchiveFolder.Kind.LEGACY, capacity=200)
    return data


def test_create_case_and_archive_no_unique(lawyer_client, client_factory):
    c = client_factory()
    r = lawyer_client.post(reverse("cases:create"), _case_data(c))
    assert r.status_code == 302
    r = lawyer_client.post(reverse("cases:create"), _case_data(c, archive_no=" 100 "))
    assert r.status_code == 200
    assert "archive_no" in r.context["form"].errors


def test_create_case_in_window_preserves_errors_and_refreshes_parent(lawyer_client, client_factory):
    client = client_factory()
    url = reverse("cases:create") + "?pencere=1"
    invalid = lawyer_client.post(url, _case_data(client, archive_no=""))
    assert invalid.status_code == 200 and "archive_no" in invalid.context["form"].errors
    response = lawyer_client.post(url, _case_data(client))
    assert response.status_code == 200
    assert "window.parent.location.reload()" in response.content.decode()
    assert Case.objects.filter(client=client).exists()


def test_type_specific_fields_cleared(lawyer_client, client_factory):
    c = client_factory()
    lawyer_client.post(
        reverse("cases:create"),
        _case_data(c, case_type="enforcement", enforcement_type="negotiable", crime="x"),
    )
    case = Case.objects.get()
    assert (
        case.status == "open" and case.stage == "started"
    )  # Yeni dosya açık ve ilk aşamada başlar.
    assert case.crime == ""
    assert case.enforcement_type == "negotiable"
    assert case.labels["official_no"] == "Dosya Numarası"


def test_enforcement_details_saved_and_shown(lawyer_client, client_factory):
    client = client_factory()
    response = lawyer_client.post(
        reverse("cases:create"),
        _case_data(
            client,
            case_type="enforcement",
            enforcement_type="negotiable",
            enforcement_basis="Örnek senet",
            enforcement_amount="1250.50",
        ),
    )
    assert response.status_code == 302
    case = Case.objects.get()
    response = lawyer_client.get(case.get_absolute_url())
    assert "Örnek senet" in response.content.decode()
    assert "1.250,50" in response.content.decode()
    assert "Maaş Haczi" in response.content.decode()
    response = lawyer_client.get(reverse("cases:seizure_add", args=[case.pk]), {"kind": "bank"})
    assert response.context["form"]["kind"].value() == "bank"


def test_create_prefills_from_client(lawyer_client, client_factory):
    c = client_factory()
    r = lawyer_client.get(reverse("cases:create"), {"client": c.pk})
    init = r.context["form"].initial
    assert init["responsible_lawyer"] == c.responsible_lawyer_id
    assert init["responsible_intern"] == c.responsible_intern_id


def test_case_list_default_hides_closed(lawyer_client, case_factory):
    case_factory(subject="Açık")
    case_factory(subject="Kapalı", status="closed")
    r = lawyer_client.get(reverse("cases:list"))
    assert [k.subject for k in r.context["cases"]] == ["AÇIK"]
    r = lawyer_client.get(reverse("cases:list"), {"status": "all"})
    assert len(r.context["cases"]) == 2


def test_case_list_shows_earliest_upcoming_planned_hearing(lawyer_client, case_factory):
    now = timezone.now()
    k = case_factory(subject="Duruşmalı")
    far = Hearing.objects.create(case=k, starts_at=now + timedelta(days=20))
    near = Hearing.objects.create(case=k, starts_at=now + timedelta(days=5))
    Hearing.objects.create(case=k, starts_at=now - timedelta(days=3))
    Hearing.objects.create(
        case=k, starts_at=now + timedelta(days=1), status=HearingStatus.CANCELLED
    )
    case_factory(subject="Duruşmasız")
    r = lawyer_client.get(reverse("cases:list"), {"sort": "next_hearing"})
    by_subject = {c.subject: c for c in r.context["cases"]}
    assert by_subject["DURUŞMALI"].next_hearing == near.starts_at
    assert by_subject["DURUŞMASIZ"].next_hearing is None
    assert far.starts_at > near.starts_at


def test_party_add_reuses_identity_and_warns_on_client(lawyer_client, case_factory):
    case = case_factory()
    url = reverse("cases:party_add", args=[case.pk])
    lawyer_client.post(
        url, {"role": "defendant", "kind": "company", "name": "X A.Ş.", "identity_no": "1234567890"}
    )
    other = case_factory(case_type="enforcement")
    lawyer_client.post(
        reverse("cases:party_add", args=[other.pk]),
        {"role": "debtor", "kind": "company", "name": "X Anonim", "identity_no": "1234567890"},
    )
    assert Party.objects.count() == 1
    assert CaseParty.objects.count() == 2


def test_document_upload_and_delete_rights(
    lawyer_client, client, intern, case_factory, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    case = case_factory()
    f = SimpleUploadedFile("dilekçe örnek.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    lawyer_client.post(
        reverse("cases:document_upload", args=[case.pk]),
        {"title": "Dava dilekçesi", "category": "petition", "file": f},
    )
    doc = Document.objects.get()
    assert doc.original_name == "dilekçe örnek.pdf"
    assert doc.file.name.startswith(f"cases/{case.pk}/")

    client.force_login(intern)
    client.post(reverse("cases:document_delete", args=[case.pk, doc.pk]))
    assert Document.objects.exists()  # stajyer başkasının belgesini silemez


def test_detail_pages_render(lawyer_client, case_factory):
    case = case_factory()
    assert lawyer_client.get(case.get_absolute_url()).status_code == 200
    assert lawyer_client.get(case.client.get_absolute_url()).status_code == 200
    assert lawyer_client.get(reverse("core:home")).status_code == 200


def test_case_form_type_labels_are_json_object(lawyer_client):
    r = lawyer_client.get(reverse("cases:create"))
    # json_script ile tek seferde kodlanmış nesne olmalı (çift kodlanmış string değil)
    assert '<script id="type-labels" type="application/json">{"civil"' in r.content.decode()


@pytest.mark.parametrize(
    "case_type",
    ["civil", "criminal", "administrative", "enforcement", "investigation", "mediation", "notice"],
)
def test_institution_and_number_required(client_factory, case_type):
    from apps.cases.forms import CaseForm

    data = _case_data(
        client_factory(), case_type=case_type, authority="", official_no="", subject=""
    )
    form = CaseForm(data)
    assert not form.is_valid()
    required = {"authority", "official_sequence"}
    # İhtarnamede yıl yok; tarih ve yevmiye numarası girilir.
    required.add("official_date" if case_type == "notice" else "official_year")
    assert required <= form.errors.keys()
    assert ("official_year" in form.errors) == (case_type != "notice")
    assert "subject" in form.errors


def test_notice_uses_date_and_yevmiye_number(lawyer_client, client_factory):
    data = _case_data(
        client_factory(), case_type="notice", official_no="", subject="ihtar", official_year=""
    )
    data.update(
        authority="SAKARYA 3. NOTERLİĞİ", official_sequence="4545", official_date="2026-12-12"
    )
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    case = Case.objects.get()
    assert case.official_no == "4545"
    assert case.official_date.isoformat() == "2026-12-12"
    assert case.official_no_display == "12.12.2026 / 4545 Yevmiye"


def test_notice_service_info_is_saved_and_cleared_for_other_types(lawyer_client, client_factory):
    data = _case_data(
        client_factory(), case_type="notice", official_no="", subject="ihtar", official_year=""
    )
    data.update(
        authority="SAKARYA 3. NOTERLİĞİ",
        official_sequence="4545",
        official_date="2026-12-12",
        notice_service_no="4200558110633",
        notice_served="on",
        notice_served_on="2026-12-20",
    )
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    case = Case.objects.get()
    assert case.notice_service_no == "4200558110633" and case.notice_served
    assert case.notice_served_on.isoformat() == "2026-12-20"
    page = lawyer_client.get(case.get_absolute_url())
    assert "Tebliğ edildi" in page.content.decode()


def test_commission_number_kind_shows_talimat(lawyer_client, client_factory):
    data = _case_data(client_factory(), case_type="criminal", subject="talimat")
    data.update(official_year="2018", official_sequence="113", official_no_kind="talimat")
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    assert Case.objects.get().official_no_display == "2018/113 Talimat"


def test_misc_number_kind_is_selectable_for_esas_types(lawyer_client, client_factory):
    data = _case_data(client_factory(), case_type="criminal", subject="değişik iş")
    data.update(official_year="2018", official_sequence="7977", official_no_kind="d_is")
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    case = Case.objects.get()
    assert case.official_no == "2018/7977" and case.official_no_kind == "d_is"
    assert case.official_no_display == "2018/7977 D.İş"
    case.official_no_kind = "esas"
    assert case.official_no_display == "2018/7977 Esas"


@pytest.mark.parametrize("case_type", ["consultancy", "other"])
def test_named_cases_need_only_title(lawyer_client, client_factory, case_type):
    data = _case_data(
        client_factory(), case_type=case_type, authority="", official_no="", subject="örnek isim"
    )
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    case = Case.objects.get()
    assert case.subject == "ÖRNEK İSİM"
    assert case.authority == case.official_no == ""
    data["subject"] = ""
    data["archive_no"] = "101"
    response = lawyer_client.post(reverse("cases:create"), data)
    assert "subject" in response.context["form"].errors


def test_archive_location_unique_per_folder(lawyer_client, client_factory):
    owner = client_factory()
    for folder in ("A", "B"):
        assert (
            lawyer_client.post(
                reverse("cases:create"), _case_data(owner, archive_folder_no=folder)
            ).status_code
            == 302
        )
    response = lawyer_client.post(reverse("cases:create"), _case_data(owner, archive_folder_no="a"))
    assert "archive_no" in response.context["form"].errors
    assert Case.objects.get(archive_folder_no="A").archive_reference == "A / 100"


def test_client_required_and_responsibles_default(lawyer_client, client_factory, admin_user):
    owner = client_factory()
    data = _case_data(owner, responsible_lawyer="", responsible_intern="")
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    case = Case.objects.get()
    assert case.responsible_lawyer == owner.responsible_lawyer
    assert case.responsible_intern == owner.responsible_intern
    assert case.subject == "TAZMİNAT"
    assert case.display_name == "ÖRNEK KURUM - 2026/1 Esas"
    data.update(archive_no="101", responsible_lawyer=admin_user.pk)
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    assert Case.objects.get(archive_no="101").responsible_lawyer == admin_user
    data.update(client="", archive_no="102")
    response = lawyer_client.post(reverse("cases:create"), data)
    assert "client" in response.context["form"].errors


def test_existing_archive_number_preserved_when_edited(lawyer_client, case_factory):
    case = case_factory(archive_no="2026/0099", subject="Eski konu")
    data = _case_data(case.client, archive_folder_no="", archive_no=case.archive_no)
    assert lawyer_client.post(reverse("cases:update", args=[case.pk]), data).status_code == 302
    case.refresh_from_db()
    assert case.archive_reference == "2026/0099"
    assert case.subject == "TAZMİNAT"


@pytest.mark.parametrize("case_type", ["civil", "consultancy", "other"])
def test_case_display_name_and_subject_are_independent(case_factory, case_type):
    case = case_factory(
        case_type=case_type, authority="Örnek Kurum", official_no="2026/42", subject="Örnek konu"
    )
    expected = (
        "ÖRNEK KONU" if case_type in ("consultancy", "other") else "ÖRNEK KURUM - 2026/42 Esas"
    )
    assert case.display_name == expected
    assert str(case) == expected


def test_case_form_date_and_removed_fields(lawyer_client, client_factory, case_factory):
    from apps.cases.forms import CaseForm

    form = CaseForm()
    assert form["opened_on"].value() == timezone.localdate()
    assert not {"value", "status", "stage", "closed_on"} & form.fields.keys()
    case = case_factory(
        archive_no="1",
        value=100,
        status="closed",
        stage="appeal",
        closing_reason="waiver",
        closed_on=timezone.localdate(),
    )
    data = _case_data(case.client, archive_no=case.archive_no)
    assert lawyer_client.post(reverse("cases:update", args=[case.pk]), data).status_code == 302
    case.refresh_from_db()
    assert case.status == "closed"
    assert case.stage == "appeal"
    assert case.value == 100
    assert case.closed_on == timezone.localdate()


@pytest.mark.parametrize("case_type", ["civil", "consultancy", "other"])
def test_case_names_in_lists_and_selectors(lawyer_client, case_factory, case_type):
    case = case_factory(
        case_type=case_type, authority="Örnek Kurum", official_no="2026/42", subject="Örnek konu"
    )
    response = lawyer_client.get(reverse("cases:list"))
    # Listede mahkeme adı ile numara ayrı satırlarda, normal yazımla gösterilir.
    if case_type in {"consultancy", "other"}:
        assert tr_title(case.display_name) in response.content.decode()
    else:
        assert tr_title(case.authority) in response.content.decode()
        assert case.official_no_display in response.content.decode()
    response = lawyer_client.get(case.get_absolute_url())
    assert case.display_name in response.content.decode()
    assert tr_title("ÖRNEK KONU") in response.content.decode()  # ekranda normal yazım


@pytest.mark.parametrize(
    "case_type",
    [
        "civil",
        "criminal",
        "administrative",
        "enforcement",
        "investigation",
        "consultancy",
        "mediation",
        "notice",
        "other",
    ],
)
def test_party_choices_follow_case_type(lawyer_client, case_factory, case_type):
    from apps.cases.party_roles import PARTY_ROLES

    case = case_factory(case_type=case_type)
    response = lawyer_client.get(case.get_absolute_url())
    assert list(response.context["party_form"].fields["role"].choices)[1:] == PARTY_ROLES[case_type]
    role = PARTY_ROLES[case_type][0][0]
    response = lawyer_client.post(
        reverse("cases:party_add", args=[case.pk]),
        {"role": role, "kind": "person", "name": "Örnek Taraf"},
    )
    assert case.party_links.get().role == role
    lawyer_client.post(
        reverse("cases:party_add", args=[case.pk]),
        {"role": "invalid", "kind": "person", "name": "Yanlış Sıfat"},
    )
    assert case.party_links.count() == 1


def test_case_number_defaults_and_numeric_validation(lawyer_client, client_factory):
    from apps.cases.forms import CaseForm

    form = CaseForm()
    assert form["official_year"].value() == timezone.localdate().year
    owner = client_factory()
    data = _case_data(owner, official_sequence="abc")
    response = lawyer_client.post(reverse("cases:create"), data)
    assert "official_sequence" in response.context["form"].errors
    assert not Case.objects.exists()
    data.update(official_sequence="0042", authority="izmir ıslah kurumu")
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    case = Case.objects.get()
    assert case.official_no == "2026/42"
    assert case.authority == "İZMİR ISLAH KURUMU"


def test_parties_saved_with_case_and_errors_preserve_rows(lawyer_client, client_factory):
    owner = client_factory()
    data = _case_data(
        owner,
        **{
            "parties-TOTAL_FORMS": "1",
            "parties-0-role": "defendant",
            "parties-0-kind": "person",
            "parties-0-name": "Örnek Taraf",
        },
    )
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    case = Case.objects.get()
    assert case.client_role == "plaintiff"
    link = case.party_links.get()
    assert link.party.name == "Örnek Taraf"
    assert link.role == "defendant"
    data.update(archive_no="101", **{"parties-0-role": "creditor"})
    response = lawyer_client.post(reverse("cases:create"), data)
    assert response.status_code == 200
    assert response.context["party_formset"].forms[0]["name"].value() == "Örnek Taraf"
    assert Case.objects.count() == 1
    assert Party.objects.count() == 1


def test_existing_party_role_edit_and_new_party_reuse(lawyer_client, client_factory):
    owner = client_factory()
    data = _case_data(
        owner,
        **{
            "parties-TOTAL_FORMS": "1",
            "parties-0-role": "defendant",
            "parties-0-kind": "company",
            "parties-0-name": "Örnek AŞ",
            "parties-0-identity_no": "1234567890",
        },
    )
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    first = Case.objects.get()
    link = first.party_links.get()
    update = _case_data(owner, **{f"party_role_{link.pk}": "counter_defendant"})
    assert lawyer_client.post(reverse("cases:update", args=[first.pk]), update).status_code == 302
    link.refresh_from_db()
    assert link.role == "counter_defendant"
    data["archive_no"] = "101"
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    assert Case.objects.count() == 2
    assert Party.objects.count() == 1


def _case_with_party(owner, case_factory):
    case = case_factory(owner)
    party = Party.objects.create(kind="person", name="SİLİNECEK TARAF")
    return case, case.party_links.create(party=party, role="defendant")


def test_admin_can_remove_party_from_case_form(admin_client_logged, client_factory, case_factory):
    owner = client_factory()
    case, link = _case_with_party(owner, case_factory)
    data = _case_data(owner, archive_folder_no=case.archive_folder_no, archive_no=case.archive_no)
    data[f"party_role_{link.pk}"] = "defendant"
    data[f"party_remove_{link.pk}"] = "on"
    response = admin_client_logged.post(reverse("cases:update", args=[case.pk]), data)
    assert response.status_code == 302
    assert not case.party_links.exists()
    assert Party.objects.filter(pk=link.party_id).exists()


def test_non_admin_cannot_remove_party_from_case_form(lawyer_client, client_factory, case_factory):
    owner = client_factory()
    case, link = _case_with_party(owner, case_factory)
    data = _case_data(owner, archive_folder_no=case.archive_folder_no, archive_no=case.archive_no)
    data[f"party_role_{link.pk}"] = "defendant"
    data[f"party_remove_{link.pk}"] = "on"
    lawyer_client.post(reverse("cases:update", args=[case.pk]), data)
    assert case.party_links.filter(pk=link.pk).exists()


def test_client_role_rejects_other_case_type(lawyer_client, client_factory):
    response = lawyer_client.post(
        reverse("cases:create"), _case_data(client_factory(), client_role="accused")
    )
    assert "client_role" in response.context["form"].errors
    assert not Case.objects.exists()


def test_party_role_validation_on_administrative_case_with_disabled_case_type(
    lawyer_client, client_factory, case_factory
):
    from apps.imports.models import PortalCase

    owner = client_factory()
    case = case_factory(owner, case_type="administrative", client_role="defendant_authority")
    PortalCase.objects.create(
        case=case, fingerprint="fp-admin-1", authority="İSTANBUL 14. İDARE", number="2025/1"
    )
    party = Party.objects.create(kind="person", name="NERİMAN DURSUN")
    link = case.party_links.create(party=party, role="plaintiff")

    # UYAP bağlantılı dosyalarda case_type alanı HTML'de disabled olduğu için
    # tarayıcı bu alanı POST verisinde göndermez:
    data = _case_data(
        owner,
        archive_folder_no=case.archive_folder_no,
        archive_no=case.archive_no,
        client_role="defendant_authority",
    )
    data.pop("case_type", None)
    data[f"party_role_{link.pk}"] = "plaintiff"

    response = lawyer_client.post(reverse("cases:update", args=[case.pk]), data)
    assert response.status_code == 302
    link.refresh_from_db()
    assert link.role == "plaintiff"
