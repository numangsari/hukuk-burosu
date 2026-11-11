# Kullanışlılık İncelemesi — Hukuk Bürosu Otomasyonu 1.2.2

İnceleme tarihi: 11 Kasım 2026. İncelenen commit: `cfbae52`.

Program günlük büro işine iyi oturuyor; asıl zayıflık, öncelikli ekran olan 1366×768'de ortaya çıkıyor. 1920×1080'de belirgin bir sorun görülmedi.

Değerlendirme, deneme verisiyle (`seed_demo`) çalıştırılan uygulamanın ekran görüntülerine bakılarak yapıldı: giriş, ana sayfa, dosya/görev/muhasebe listeleri, dosya detayı, takvim, raporlar, ayarlar ve görev pencereleri. Çoğuna yönetici hesabıyla bakıldı.

## İyi çalışanlar

- **Giriş:** Kart seç, PIN gir; küçük bir büro için en hızlı yol.
- **Ana sayfa:** "Görevlerim" ve "Kontrolümü bekleyenler" yan yana; gecikenler kırmızı rozetle hemen görünüyor.
- **Tutarlı sayfa düzeni:** Her modülde başlık, sayı şeridi, Excel/PDF ve tek ana düğme aynı yerde. Bir ekranı öğrenen diğerlerini de biliyor.
- **Her yerden erişim:** Üstteki arama (Ctrl+K) ve "Yeni kayıt" menüsü her sayfada var.
- **Dosya detayı:** Aşama çizgisi dosyanın nerede olduğunu tek bakışta gösteriyor; sekmelerdeki sayılar boş sekmeye tıklamayı önlüyor.
- **Muhasebe:** "Alacağımız" etiketi ve altındaki bakiye formülü, en çok karışan konuyu açıklıyor.
- **Raporlar:** Müvekkile gidecek ve ofis içi raporların ayrılması yanlış belge gönderme riskini azaltıyor.

## Sorunlar (önem sırasıyla)

### 1. 1366'da yan menü etiketsiz simgelere iniyor

On üçten fazla simge var ve İcra İşlemleri ile UYAP Avukat kısayolu neredeyse aynı bina simgesini kullanıyor. Yeni başlayan biri hangi simgenin ne olduğunu üzerine gelip bekleyerek öğrenmek zorunda.

Öneri: en azından simgeler ayrıştırılmalı; daha iyisi menüyü açık sabitleme seçeneği.

### 2. Dosya listesinde mahkeme adı ayırt edici yerinden kesiliyor

1366'da "Sakarya 2. Asliye Ceza Mahke…" ve "Sakarya 1. Asliye Hukuk Mahk…" görünüyor, oysa sütunun sağında boş yer var. Aynı genişlikte Aşama ve Açık görev sütunları da gizleniyor; dosyaya bakan kişinin en çok aradığı iki bilgi bunlar.

### 3. Yedek uyarısı her pencerenin içinde tekrar çıkıyor

"Son 2 gündür başarılı yedek alınmadı" bandı sayfada dururken, açılan görev penceresinin içinde de ikinci kez görünüyor. Bu bir hata gibi duruyor ve zaten dar olan pencereden yer alıyor.

### 4. 768 yükseklikte içerik aşağı itiliyor

Dosya listesinde uyarı, başlık ve üç sıra süzgeç ekranın yarısından fazlasını kaplıyor; yalnızca 6 dosya görünüyor. Yeni görev penceresinde beş-altı bölümden ilk ikisi sığıyor.

Öneri: tür süzgeçleri dar ekranda tek açılır listeye inebilir.

### 5. Görev penceresinde iki ana düğme yarışıyor

Sağ üstte "Görevi tamamla", hemen altında "Kontrole gönder" aynı ağırlıkta duruyor. Bu, yönetici hesabıyla görüldü; diğer rollerde ikisinin birden çıkıp çıkmadığına bakılmadı.

### 6. Ana sayfada her görev vurgulu

"Görevlerim" kartındaki bütün satırlar mor zeminli ve "Yeni görev" rozetli; hepsi vurgulanınca geciken görev öne çıkmıyor.

### 7. Google Takvim uyarısı kalıcı

Takvim sayfasında geniş bir sarı bant, ana sayfada ayrıca bir not var. Google kullanmayan büro bunu her gün görecek.

Öneri: kapatılabilir olmalı ya da yalnızca yöneticiye gösterilmeli.

## Bakılmayanlar

- Avukat ve sekreter hesaplarıyla sayfalar açıldı ama görüntüleri tek tek incelenmedi.
- Kayıt oluşturma, görev onay akışı ve duruşma sonucu girme gibi işler baştan sona tıklanarak denenmedi.
- Koyu temaya bakılmadı.
- Gerçek kullanıcı gözlemi yok; bunlar ekrana bakılarak varılan yargılar.

## Öncelik önerisi

İlk üç madde küçük CSS ve şablon işleri; onlardan başlanabilir.
