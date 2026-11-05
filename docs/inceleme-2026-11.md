# Teknik İnceleme — Kasım 2026

Bu belge kod tabanının bir defalık teknik incelemesidir; kalıcı kurallar `CLAUDE.md` dosyasındadır.
Maddeler giderildikçe bu belgede işaretlenebilir veya belge kaldırılabilir.

**İnceleme anındaki durum:** `uv run pytest` tamamı geçti, `ruff check` ve `ruff format --check` temiz,
GitHub Actions CI kurulu. İnceleme sırasında kodda değişiklik yapılmadı.

> Öncelik: 🔴 kritik (güvenlik/veri) · 🟠 teknik sağlamlık · 🟡 kullanıcı deneyimi

---

## 🔴 Kritik — güvenlik ve veri gizliliği

### 1. "Sorumlu bazlı" görünürlük modunda yetki açıkları (doğrulandı)

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

### 2. PIN deneme yoluyla kolayca bulunabilir

4 haneli PIN (10.000 olasılık), hatalı girişte bekleme/kilit yok ve giriş ekranı tüm aktif
kullanıcıları listeliyor. Ofis içinde bile bir kullanıcı yönetici PIN'ini kısa sürede deneyerek
bulup muhasebe, silme ve yedek indirme yetkisine erişebilir.

**Öneri:** Kullanıcı + IP bazında artan bekleme (ör. 5 hatalı denemeden sonra), başarısız girişlerin
aktivite kaydına yazılması, yönetici hesapları için daha uzun PIN/parola seçeneği.

### 3. Yedek güvenliği

- Arşivler parolasız.
- `BACKUP_DIR` varsayılanı kurulum klasörü içi (`apps/backups/services.py`); yedek ve canlı veri aynı
  diskte. Disk arızası veya fidye yazılımında ikisi birlikte kaybolur.
- `restore` geri yüklemeden önce mevcut veritabanının güvenlik yedeğini almıyor; yanlış dosya
  seçilirse geri dönüş yolu yok.

**Öneri:** Geri yükleme öncesi otomatik güvenlik yedeği, ikinci konuma (harici disk/NAS) kopya,
şifreli arşiv seçeneği, düzenli geri yükleme denemesi.

### 4. `DJANGO_ALLOWED_HOSTS=*`

`installer/scripts/postinstall.ps1` kurulumda `*` yazıyor. Sunucu adı ve IP adresleriyle
sınırlanmalı.

---

## 🟠 Teknik sağlamlık

### 5. Hata sayfaları ve HTMX hataları

- Özel 403/404/500 şablonu yok; üretimde Django'nun İngilizce varsayılan sayfası çıkıyor.
- `htmx:responseError` / `htmx:sendError` dinlenmiyor; HTMX isteği hata dönerse kullanıcı hiçbir
  geri bildirim görmüyor ("butona bastım, bir şey olmadı").

**Öneri:** Türkçe hata şablonları ve `base.html` içinde genel bir HTMX hata bildirimi (toast).

### 6. Haciz görev üretimi kullanıcı isteği içinde çalışıyor

`apps/cases/middleware.py` → `SeizureTaskMiddleware` dakikada bir, rastgele bir kullanıcının isteği
içinde `create_due_tasks()` çalıştırıyor ve hatayı yeniden fırlatıyor; kullanıcı ilgisiz bir sayfada
500 hatası görür. Yalnızca zamanlanmış görevde çalışmalı ya da hata yakalanıp loglanmalı.

### 7. Google Takvim eşitlemesi eşzamanlı

`apps/cases/views_hearings.py` içinde `sync_hearing_to_google` istek sırasında çağrılıyor. İnternet
yavaş/yokken duruşma kaydetmek yavaşlar. Başarısız eşitlemeler için yeniden deneme kuyruğu
görülmedi; zamanlanmış bir "eşitlenmemişleri tekrar dene" adımı değerlendirilmeli.

### 8. Yüklemelerde içerik denetimi yok

`apps/core/uploads.py` yalnızca uzantı ve boyuta bakıyor. `CLAUDE.md` §8 içerik uygunluğunu da
istiyor; en azından PDF/resim/Office türleri için dosya imzası (magic bytes) kontrolü eklenmeli.

### 9. Tekrarlanan kurulum dosyaları ve eski adlar

`installer/OzkurtHukuk.iss` ↔ `installer/HukukBurosu.iss`, `OzkurtHukukApp.xml` ↔ `HukukBuroApp.xml`
neredeyse aynı; zamanla ayrışma riski var. Veritabanı/kullanıcı adı `ozkurt` olarak CI'da ve
`restore` geliştirme yolunda sabit yazılı.

### 10. Küçük düzeltmeler

- `OfficeSettings.load()` her çağrıda `get_or_create` yapıyor; bir istekte birkaç kez çağrılıyor
  (middleware, context processor, yetki fonksiyonları). İstek başına önbellek yeterli.
- `apps/core/media.py` açıklaması ("herkes tüm kayıtları görür") restricted modla çelişiyor.
- Testler `staticfiles/` klasörü yok uyarısı üretiyor (CI'da `mkdir` ile geçiştirilmiş).

---

## 🟡 Kullanıcı deneyimi (kod okumasına dayalı)

- Hata geri bildirimi (madde 5) en çok hissedilecek eksik.
- Kısıtlı kullanıcı Raporlar'da tüm dosyaları görüyor (madde 1); "yetkim var" diye algılanır.
- Başarısız giriş denemeleri yöneticiye aktivite kaydında gösterilebilir.
- Geri yükleme yalnızca komut satırından; yöneticinin arayüzden (önce otomatik güvenlik yedeği
  alarak) başlatabileceği bir akış büro için daha pratik olur.

---

## Önerilen sıra

1. Madde 1 — görünürlük açıkları + uç bazında yetki testleri
2. Madde 2 — PIN deneme sınırı
3. Madde 5 ve 6 — Türkçe hata sayfaları, HTMX bildirimi, haciz kontrolünün istekten ayrılması
4. Madde 3 — yedek güvenliği
