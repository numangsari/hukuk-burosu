# Yapılacaklar

Tarih: 7 Kasım 2026. Üç belgenin birleşimidir; çakışan maddeler tek satıra indirildi:

- `docs/inceleme-2026-11.md` → kaynak kodu **T** (teknik), **K** (kullanım), **U** (UI/UX)
- `docs/inceleme-2026-11-07.md` → kaynak kodu **B** (bulgu numarası)
- `docs/masaustu-tasarim-onerileri.md` → kaynak kodu **M**

## Kaldığımız yer (7 Kasım 2026)

- Karar verilenler: tasarım yönü = eski öneri (Y24), inceleme/oluşturma pop-up ile, yan panel yok (Y29), listelerde normal yazım (Y27), `ALLOWED_HOSTS` için ad + IP listesi ve yönetici ekranı (Y11).
- Tasarım uygulamasında bitenler: renk/yazı tipi değişkenleri ve Source Serif 4, sıkı satır, `tr_title` normal yazım, dosya listesinde mahkeme/numara ayrımı, `…` ile kısaltma, tablo başlıklarında normal yazım, dosya listesinde "sonraki duruşma" sütunu, bakiye şeridi kompakt.
- Sıradaki: Y29 devamı (dosya ve belge listeleri), Y30–Y32.
- Karar bekleyen en önemli güvenlik maddesi: Y01 (HTTPS). Seçenekler: ofis içi sertifika, ters vekil + yerel CA, şimdilik atla.
- Açık not: geliştirme veritabanında gerçek büro verisi görünüyor; `CLAUDE.md` kuralı gereği sentetik veriyle değiştirilmesi değerlendirilmeli.
- Yerelde çalıştırma: `uv run python -m pytest` (Windows'ta `uv run pytest` trampoline hatası verir), `PYTHONUTF8=1` gerekir.

Durum: `[ ]` açık · `[~]` kısmen · `[x]` bitti. **Karar** = uygulamadan önce kullanıcıdan karar gerekir.
Kullanım ~%99 masaüstünde olduğundan telefon maddeleri en sona alındı.

---

## A. Güvenlik ve veri gizliliği

| No | İş | Kaynak | Durum | Not |
|---|---|---|---|---|
| Y01 | Ofis içi ağ için HTTPS (TLS): sertifika/isim planı, Secure çerezler, yönlendirme | B02 | [ ] | **Karar** + Windows kurulum değişikliği. Şu an PIN ve belgeler şifresiz HTTP ile gidiyor. |
| Y02 | Yönetici kimliği: uzun PIN/parola seçeneği, MFA, deneme sayacını kalıcı ve atomik yap | T2, B03 | [~] | Yavaşlatma var ama bellekte; servis yeniden başlayınca sıfırlanır. **Karar** (giriş deneyimi). |
| Y03 | Yedek güvenliği: şifreli arşiv, ayrı disk/NAS kopyası, düzenli geri yükleme tatbikatı, yöneticiye arayüzden geri yükleme; Google servis hesabı JSON'unu düz metin saklamama | T3, B09 | [~] | Geri yükleme öncesi güvenlik yedeği yapıldı. **Karar** (anahtar yönetimi). |
| Y04 | Tebligat erişim politikası: liste, ayrıntı ve belge indirme uçlarında nesne bazlı görünürlük; eşleşmemiş tebligat için inceleme yetkisi | B06 | [ ] | **Karar** (kim neyi görür). |
| Y05 | Muhasebe/makbuz rol matrisi: kim görür, kim iptal eder | B07 | [ ] | **Karar**. `can_view_balances` tek başına mali gizlilik sağlamaz. |
| Y06 | Dosyasız randevu/duruşma gizliliği (`restricted` modda herkese görünüyor): ofis toplantısı ile özel müvekkil görüşmesini ayır | B11 | [ ] | **Karar**. |
| Y07 | Audit kaydında kişisel veri: alan bazlı maskeleme/dışlama, saklama süresi | B08 | [ ] | Eski kayıtların temizliği ayrı ve onaylı veri işlemi. |
| Y08 | Google'a giden veriyi azalt (not/karar varsayılan dışarıda); iCal URL için iç ağ/yönlendirme kısıtı (SSRF) | B10, B14 | [ ] | **Karar** (hangi alanlar gitsin). |
| Y09 | İlk kurulum yarışı: tek kullanımlık yerel kurulum sırrı ve kilitli tekrar kontrol | B13 | [ ] | **Karar**. |
| Y10 | Yükleme güvenliği: yerel virüs taraması/karantina; `.xls`, txt, csv, udf, eml, HEIC için imza denetimi | B15, T8 | [~] | PDF/resim/Office imzası var. Yeni araç gerektirir. |
| Y11 | Eski kurulumlarda `.env` içindeki `DJANGO_ALLOWED_HOSTS=*` değerini daralt | T4, B12 | [~] | Yeni kurulum ve yönetici ekranı yapıldı (`c08ec75`). Mevcut kurulumlar elle daraltılmalı. |

## B. Teknik sağlamlık ve test

| No | İş | Kaynak | Durum | Not |
|---|---|---|---|---|
| Y12 | Google Takvim eşitlemesini istekten ayır (arka plan kuyruğu) | T7 | [~] | Başarısız eşitleme işaretlenip yeniden deneniyor; eşitleme hâlâ istek içinde. Mimari **karar**. |
| Y13 | UYAP/UETS Node testlerindeki 6 başarısızlığı düzelt ve CI'a ekle; desteklenen davranış matrisi (üretimde `DEBUG=False` iken aktarım kapalı) yaz | B19, B20 | [ ] | Hedef aktarım kapsamı netleşmeden test beklentisi değiştirilmez. |
| Y14 | `postinstall.ps1` ve `check-reminders.ps1`'i gerçek kurulumlu Windows makinede dene | T4 | [~] | Sözdizimi ve sahte servisle çalışma doğrulandı; gerçek servis/zamanlanmış görev denenmedi. |
| Y15 | `OfficeSettings.load()` için istek başına önbellek | T10 | [ ] | Eski değer riski ayrıca değerlendirilmeli. |
| Y16 | CI ve geliştirme veritabanı/kullanıcı adı `ozkurt` adlarını yeniden adlandır | T9 | [ ] | Eski kurulumların yükseltilmesi için `Ozkurt*` servis/görev adları kalmalı. |
| Y17 | Performans: aktivite listesinde N+1, raporların tüm satırları belleğe alması | B23 | [ ] | Gerçek hacimle ölçüm yapılmadı. |
| Y18 | Windows'ta `tests/test_audit_template_security.py` cp1254 kodlama hatası (`read_text()` kodlama vermiyor) | yeni | [ ] | Linux CI'da sorun yok; yerelde `PYTHONUTF8=1` ile geçiyor. |

## C. Hukuki özellikler ve yeni işlevler

| No | İş | Kaynak | Durum | Not |
|---|---|---|---|---|
| Y19 | Hukuki süre hesaplayıcı (adli tatil 20 Temmuz–31 Ağustos, bayramlar, hafta sonu kayması); tebligat tarihi belirsizse "önerilen tarih" ile avukat teyidini ayır | K1, B18 | [ ] | `CLAUDE.md` §11: kesin süre gibi gösterilmez, hukuki doğrulama gerekir. En yüksek değerli özellik. |
| Y20 | Personele bildirim: sabah günlük özeti, yeni görev bildirimi | K2 | [ ] | Dış servis kullanılmaz (çevrimdışı çalışma). |
| Y21 | Menfaat çakışması kontrolü (yeni müvekkilde karşı taraf uyarısı) | K3 | [ ] | |
| Y22 | Dava açma / hak düşürücü süre takibi (dosyaya bağlı son tarih ve uyarı) | K4 | [ ] | Y19 ile birlikte tasarlanmalı. |
| Y23 | Orta/düşük değerli özellikler: faiz ve icra hesabı, AAÜT asgari ücret hesabı, serbest meslek makbuzu takibi, sözleşmeye bağlı taksit/vade, belge içi arama, zaman kaydı, tekrarlayan görevler, müvekkil durum özeti PDF'i | K5–K12 | [ ] | İhtiyaç çıktıkça seçilir. |

## D. Arayüz (masaüstü öncelikli)

| No | İş | Kaynak | Durum | Not |
|---|---|---|---|---|
| Y24 | **Karar verildi (7 Kasım 2026): eski öneri ("Sade ve yoğun profesyonel").** Nötr gri zemin, tek vurgu `#1F3A63`, kırmızı `#B42318` = gecikti, kehribar `#9A4D06` = yaklaşıyor; serif başlık/dosya adı (Source Serif 4), arayüz Inter, tabular rakamlar; 6 px köşe, gölge yerine ince çizgi, ~40 px satır; renk yerine nokta + metin. Referans: `docs/prototip/tasarim-karsilastirma.html` (2. sekme). | U-öneri | [x] | Source Serif 4 `static/vendor/` altına yerel eklenmeli (CDN yok). Koyu tema aynı değişkenlerle yeniden ayarlanır, buton kontrastı ≥ 4.5:1. |
| Y25 | **Kısmen yapıldı:** sıkı satır, dosya listesinde mahkeme/numara ayrımı ve `…` kısaltma bitti; sabit başlık ve ana sayfa kartındaki tekrar kaldı. (Eski öneri kuralları ile) Liste yoğunluğu: satır yüksekliği, sabit başlık, hizalı tutar/tarih; ana sayfa kartında tekrarlanan görev türünü kaldır | U11, U12, K1–K2, M1, M4 | [ ] | Mahkeme adı ile esas no'yu iki satıra ayırmak çoğu kırılmayı giderir. |
| Y26 | Tek sekme bileşeni, tek "Kaydet" yeri | U6, U7 | [x] | Sekmeler tek stilde; Kaydet tüm kayıt formlarında sabit üst çubukta (pop-up dahil). Ayarlar, içe aktarma ve silme onay sayfaları kapsam dışı. |
| Y27 | Listelerde BÜYÜK HARF yerine normal yazım göster (saklama `tr_upper` ile büyük kalır) | U10 | [~] | Listeler ve ana sayfa yapıldı (`tr_title`, `CLAUDE.md` §4'e işlendi); detay sayfası başlıkları kaldı; tablo başlıkları normal yazıma çevrildi. |
| Y28 | Arşiv kartlarını varsayılan kompakt yap | U13 | [ ] | |
| Y29 | Liste satırına tıklayınca kayıt özeti **pop-up (modal) içinde** açılsın; yan panel yapılmayacak. Önce görev listesinde pilot, sonra dosya ve belge listeleri. | M3 | [~] | **Karar (7 Kasım): yeni kayıtların tamamı pop-up; mevcut kayıtta görev ve tebligat pop-up, dosya ve müvekkil tam sayfa (liste satırı doğrudan detaya gider). Görev ve tebligat yapıldı:** görev pop-up zaten açılıyordu; kaydedilmemiş metin uyarısı eklendi, işlem yapılmadan kapanınca liste yenilenmiyor (kaydırma/filtre/sayfa korunur) ve odak satıra döner. Duruşmanın ayrıntı sayfası yok, işlemleri pop-up; belge listesi kaldı. **Karar verildi: yan panel yok, her şey pop-up.** Pop-up izinleri tam sayfa ile aynı; kaydedilmemiş değişiklik uyarısı; kapanınca filtre, sıralama, sayfa ve kaydırma konumu ve odaklanan satır korunur. Prototipteki sağ panel kaldırılacak. |
| Y30 | Filtre, sıralama ve sütun tercihlerini kaydet; detaydan dönüşte konumu koru | M2 | [ ] | Tercih erişim hakkı kazandırmamalı. |
| Y31 | Dosya detay yerleşimi: kompakt başlık, geniş ana alan, süre/sorumlu/sıradaki iş bilgisi (yan panel yerine sayfa içi dar sütun) | M5 | [ ] | 768 px yükseklikte sabit alanlar çalışma alanını yememeli. |
| Y32 | Klavye kısayolları, komut paleti (`Ctrl K` genişletme), son açılan kayıtlar, daraltılabilir yan menü | M7 | [ ] | |
| Y33 | Belge yüklemede sürükle-bırak | U17, K5 | [ ] | |
| Y34 | Toplu işlem (satır seçimi, toplu atama/dışa aktarma) | M | [ ] | Kayıt bazlı izin; süre ve mali iptal kapsam dışı. |
| Y35 | Erişilebilirlik ve E2E: ekran okuyucu, klavye, tüm roller için tarayıcı testi | B | [ ] | |
| Y36 | Telefon: "Bugün" bölümü en üstte, muhasebe tablosu için kart görünüm | U16, K3 | [ ] | **Düşük öncelik** (kullanımın ~%1'i). |

---

## Bitenler (özet)

- Görünürlük açıkları ve uç bazında yetki testleri (T1), PIN deneme yavaşlatma (T2), Türkçe hata sayfaları ve HTMX bildirimi (T5), haciz middleware hatası (T6), dosya imzası denetimi (T8, kısmen).
- Yatay taşma, koyu tema kontrastı, numara alanı, tutar kırılması, menü gölgesi (U1–U5); anında filtre, durum rozetleri, bakiye etiketi, gizlenebilir yedek uyarısı (U8, U9, U14, U15).
- İlk kurulum yarışının pasif hesap kolu (B01), arama sızıntısı (B04), XSS (B05), dış yönlendirme (B16), kısa arama hatası (B17), yedek uyarısı betiği (B21), form ARIA (B22).
- `ALLOWED_HOSTS`: yeni kurulum ve yönetici ekranı (B12, kısmen).
