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
