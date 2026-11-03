from django.db import migrations


OPTIONAL_TYPES = [
    "Dava Dosyası İnceleme",
    "Ara Kararın Yerine Getirilmesi",
    "Gerekçeli Kararı Tebliğe Çıkarma",
    "Ödeme / İcra Emri Tebliğini Takip",
    "İcra Dosyası İnceleme",
    "Takibin Kesinleşmesini Kontrol / Kesinleştirme İşlemi",
    "Malvarlığı Sorgulama Ve Haciz Talebi",
    "89/1-2-3 Haciz İhbarnamesi Talebi",
    "Kıymet Takdirine İtiraz",
    "Haciz Yenileme Talebi",
    "Satış İşlemleri",
    "Dosya Kapak Hesabı Talebi",
    "Taahhüt / Taksitlendirme İşlemleri",
    "Tahsilat İşlemleri",
    "Haricen Tahsil Bildirimi",
    "Haczin Kaldırılması / Fek İşlemleri",
    "İcra Dosya Kapama",
    "Evrak Gönderme",
    "Evrak İnceleme",
    "Fiziki Evrak Tarama Ve Arşivleme",
    "Dosya İnceleme",
    "Tebligat Kontrolü",
    "Bila Tebliğ (İade) Tebligat İşlemleri",
    "Müzekkere Akıbeti Takibi",
    "Müvekkil Bilgilendirme",
    "Müvekkilden Evrak / Bilgi Talebi",
    "Harç / Masraf Yatırma",
    "Müvekkilden Masraf Talebi",
    "Gider Avansı Yatırma",
    "Artan Masrafı İade Alma",
    "Vekâlet Ücreti Takibi",
    "Karşı Vekâlet Ücreti Takibi",
    "Ödeme Yapılması",
    "Tahsilat Yapılması",
    "Soruşturma Dosyası İnceleme",
    "Fiziki Dosya Kontrolü",
    "Dosya Kapatma Ve Arşivleme",
    "Fiziki Dosya Hazırlama",
    "Diğer",
]


def update_types(apps, schema_editor):
    apps.get_model("office", "TaskType").objects.filter(name__in=OPTIONAL_TYPES).update(
        requires_document=False
    )


class Migration(migrations.Migration):
    dependencies = [("office", "0013_task_document_requirements")]
    operations = [migrations.RunPython(update_types, migrations.RunPython.noop)]
