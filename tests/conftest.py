import pytest

from apps.accounts.models import User
from apps.cases.models import Case
from apps.clients.models import Client

# Testlerde gerçek kişi verisi kullanılmaz; aşağıdaki TCKN'ler algoritmik olarak üretilmiş
# geçerli test numaralarıdır.
VALID_TCKN = "10000000146"


def make_user(username, role, **kw):
    return User.objects.create_user(
        username=username, password="test-pass-123", role=role, first_name=username.title(), **kw
    )


@pytest.fixture
def admin_user(db):
    return make_user("yonetici", User.Role.ADMIN)


@pytest.fixture
def lawyer(db):
    return make_user("avukat", User.Role.LAWYER)


@pytest.fixture
def intern(db):
    return make_user("stajyer", User.Role.INTERN)


@pytest.fixture
def client_factory(lawyer, intern):
    def factory(**kw):
        defaults = {
            "kind": "person",
            "first_name": "Deneme",
            "last_name": "Kişi",
            "responsible_lawyer": lawyer,
            "responsible_intern": intern,
        }
        defaults.update(kw)
        return Client.objects.create(**defaults)

    return factory


@pytest.fixture
def case_factory(client_factory):
    counter = {"n": 0}

    def factory(client=None, **kw):
        counter["n"] += 1
        client = client or client_factory()
        defaults = {
            "client": client,
            "case_type": "civil",
            "archive_no": f"T-{counter['n']}",
            "subject": "Alacak davası",
            "responsible_lawyer": client.responsible_lawyer,
            "responsible_intern": client.responsible_intern,
        }
        defaults.update(kw)
        return Case.objects.create(**defaults)

    return factory


@pytest.fixture
def lawyer_client(client, lawyer):
    client.force_login(lawyer)
    return client


@pytest.fixture
def admin_client_logged(client, admin_user):
    client.force_login(admin_user)
    return client


def client_form_data(client=None, delete=(), **new_rows):
    """Müvekkil oluşturma/düzenleme formu için POST verisi.

    client verilirse mevcut alanlar ve alt kayıtlar (iletişim, IBAN, yetkili, vekalet) forma
    eklenir; delete içindeki (önek, pk) çiftleri silinmek üzere işaretlenir; new_rows ile
    önek başına yeni satırlar eklenir.
    """
    from django.forms.models import model_to_dict

    from apps.clients.forms import CLIENT_SUBRECORDS, ClientForm

    data = {}
    if client is not None:
        for name in ClientForm.Meta.fields:
            value = (
                getattr(client, f"{name}_id", None)
                if name.startswith("responsible")
                else (getattr(client, name))
            )
            data[name] = "" if value is None else value
    related = {
        "iletisim": "contacts",
        "iban": "ibans",
        "yetkili": "representatives",
        "vekalet": "powers_of_attorney",
    }
    for prefix, (_, form) in CLIENT_SUBRECORDS.items():
        existing = list(getattr(client, related[prefix]).order_by("pk")) if client else []
        rows = []
        for item in existing:
            row = {k: v for k, v in model_to_dict(item, fields=form.Meta.fields).items()
                   if v not in (None, False) and k != "pdf"}  # fmt: skip
            row["id"] = item.pk
            if (prefix, item.pk) in delete:
                row["DELETE"] = "on"
            rows.append(row)
        rows += new_rows.get(prefix, [])
        data[f"{prefix}-TOTAL_FORMS"] = str(len(rows))
        data[f"{prefix}-INITIAL_FORMS"] = str(len(existing))
        for i, row in enumerate(rows):
            data.update({f"{prefix}-{i}-{k}": v for k, v in row.items()})
    return data
