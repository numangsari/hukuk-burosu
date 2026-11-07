import datetime as dt
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import OfficeEntry

from .conftest import make_user

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\nmakbuz"


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def entry(user, kind="expense", amount="100.00", date=None, **kw):
    return OfficeEntry.objects.create(
        kind=kind,
        amount=Decimal(amount),
        date=date or timezone.localdate(),
        description=kw.pop("description", "Kırtasiye"),
        created_by=user,
        **kw,
    )


@pytest.fixture
def accountant(db):
    return make_user("muhasebeci", "accountant")


# ---- yetki -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", ["lawyer", "senior", "intern", "paralegal", "secretary", "accountant"]
)
def test_only_admin_can_use_office_ledger(role, admin_user):
    user = make_user(f"k-{role}", role)
    e = entry(admin_user)
    c = login(user)
    assert c.get(reverse("accounting:office_list")).status_code == 403
    assert c.get(reverse("accounting:office_create")).status_code == 403
    assert (
        c.post(reverse("accounting:office_cancel", args=[e.pk]), {"reason": "x"}).status_code == 403
    )
    assert c.get(reverse("accounting:list")).status_code == 200
    assert (
        f'href="{reverse("accounting:office_list")}"'
        not in c.get(reverse("accounting:list")).content.decode()
    )


def test_admin_sees_link_on_accounting_page(admin_user):
    html = login(admin_user).get(reverse("accounting:list")).content.decode()
    assert f'href="{reverse("accounting:office_list")}"' in html


# ---- kayıt -----------------------------------------------------------------------------


def post_data(**kw):
    data = {
        "kind": "expense",
        "amount": "250.50",
        "date": timezone.localdate().isoformat(),
        "description": "Elektrik faturası",
        "receipt_no": "M-15",
    }
    data.update(kw)
    return data


def test_admin_records_expense_with_receipt(admin_user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    r = login(admin_user).post(
        reverse("accounting:office_create"),
        {**post_data(), "receipt": SimpleUploadedFile("fatura.pdf", PDF)},
    )
    assert r.status_code == 302
    e = OfficeEntry.objects.get()
    assert e.amount == Decimal("250.50") and e.receipt_no == "M-15" and e.created_by == admin_user
    assert e.receipt.name.startswith("office-ledger/")


def test_receipt_no_is_kept_only_for_expenses(admin_user):
    login(admin_user).post(reverse("accounting:office_create"), post_data(kind="income"))
    assert OfficeEntry.objects.get().receipt_no == ""


def test_validation(admin_user):
    c = login(admin_user)
    zero = c.post(reverse("accounting:office_create"), post_data(amount="0"))
    blank = c.post(reverse("accounting:office_create"), post_data(description=""))
    kind = c.post(reverse("accounting:office_create"), post_data(kind="fee"))
    assert "amount" in zero.context["form"].errors
    assert "description" in blank.context["form"].errors
    assert "kind" in kind.context["form"].errors
    assert not OfficeEntry.objects.exists()


def test_create_in_modal_reloads_parent(admin_user):
    r = login(admin_user).post(reverse("accounting:office_create") + "?pencere=1", post_data())
    assert r.status_code == 200 and "window.parent.location.reload()" in r.content.decode()
    assert r["X-Frame-Options"] == "SAMEORIGIN"


# ---- toplam ve süzme ------------------------------------------------------------------------


def test_totals_default_to_current_month_and_skip_cancelled(admin_user):
    today = timezone.localdate()
    entry(admin_user, "income", "1000.00")
    entry(admin_user, "expense", "400.00")
    cancelled = entry(admin_user, "expense", "50.00")
    cancelled.is_cancelled = True
    cancelled.save()
    old = today.replace(day=1) - dt.timedelta(days=5)
    entry(admin_user, "income", "9999.00", date=old)
    ctx = login(admin_user).get(reverse("accounting:office_list")).context
    assert ctx["income"] == Decimal("1000.00") and ctx["expense"] == Decimal("400.00")
    assert ctx["net"] == Decimal("600.00")
    assert len(ctx["entries"]) == 3  # iptal edilen de listelenir


def test_date_range_and_kind_filter(admin_user):
    today = timezone.localdate()
    old = today - dt.timedelta(days=60)
    entry(admin_user, "income", "700.00", date=old)
    entry(admin_user, "expense", "20.00")
    c = login(admin_user)
    ctx = c.get(
        reverse("accounting:office_list"),
        {"baslangic": (old - dt.timedelta(days=1)).isoformat(), "bitis": today.isoformat()},
    ).context
    assert ctx["income"] == Decimal("700.00") and ctx["expense"] == Decimal("20.00")
    only = c.get(
        reverse("accounting:office_list"),
        {"baslangic": (old - dt.timedelta(days=1)).isoformat(), "tur": "income"},
    ).context
    assert [e.kind for e in only["entries"]] == ["income"]


# ---- iptal ---------------------------------------------------------------------------------


def test_cancel_needs_reason_and_is_final(admin_user):
    e = entry(admin_user)
    c = login(admin_user)
    c.post(reverse("accounting:office_cancel", args=[e.pk]), {"reason": " "})
    e.refresh_from_db()
    assert not e.is_cancelled
    c.post(reverse("accounting:office_cancel", args=[e.pk]), {"reason": "Yanlış girildi"})
    e.refresh_from_db()
    assert e.is_cancelled and e.cancelled_by == admin_user and e.cancel_reason == "Yanlış girildi"
    c.post(reverse("accounting:office_cancel", args=[e.pk]), {"reason": "Tekrar"})
    e.refresh_from_db()
    assert e.cancel_reason == "Yanlış girildi"


# ---- belge erişimi ----------------------------------------------------------------------------


def test_receipt_file_only_served_to_admin(admin_user, accountant, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    e = entry(admin_user)
    e.receipt.save("m.pdf", SimpleUploadedFile("m.pdf", PDF))
    assert login(admin_user).get(e.receipt.url).status_code == 200
    assert login(accountant).get(e.receipt.url).status_code == 403
    assert HttpClient().get(e.receipt.url).status_code == 302
