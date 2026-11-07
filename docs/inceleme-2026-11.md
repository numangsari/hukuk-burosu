# Teknik İnceleme — Kasım 2026

Bu belge kod tabanının bir defalık teknik incelemesidir; kalıcı kurallar `CLAUDE.md` dosyasındadır.
Maddeler giderildikçe bu belgede işaretlenebilir veya belge kaldırılabilir.

**İnceleme anındaki durum:** `uv run pytest` tamamı geçti, `ruff check` ve `ruff format --check` temiz,
GitHub Actions CI kurulu. İnceleme sırasında kodda değişiklik yapılmadı.

## Güncel durum (6 Kasım 2026)

Bulgular iki çalışmada ele alındı; ikisi de `main` dalındadır. Son durumda `uv run pytest`
634 geçti / 4 atlandı, `ruff check` ve `ruff format --check` temiz.

İşaretler: ✅ giderildi · ◐ kısmen giderildi · işaretsiz = açık.

| Bölüm | Giderildi | Kısmen | Açık |
|---|---|---|---|
| Teknik (1–10) | 1, 2, 5, 6, 8 | 3, 7, 9, 10 | 4 |
| UI/UX (1–17) | 1, 2, 3, 4, 5, 8, 9, 14, 15 | — | 6, 7, 10–13, 16, 17 |
| Kullanım sorunları (1–6) | 4, 6 | — | 1, 2, 3, 5 |
| Eksik özellikler (1–12) | — | — | tümü |
| Tasarım önerisi | — | — | beklemede |

**1. çalışma** (`f1777ce`, `8b55420`): uç bazında görünürlük ve yetki testleri, PIN deneme sınırı ve
hatalı PIN kaydı, geri yükleme öncesi güvenlik yedeği, Türkçe hata sayfaları ve HTMX hata bildirimi,
haciz middleware hatasının sayfayı bozmaması, dosya imzası denetimi, `media.py` açıklaması; yatay
taşma, koyu tema buton kontrastı, tutar satır kırılması.

**2. çalışma** (`f77062b`): başarısız Google Takvim eşitlemesinin işaretlenip `retry_google_sync` ile
yeniden denenmesi (iptal edilen duruşmada ağ hatası artık 500 vermez), kullanılmayan
`installer/OzkurtHukuk.iss` dosyasının kaldırılması, testlerdeki `staticfiles/` uyarısı; bakiye yönü için
"Alacağımız / Borcumuz" etiketi, duruşma listesinde anında filtre, gün boyu gizlenebilen yedek
uyarısı, rozet görünümlü görev durumları, yan menüde kaydırma gölgesi, taşmayan dosya numarası alanı.

Açık kalan maddeler ve nedenleri sayfa sonundaki "Açık kalanlar" bölümündedir.

> Öncelik: 🔴 kritik (güvenlik/veri) · 🟠 teknik sağlamlık · 🟡 kullanıcı deneyimi

---

## 🔴 Kritik — güvenlik ve veri gizliliği

### 1. ✅ "Sorumlu bazlı" görünürlük modunda yetki açıkları (doğrulandı)

`OfficeSettings.case_visibility_mode = restricted` iken, sorumlusu başka avukat olan bir dosyayla
geçici test yazılarak doğrulandı (test repoya eklenmedi). Dört senaryonun dördü de sızdırdı:

| Uç | Sorun |
|---|---|
| `Raporlar > Dosya listesi` (`apps/reports/definitions.py` → `build_cases`) | Tüm dosyalar listeleniyor. `build_client_cases`, `build_seizures`, `build_tasks` da `filter_visible_cases` kullanmıyor. |
| `/gorevler/<id>/` (`apps/tasks/views.py` → `TaskDetailView`) | Görmemesi gereken dosyanın görevi açılıyor. `TaskActionView`, `TaskNoteView`, `TaskCommentView`, görev belgesi uçları da görünürlük denetlemiyor. |
| `/dosyalar/<id>/durusma/yeni/` (`apps/cases/views_records.py`) | Görmediği dosyaya duruşma eklenebiliyor. `HearingResultView`, `EventAddView`, `EventDeleteView` ve `apps/cases/views_seizures.py` uçları da `get_object_or_404(Case, pk=pk)` ile filtresiz. |
| `/media/cases/...` (`apps/core/media.py`) | Başka dosyanın belgesi indirilebiliyor; yalnızca girişli olmak yeterli. `tasks/` ve `clients/` önekleri için de kayıt bazında denetim yok. |

Mevcut testler (`tests/test_accounts.py`) yalnızca `filter_visible_cases` fonksiyonunu sınıyor;
uç (URL) bazında yetki testi yok.

**Öneri:** Tüm dosya/görev/belge uçlarında görünür kayıt kümesi üzerinden nesne alınmalı; `media.py`
kayıt sahibinin dosyasını görünürlük kuralıyla denetlemeli; restricted modda tüm uçları gezen
parametrik bir yetki testi eklenmeli.

### 2. ✅ PIN deneme yoluyla kolayca bulunabilir (deneme sınırı eklendi; yönetici için uzun PIN/parola açık)

4 haneli PIN (10.000 olasılık), hatalı girişte bekleme/kilit yok ve giriş ekranı tüm aktif
kullanıcıları listeliyor. Ofis içinde bile bir kullanıcı yönetici PIN'ini kısa sürede deneyerek
bulup muhasebe, silme ve yedek indirme yetkisine erişebilir.

**Öneri:** Kullanıcı + IP bazında artan bekleme (ör. 5 hatalı denemeden sonra), başarısız girişlerin
aktivite kaydına yazılması, yönetici hesapları için daha uzun PIN/parola seçeneği.

### 3. ◐ Yedek güvenliği (yalnızca geri yükleme öncesi güvenlik yedeği giderildi)

- Arşivler parolasız.
- `BACKUP_DIR` varsayılanı kurulum klasörü içi (`apps/backups/services.py`); yedek ve canlı veri aynı
  diskte. Disk arızası veya fidye yazılımında ikisi birlikte kaybolur.
- `restore` geri yüklemeden önce mevcut veritabanının güvenlik yedeğini almıyor; yanlış dosya
  seçilirse geri dönüş yolu yok.

**Öneri:** Geri yükleme öncesi otomatik güvenlik yedeği, ikinci konuma (harici disk/NAS) kopya,
şifreli arşiv seçeneği, düzenli geri yükleme denemesi.

### 4. ◐ `DJANGO_ALLOWED_HOSTS=*` (yeni kurulumda daraltıldı; eski kurulumlarda `*` sürüyor)

Yeni kurulum bilgisayar adı ve IPv4 adreslerini yazar; sonradan adres eklemek için Ayarlar >
Erişim adresleri ekranı vardır. Mevcut kurulumlarda `.env` içindeki `*` elle daraltılmalıdır.

---

## 🟠 Teknik sağlamlık

### 5. ✅ Hata sayfaları ve HTMX hataları

- Özel 403/404/500 şablonu yok; üretimde Django'nun İngilizce varsayılan sayfası çıkıyor.
- `htmx:responseError` / `htmx:sendError` dinlenmiyor; HTMX isteği hata dönerse kullanıcı hiçbir
  geri bildirim görmüyor ("butona bastım, bir şey olmadı").

**Öneri:** Türkçe hata şablonları ve `base.html` içinde genel bir HTMX hata bildirimi (toast).

### 6. ✅ Haciz görev üretimi kullanıcı isteği içinde çalışıyor (hata artık yakalanıp günlüğe yazılıyor)

`apps/cases/middleware.py` → `SeizureTaskMiddleware` dakikada bir, rastgele bir kullanıcının isteği
içinde `create_due_tasks()` çalıştırıyor ve hatayı yeniden fırlatıyor; kullanıcı ilgisiz bir sayfada
500 hatası görür. Yalnızca zamanlanmış görevde çalışmalı ya da hata yakalanıp loglanmalı.

### 7. ◐ Google Takvim eşitlemesi eşzamanlı (yeniden deneme eklendi; istek içinde çalışma sürüyor)

`apps/cases/views_hearings.py` içinde `sync_hearing_to_google` istek sırasında çağrılıyor. İnternet
yavaş/yokken duruşma kaydetmek yavaşlar. Başarısız eşitlemeler için yeniden deneme kuyruğu
görülmedi; zamanlanmış bir "eşitlenmemişleri tekrar dene" adımı değerlendirilmeli.

**Yapılan:** Başarısız eşitleme `Hearing.google_sync_pending` ile işaretlenir; `retry_google_sync`
komutu kurulumda `check-reminders.ps1` üzerinden beş dakikada bir yeniden dener. **Kalan:** eşitleme
hâlâ istek içinde çalışır.

### 8. ✅ Yüklemelerde içerik denetimi yok

`apps/core/uploads.py` yalnızca uzantı ve boyuta bakıyor. `CLAUDE.md` §8 içerik uygunluğunu da
istiyor; en azından PDF/resim/Office türleri için dosya imzası (magic bytes) kontrolü eklenmeli.

### 9. ◐ Tekrarlanan kurulum dosyaları ve eski adlar (kullanılmayan `OzkurtHukuk.iss` kaldırıldı)

`installer/OzkurtHukuk.iss` ↔ `installer/HukukBurosu.iss`, `OzkurtHukukApp.xml` ↔ `HukukBuroApp.xml`
neredeyse aynı; zamanla ayrışma riski var. Veritabanı/kullanıcı adı `ozkurt` olarak CI'da ve
`restore` geliştirme yolunda sabit yazılı.

**Yapılan:** Hiçbir yerde kullanılmayan `OzkurtHukuk.iss` silindi. **Kalan:** `OzkurtHukukApp.xml` ve
`Ozkurt*` servis/görev adları eski kurulumların yükseltilmesi için gerekli olduğundan tutuldu.

### 10. ◐ Küçük düzeltmeler

- `OfficeSettings.load()` her çağrıda `get_or_create` yapıyor; bir istekte birkaç kez çağrılıyor
  (middleware, context processor, yetki fonksiyonları). İstek başına önbellek yeterli.
- ✅ `apps/core/media.py` açıklaması ("herkes tüm kayıtları görür") restricted modla çelişiyor.
- ✅ Testler `staticfiles/` klasörü yok uyarısı üretiyor (CI'da `mkdir` ile geçiştirilmiş).

---

## 🟡 Kullanıcı deneyimi (kod okumasına dayalı)

- ✅ Hata geri bildirimi (madde 5) en çok hissedilecek eksik.
- ✅ Kısıtlı kullanıcı Raporlar'da tüm dosyaları görüyor (madde 1); "yetkim var" diye algılanır.
- ✅ Başarısız giriş denemeleri yöneticiye aktivite kaydında gösterilebilir.
- Geri yükleme yalnızca komut satırından; yöneticinin arayüzden (önce otomatik güvenlik yedeği
  alarak) başlatabileceği bir akış büro için daha pratik olur.

---

## Önerilen sıra

1. Madde 1 — görünürlük açıkları + uç bazında yetki testleri
2. Madde 2 — PIN deneme sınırı
3. Madde 5 ve 6 — Türkçe hata sayfaları, HTMX bildirimi, haciz kontrolünün istekten ayrılması
4. Madde 3 — yedek güvenliği

---

## Açık kalanlar

### Karar veya Windows ortamı gerektirenler
- **Madde 4 (`DJANGO_ALLOWED_HOSTS=*`):** sunucu adı/IP'lerinin kurulumda nasıl belirleneceğine karar
  verilmeli (IP değişirse ofisten erişim kesilir); `installer/` betikleri Windows'ta denenmeli.
- **Kurulum betiği:** 2. çalışmada değişen `installer/scripts/check-reminders.ps1` Windows'ta henüz
  çalıştırılmadı; ilk kurulumda/güncellemede denenmeli.
- **Madde 7'nin kalanı:** eşitlemeyi istekten tamamen ayırmak (arka plan kuyruğu) mimari karar gerektirir.

### Güvenlik iyileştirmeleri
- **Madde 3'ün kalanı:** yedeğin ayrı diske/NAS'a kopyası, şifreli arşiv, yöneticinin arayüzden geri
  yükleme başlatması.
- **PIN:** sayaçlar önbellekte olduğundan servis yeniden başlayınca sıfırlanır; yönetici hesapları için
  daha uzun PIN/parola seçeneği yok.
- **Dosya imzası:** `.xls`, metin tabanlı türler (txt, csv, udf, eml) ve HEIC denetlenmez.

### Küçük teknik
- **Madde 10:** `OfficeSettings.load()` istek başına önbellek (eski değer riski nedeniyle ayrıca
  değerlendirilmeli).
- **Madde 9:** CI ve geliştirme veritabanı/kullanıcı adı `ozkurt` olarak duruyor.

### Tasarım kararı gerektirenler
- **UI/UX 6, 7, 10–13, 16, 17:** tek sekme bileşeni, tek Kaydet yeri, büyük harf gösterimi, liste
  yoğunluğu, ana sayfa kart tekrarı, arşiv kart boyutu, telefonda "Bugün" önceliği, sürükle-bırak yükleme.
- **Kullanım sorunları 1, 2, 3, 5** (yukarıdaki UI maddeleriyle örtüşür).
- **"Tasarım Önerisi"** bölümü.

### Yeni özellikler
- "Eksik özellikler" listesinin tamamı. Öncelik: hukuki süre hesaplayıcı (adli tatil ve bayramlar;
  `CLAUDE.md` §11 gereği öneri olarak ve hukuki doğrulamayla), sabah özeti/bildirimler, menfaat çakışması
  kontrolü.

---

# Kullanım ve Özellik Analizi

Sistem `seed_demo` verisiyle (18 müvekkil, 32 dosya, 48 görev) yerelde çalıştırılıp yönetici rolüyle
masaüstü ve telefon genişliğinde gezilerek değerlendirildi. Deneme verisinde duruşma olmadığından takvim
ve duruşma listesi dolu hâliyle değerlendirilemedi.

## Güçlü yanlar

- **Ana sayfa:** "Görevlerim", "Kontrolümü bekleyenler" ve "Takvim" yan yana; gecikmeler kırmızı
  rozetle hemen görülüyor.
- **Dosya detayı:** Aşama çubuğu (Derdest → Kesinleşti), sekmeler, ekip ve tarihler tek bakışta.
- **Görev–kontrolcü akışı** büro hiyerarşisine uygun (stajyer yapar, avukat onaylar, puan yazılır).
- **UYAP/UETS köprüsü, fiziki arşiv, safahat ve haciz yenileme takibi** büroya özgü ve gerçek
  ihtiyaçtan doğmuş özellikler.
- **Telefonda kullanılabilir:** menü katlanıyor, kartlar alt alta diziliyor.

## Ekranlarda görülen kullanım sorunları

1. **Ana sayfa kartlarında tekrar:** Görev adı çoğu zaman türle aynı ("HARÇ / MASRAF YATIRMA" ve altında
   "Harç / Masraf Yatırma"), üstelik başlık kesiliyor. İkinci satırda ayırt edici bilgi (not, karşı taraf)
   daha yararlı olur.
2. **Dosya listesinde "sonraki duruşma / son işlem" sütunu yok.** "Dosya bilgisi" sütunu dar olduğundan
   satırlar 4–5 satıra kırılıyor; 25 dosya için uzun kaydırma gerekiyor.
3. **Telefonda öncelik sırası:** Takvim kartı en altta. Adliyedeki avukat için bugünkü duruşmalar en
   üstte olmalı.
4. ✅ **Filtre davranışı tutarsız:** Arşiv ve görevlerde seçim anında süzülüyor; duruşma listesinde ayrıca
   "Filtrele" butonuna basmak gerekiyor.
5. **Belge yükleme** tarayıcının standart dosya seçicisiyle; sürükle-bırak zaman kazandırır.
6. ✅ **Hata geri bildirimi yok** (teknik madde 5).

## Eksik özellikler (değere göre)

### Yüksek değer — risk azaltır

1. **Hukuki süre hesaplayıcı:** Adli tatil (20 Temmuz–31 Ağustos), resmi/dini bayramlar ve hafta sonuna
   denk gelen son günün kaydırılması kodda yok; tebligat görevine sabit 14 gün ekleniyor. Hesaplanan gün
   `CLAUDE.md` §11 gereği "kontrol edilmeli" uyarısıyla önerilmeli.
2. **Personele bildirim/hatırlatma:** Uygulama içi bildirim merkezi, e-posta veya masaüstü bildirimi yok;
   yalnızca ana sayfa ve müvekkile WhatsApp var. Sabah günlük özet ve yeni görev bildirimi önerilir.
3. **Menfaat çakışması kontrolü:** Yeni müvekkil eklenirken başka dosyada karşı taraf olup olmadığı
   uyarısı yok (yalnızca vekaletname aktarımında benzer kontrol var).
4. **Dava açma / hak düşürücü süre takibi:** Dosya açılmadan önceki süreler için dosyaya bağlı son tarih
   ve uyarı yok.

### Orta değer — zaman kazandırır

5. **Faiz ve icra dosya hesabı** (yasal, ticari, avans faizi).
6. **AAÜT asgari vekalet ücreti hesabı.**
7. **Serbest meslek makbuzu takibi** (kesildi mi, numarası); ileride e-SMM.
8. **Avukatlık sözleşmesine bağlı taksit/vade takibi.**
9. **Belge içinde arama** (PDF/UDF içeriği).

### Düşük değer / ihtiyaca bağlı

10. Zaman ve emek kaydı (saatlik danışmanlık).
11. Tekrarlayan görevler.
12. Müvekkile gönderilecek tek sayfalık dosya durum özeti PDF'i.

## Kullanım tarafında önerilen sıra

1. Süre hesaplayıcı (adli tatil ve bayramlar dahil)
2. Sabah özeti ve bildirimler
3. Dosya listesine "sonraki duruşma / son işlem" sütunu ve telefonda "bugün" bölümünün en üste alınması

---

# UI/UX Analizi

Ekranlar 1440×900, 1280×800 ve 390×844 (telefon) boyutlarında, açık ve koyu temada gezildi. Yatay taşma
ve renk kontrastı tarayıcıda ölçüldü.

## Genel izlenim

Görsel dil tutarlı ve profesyonel: sakin lacivert/altın palet, kart tabanlı düzen, anlaşılır boş durumlar
("Henüz dilekçe yüklenmedi", "Duruşma kaydı bulunamadı"), renkli süre rozetleri (gecikti / kaldı),
`Ctrl K` ile genel arama ve gerçek bir koyu tema. Giriş ekranı büroya özgü ve şık.

## Hatalar (ölçülerek doğrulandı)

1. ✅ **Yeni görev sayfası yatay taşıyor.** Sayfa 1440 px ekranda 1643 px, telefonda 609 px genişliğe çıkıyor.
   Neden: `BootstrapMixin` (`apps/core/forms.py`) radyo butonlarına da `form-control` sınıfı ekliyor;
   "Gelir/gider kaydı Var/Yok" seçimindeki gizli radyolar (`.segment-choice input { position:absolute;
   opacity:0 }`) %100 genişlik alıp sayfayı sağa itiyor. Çözüm: `RadioSelect` için `form-control`
   eklememek veya gizli girdiye `width:1px; height:1px` vermek.
2. ✅ **Koyu temada birincil buton kontrastı düşük:** beyaz yazı / `rgb(91,143,214)` zemin = **3.31:1**
   (normal metin için WCAG AA en az 4.5:1). Koyu temada buton zemini koyulaştırılmalı ya da yazı rengi
   koyu yapılmalı.
3. ✅ **Yeni dosya formunda dosya numarası alanı sıkışık:** sıra no kutusu birkaç karakter genişliğinde,
   "Esas" seçimi sütun sınırını aşıp sağdaki "Fiziki arşiv yeri" bölümüne taşıyor.
4. ✅ **Muhasebe tablosunda tutar kırılıyor:** "102.200,00" ve "₺" ayrı satırlara düşüyor; tutar hücresi
   `white-space: nowrap` olmalı.
5. ✅ **Kenar menüsü 900 px yükseklikte kesiliyor:** "Kısayollar" altındaki üçüncü bağlantı yarım
   görünüyor; kullanıcı menünün kaydırılabildiğini fark etmeyebilir.

## Tutarlılık

6. **Dört farklı sekme stili var:** Görevler ve dosya detayı alt çizgili; Duruşma Listesi dolu hap +
   düz metin; Arşiv dolu hap + iki satıra taşan bağlantılar; Görevler'de ayrıca "Bana atanmış / Tümü"
   segment kontrolü. Tek bir sekme bileşeni seçilmeli.
7. **Kaydet butonunun yeri değişiyor:** Yeni dosya'da sağ üstte, Yeni görev'de formun altında.
8. ✅ **Filtreleme davranışı farklı:** Arşiv ve görevlerde anında, duruşma listesinde "Filtrele" butonuyla.
9. ✅ **Durum gösterimi:** Görev listesinde "Yeni Görev" durumu mavi bağlantı gibi görünüyor; diğer
   yerlerde durumlar rozetle gösteriliyor.

## Okunabilirlik ve yoğunluk

10. **Her yerde BÜYÜK HARF:** Müvekkil, konu ve görev adları `tr_upper` ile büyük harfe çevriliyor
    (`CLAUDE.md` §4 iş kuralı). Saklama böyle kalabilir; ama listelerde uzun büyük harf metinler okumayı
    yavaşlatıyor ve satırları uzatıyor. Görüntülemede başlık biçimi (ör. "Sakarya 2. Asliye Ceza
    Mahkemesi") veya en azından ikincil satırlarda normal yazım değerlendirilebilir.
11. **Dosya ve muhasebe listelerinde satırlar çok yüksek:** Dar sütunlar yüzünden her satır 3–5 satıra
    kırılıyor; 25 kayıtlık sayfa ekranın 4–5 katı uzunlukta. Mahkeme adı ile esas no'yu iki satıra
    ayırmak ve sütun genişliklerini ayarlamak yeterli olabilir.
12. **Ana sayfa kartlarında başlık erken kesiliyor** ve altında aynı bilgi (görev türü) tekrarlanıyor.
13. **Arşiv kartları bilgiye göre büyük:** "0 / 8, %0 doluluk" bilgisini göstermek için büyük kartlar
    kullanılıyor; kompakt görünüm düğmesi çok küçük. Varsayılan olarak kompakt liste düşünülebilir.
14. ✅ **Bakiye rengi:** "Bakiye tutar 1.009.350,00 ₺" kırmızı. Pozitif bakiye "müvekkil ofise borçlu"
    demek; kırmızı genelde ofisin zararı gibi algılanır. Renk yerine "Alacağımız / Borcumuz" etiketi
    daha açık olur.
15. ✅ **Yedek uyarısı** her sayfanın en üstünde sabit duruyor ve dikey alan kaplıyor; gün boyu
    kapatılabilir olabilir veya küçük bir rozet olarak menüye taşınabilir.

## Telefon

16. Düzen çalışıyor; ancak ana sayfada takvim en altta. Telefonda sıra "Bugün (duruşmalar + süresi
    dolan) → Görevlerim → Kontrolümü bekleyenler" olmalı.
17. Belge yüklemede sürükle-bırak masaüstünde, kameradan çekip yükleme telefonda zaman kazandırır.

## UI/UX tarafında önerilen sıra

1. Yatay taşma (madde 1) ve koyu tema kontrastı (madde 2): küçük ve kesin düzeltmeler
2. Yeni dosya numara alanı ve muhasebe tutar kırılması (madde 3–4)
3. Tek sekme bileşeni, tek Kaydet yeri, anında filtre (madde 6–8)
4. Liste yoğunluğu ve büyük harf kullanımı (madde 10–11)

---

# Tasarım Önerisi — "Sade ve yoğun profesyonel" (beklemede)

Durum: **öneri aşamasında, uygulanmadı.** Önce/sonra görselleri:
https://claude.ai/artifact/1diSEbuWFnkjoKLD5D5skg (özel bağlantı; yalnızca sahibine açık).
Görsellerdeki "sonra" ekranlarında yer alan duruşma ve dosya ayrıntıları sentetik örnek veridir.

## Neden

Mevcut tasarım "yumuşak SaaS paneli" tarzında: yuvarlak kartlar, renkli zeminler, bol rozet ve geniş
boşluklar. Günde saatlerce yüzlerce kayda bakan büro çalışanı için ekrana az bilgi sığıyor
(25 dosyalık liste ekranın 4–5 katı) ve renk fazlalığı yüzünden "gecikti" gibi kritik uyarılar
kayboluyor.

## Kurallar

1. **Renk yalnızca anlam taşır:** nötr gri zemin, tek vurgu rengi (lacivert `#1F3A63`); kırmızı
   `#B42318` = gecikti, kehribar `#9A4D06` = yaklaşıyor. "Yeni görev" için satır boyamak yerine küçük
   nokta. Muhasebede renk yerine "Alacağımız / Borcumuz" etiketi.
2. **Tipografi:** Sayfa başlıkları ve dosya adları serif (Source Serif 4), arayüz Inter; tutar ve
   tarihlerde hizalı rakamlar (`font-variant-numeric: tabular-nums`). Veritabanında büyük harf kalabilir,
   ekranda normal yazım gösterilir.
3. **Yoğunluk:** Tablo öncelikli listeler, ~40 px satır, kompakt görünüm varsayılan; gölge yerine ince
   çizgi; köşe yuvarlaklığı 12 px → 6 px.
4. **Liste + detay aynı ekranda:** Görev ve dosya listelerinde satıra tıklayınca sağda özet paneli
   (aşama, sonraki duruşma, taraflar, bakiye, açık görevler).
5. **Klavye:** `Ctrl K` aramadan komut paletine genişler ("yeni görev", "2026/919'a git").

## Görsellerde gösterilen ekranlar

- **Ana sayfa:** serif tarih başlığı, 4 rakamlık tek özet şeridi (bugün duruşma, süresi geçen, bu hafta
  biten, kontrol bekleyen), yoğun "Görevlerim" tablosu, saatli "Bugünkü duruşmalar", yedek uyarısı
  banttan küçük rozete.
- **Dosyalar:** "Sonraki duruşma" sütunu (bugün vurgulu), tek satırlık filtre çubuğu (durum segmenti,
  tür/sorumlu/aşama seçimleri), sağda seçili dosya paneli.
- **Telefon:** "Bugün" en üstte (duruşmalar → süresi geçen/yaklaşan → görevler), 44 px dokunma
  hedefleri, altta 5 sekmeli menü.

## Uygulama notları

- Bootstrap 5.3 + HTMX/Alpine korunur; değişikliğin çoğu `static/css` içindeki CSS değişkenleri
  (renk, yazı tipi, boşluk, köşe) ve birkaç ortak şablondadır.
- İnternetsiz çalışma kuralı gereği Source Serif 4 `static/vendor/` altına yerel eklenmeli (Inter zaten
  yerel). Görseldeki Google Fonts bağlantısı yalnızca taslak içindir.
- Koyu tema aynı değişkenlerle yeniden ayarlanmalı; birincil buton kontrastı ≥ 4.5:1 olmalı
  (UI/UX madde 2).
- Önerilen sıra: (1) renk/yazı tipi değişkenleri, (2) liste yoğunluğu ve normal yazım gösterimi,
  (3) liste + detay paneli, (4) komut paleti.
