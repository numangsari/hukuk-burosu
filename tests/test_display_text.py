import pytest

from apps.core.templatetags.ui import same_text
from apps.core.text import tr_title


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("SAKARYA 2. ASLİYE CEZA MAHKEMESİ", "Sakarya 2. Asliye Ceza Mahkemesi"),
        ("2026/151 ESAS", "2026/151 Esas"),
        ("KAYA, ALİ", "Kaya, Ali"),
        ("ÖRNEK İNŞAAT A.Ş.", "Örnek İnşaat A.Ş."),
        ("MEHMET VE AYŞE YILDIZ", "Mehmet ve Ayşe Yıldız"),
        ("ÇAĞ-DAŞ D.İŞ", "Çağ-Daş D.İş"),
        ("KAYA'NIN DAVASI", "Kaya'nın Davası"),
        ("IŞIK ILGAZ", "Işık Ilgaz"),
        (
            "GAZİOSMANPAŞA 8. ASLİYE CEZA MAHKEMESİ - 2023/271 Esas",
            "Gaziosmanpaşa 8. Asliye Ceza Mahkemesi - 2023/271 Esas",
        ),
        ("Numan Görkem SARI", "Numan Görkem Sarı"),
        ("SGK İL MÜDÜRLÜĞÜ", "SGK İl Müdürlüğü"),
        ("", ""),
        (None, ""),
    ],
)
def test_tr_title_converts_uppercase_for_display(raw, expected):
    assert tr_title(raw) == expected


def test_tr_title_leaves_mixed_case_text_untouched():
    assert tr_title("Kaya Hukuk Bürosu") == "Kaya Hukuk Bürosu"
    assert tr_title("UYAP Dosyası") == "UYAP Dosyası"
    assert tr_title("A") == "A"


def test_same_text_ignores_case_and_turkish_accents():
    assert same_text("Harç / Masraf Yatırma", "HARÇ / MASRAF YATIRMA")
    assert not same_text("Dilekçe", "Duruşma")
