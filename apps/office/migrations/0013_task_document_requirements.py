from django.db import migrations


DOCUMENT_TYPES = [
    "Dava Dilekçesi Hazırlama Ve Dava Açılışı",
    "Cevap Dilekçesi Sunulması",
    "Cevaba Cevap Dilekçesi Sunulması",
    "İkinci Cevap Dilekçesi Sunulması",
    "Delil Sunma",
    "Bilirkişi Raporuna Beyan Ve İtiraz Dilekçesi",
    "Tanık Listesi Sunma",
    "Beyan Dilekçesi Sunma",
    "Islah / Bedel Artırım Dilekçesi",
    "İhtiyati Tedbir / İhtiyati Haciz Talebi",
    "Süre Uzatım Dilekçesi",
    "İstinaf Dilekçesi",
    "İstinafa Cevap Dilekçesi",
    "Temyiz Dilekçesi",
    "Temyize Cevap Dilekçesi",
    "Kesinleşme Şerhi Talebi",
    "İcra Takibi Başlatma",
    "İcra Takibine İtiraz",
    "İcra Müdürlüğü İşlemine Karşı Şikâyet",
    "İtirazın Kaldırılması / İptali",
    "Evrak Hazırlama",
    "İhtarname İşlemleri",
    "Dönemsel Dava Ve İcra Raporlaması",
    "Sözleşme Hazırlama",
    "Avukatlık Ücret Sözleşmesi Hazırlama",
    "Sulh Ve İbraname Protokolü Hazırlama",
    "Serbest Meslek Makbuzu (E-SMM) Düzenleme",
    "Müvekkil Cari Hesap Mutabakatı",
    "Arabuluculuk Başvurusu",
    "İcra Edilebilirlik Şerhi Talebi",
    "Şikâyet Dilekçesi Hazırlama",
    "Esas Hakkında Mütalaaya Karşı Savunma Dilekçesi",
    "Tutukluluğa İtiraz",
    "Tahliyeye İtiraz",
    "Adli Kontrole İtiraz",
    "Takipsizlik Kararına İtiraz",
]
APPEAL_TYPES = [
    "İstinaf Dilekçesi",
    "İstinafa Cevap Dilekçesi",
    "Temyiz Dilekçesi",
    "Temyize Cevap Dilekçesi",
]


def update_types(apps, schema_editor):
    task_type = apps.get_model("office", "TaskType")
    task_type.objects.filter(name__in=DOCUMENT_TYPES).update(requires_document=True)
    for item in task_type.objects.filter(name__in=APPEAL_TYPES):
        item.categories = [
            category for category in item.categories if category != "Ceza ve Soruşturma İşlemleri"
        ]
        item.save(update_fields=["categories"])


class Migration(migrations.Migration):
    dependencies = [("office", "0012_capitalize_task_type_names")]
    operations = [migrations.RunPython(update_types, migrations.RunPython.noop)]
