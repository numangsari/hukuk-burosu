from django.db import migrations

TASK_TYPES = [('Dava dosyası inceleme', 2), ('Dava dilekçesi hazırlama ve Dava açılışı', 3), ('Cevap Dilekçesi sunulması', 3), ('Cevaba cevap Dilekçesi sunulması', 2), ('İkinci cevap dilekçesi sunulması', 2), ('Ara kararın yerine getirilmesi', 2), ('Delil sunma', 2), ('Bilirkişi raporuna beyan ve itiraz dilekçesi', 3), ('Tanık Listesi Sunma', 1), ('Beyan Dilekçesi Sunma', 2), ('Islah / Bedel artırım dilekçesi', 2), ('İhtiyati tedbir / İhtiyati haciz talebi', 3), ('Süre uzatım dilekçesi', 1), ('İstinaf dilekçesi', 3), ('İstinafa cevap dilekçesi', 2), ('Temyiz dilekçesi', 3), ('Temyize cevap dilekçesi', 2), ('Gerekçeli kararı tebliğe çıkarma', 1), ('Kesinleşme şerhi talebi', 1), ('İcra takibi başlatma', 3), ('Ödeme / İcra emri tebliğini takip', 1), ('İcra dosyası inceleme', 1), ('Takibin kesinleşmesini kontrol / Kesinleştirme işlemi', 1), ('Malvarlığı sorgulama ve Haciz talebi', 2), ('89/1-2-3 haciz ihbarnamesi talebi', 1), ('Kıymet takdirine itiraz', 3), ('Haciz Yenileme Talebi', 1), ('Satış işlemleri', 3), ('Dosya kapak hesabı talebi', 1), ('Taahhüt / Taksitlendirme işlemleri', 2), ('Tahsilat işlemleri', 1), ('Haricen tahsil bildirimi', 1), ('Haczin kaldırılması / Fek işlemleri', 1), ('İcra dosya kapama', 1), ('İcra takibine İtiraz', 2), ('İcra müdürlüğü işlemine karşı şikâyet', 3), ('İtirazın kaldırılması / İptali', 3), ('Evrak hazırlama', 1), ('Evrak gönderme', 1), ('Evrak inceleme', 1), ('Fiziki evrak tarama ve arşivleme', 1), ('Dosya inceleme', 2), ('Tebligat kontrolü', 1), ('Bila tebliğ (iade) tebligat işlemleri', 2), ('Müzekkere akıbeti takibi', 1), ('İhtarname işlemleri', 2), ('Müvekkil bilgilendirme', 1), ('Müvekkilden evrak / Bilgi talebi', 1), ('Dönemsel dava ve icra raporlaması', 2), ('Sözleşme hazırlama', 3), ('Avukatlık ücret sözleşmesi hazırlama', 1), ('Sulh ve ibraname protokolü hazırlama', 3), ('Harç / Masraf yatırma', 1), ('Müvekkilden masraf talebi', 1), ('Gider avansı yatırma', 1), ('Artan masrafı iade alma', 1), ('Vekâlet ücreti takibi', 2), ('Karşı vekâlet ücreti takibi', 2), ('Ödeme yapılması', 1), ('Tahsilat yapılması', 1), ('Serbest meslek makbuzu (E-SMM) düzenleme', 1), ('Müvekkil cari hesap mutabakatı', 2), ('Arabuluculuk başvurusu', 2), ('İcra edilebilirlik şerhi talebi', 2), ('Şikâyet dilekçesi hazırlama', 3), ('Esas hakkında mütalaaya karşı savunma dilekçesi', 3), ('Tutukluluğa itiraz', 2), ('Tahliyeye itiraz', 2), ('Adli kontrole itiraz', 2), ('Soruşturma dosyası inceleme', 2), ('Takipsizlik kararına itiraz', 2), ('Fiziki Dosya kontrolü', 2), ('Dosya kapatma ve arşivleme', 2), ('Fiziki Dosya Hazırlama', 2), ('Diğer', 2)]

def seed(apps, schema_editor):
    TaskType = apps.get_model("office", "TaskType")
    names = [name for name, _ in TASK_TYPES]
    TaskType.objects.exclude(name__in=names).update(is_active=False)
    for order, (name, points) in enumerate(TASK_TYPES):
        TaskType.objects.update_or_create(
            name=name, defaults={"order": order, "points": points, "is_active": True}
        )


class Migration(migrations.Migration):
    dependencies = [("office", "0008_tasktype_points")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
