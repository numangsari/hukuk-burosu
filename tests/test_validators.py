import pytest
from django.core.exceptions import ValidationError

from apps.core.text import fold, tr_lower
from apps.core.validators import validate_iban, validate_tckn, validate_vkn

from .conftest import VALID_TCKN


def test_tckn_valid():
    validate_tckn(VALID_TCKN)


@pytest.mark.parametrize("value", ["", "12345", "01234567890", "10000000147", "abcdefghijk"])
def test_tckn_invalid(value):
    with pytest.raises(ValidationError):
        validate_tckn(value)


def test_vkn():
    validate_vkn("1234567890")
    with pytest.raises(ValidationError):
        validate_vkn("123")


def test_iban_valid_with_spaces():
    # Örnek TR IBAN (kontrol hanesi geçerli, gerçek hesap değil)
    validate_iban("TR33 0006 1005 1978 6457 8413 26")


def test_iban_invalid_checksum():
    with pytest.raises(ValidationError):
        validate_iban("TR34 0006 1005 1978 6457 8413 26")


def test_turkish_lower_and_fold():
    assert tr_lower("IŞIK") == "ışık"
    assert tr_lower("İSTANBUL") == "istanbul"
    assert fold("IŞIK") == fold("ışık") == fold("Isik") == "isik"
    assert fold("Çağlayan Ünlü") == "caglayan unlu"
