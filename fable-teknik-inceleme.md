# Teknik İnceleme Raporu — Hukuk Bürosu Otomasyonu 1.2.2

İnceleme tarihi: 11 Kasım 2026. İncelenen commit: `cfbae52`.

Program sağlıklı durumda: tüm testler ve denetimler geçiyor, acil düzeltme gerektiren bir hata bulunmadı. Aşağıda dört küçük bulgu var; inceleme sırasında kodda değişiklik yapılmadı.

## Doğrulama sonuçları

| Kontrol | Sonuç |
|---|---|
| `uv run pytest` | 1078 geçti, 13 atlandı (hepsi yalnızca Windows'ta çalışan PowerShell testleri) |
| `node --test` (eklenti ve arayüz betikleri) | 70 geçti |
| `ruff check` / `ruff format --check` | Temiz |
| `makemigrations --check` | Eksik migration yok |
| `check --deploy` (üretim ayarları) | Sorun yok; dört HTTPS uyarısı LAN gerekçesiyle bilinçli susturulmuş |

Testler PostgreSQL 16 üzerinde çalıştırıldı (inceleme ortamında Docker yoktu); proje ve CI 17 kullanıyor.

## Bulgular

### 1. Silme uçları görünürlük süzgecini kullanmıyor

Dosya silme, yeniden açma, taraf çıkarma (`apps/cases/views.py:614`, `:664`, `:893`), duruşma silme (`apps/cases/views_hearings.py:290`) ve müvekkil silme (`apps/clients/views.py:521`) kaydı doğrudan `get_object_or_404` ile alıyor.

Hepsi yetki matrisiyle korunuyor ve varsayılanda yalnızca yöneticiye açık, bu yüzden bugün açık değil. Ancak matriste bu yetkilerden biri `cases.view_all` yetkisi olmayan bir role verilirse, o kişi göremediği kayıt üzerinde işlem yapabilir. Bu, `CLAUDE.md` Bölüm 8'deki kurala aykırı.

Öneri: beş uçta görünür kayıt kümesine geçmek ve `tests/test_visibility_endpoints.py`'ye birer test eklemek.

### 2. Kullanılmayan WhatsApp mesajlaşma modülü depoda duruyor

`apps/clients/messaging/` (yaklaşık 1.070 satır; resmî WhatsApp API'si, webhook, hatırlatmalar) hiçbir URL'ye bağlı değil ve `tests/test_retired_features.py` kapalı kaldığını sınıyor. Modelleri, şablonları ve `.env.example` içindeki `WHATSAPP_*` değişkenleri yerinde; `CLAUDE.md`'de hiç geçmiyor.

İleride yanlışlıkla bağlanırsa müvekkil görünürlüğü uygulamayan görünümler açılır (`apps/clients/messaging/views.py:93` vb.).

Öneri: ya silinmeli ya da "kaldırıldı, verisi korunuyor" diye belgelenmeli.

### 3. `uv.lock` eski sürümde kalmış

Kilit dosyası 1.2.1, `pyproject.toml` 1.2.2 diyor; her `uv run` dosyayı sessizce yeniden yazıyor.

Öneri: sürüm artırılırken `uv lock` çalıştırılmalı.

### 4. Django 6 uyarısı

`FORMS_URLFIELD_ASSUME_HTTPS` geçiş ayarı Django 6.0'da kaldırılacak; 5.2 LTS'te kalındıkça sorun değil.

## Bakılan ve sorun görülmeyen yerler

- **Eklenti uçları:** `csrf_exempt` olanlar yalnızca yerel istek kabul ediyor, anahtarı özetleyerek karşılaştırıyor ve gövde boyutunu sınırlıyor.
- **Riskli kalıplar:** `mark_safe` yalnızca kaçışlanmış değerle kullanılıyor; `shell=True`, `eval`, `pickle` veya şablonda `|safe` yok.
- **Yönlendirme:** Muhasebe iptalindeki `next` parametresi açık yönlendirmeye karşı denetleniyor.
- **Kod işaretleri:** TODO/FIXME yok; 20 geniş `except Exception` var, tek tek incelenmedi.

## Kapsam dışında kalanlar

- Arayüz bu incelemede tarayıcıda gözle kontrol edilmedi.
- Windows kurulumu, güncelleyici ve yedek/geri yükleme Linux ortamında denenemedi.
- Bağımlılıklar için güvenlik açığı taraması yapılmadı.
- Depo kopyası son 50 commit'le sınırlıydı; geçmişin tamamı incelenmedi.
- `CLAUDE.md` Bölüm 13'teki açık işler (PIN sayaçlarının kalıcı olmaması, şifresiz yedek, ilk kurulum yarışı, muhasebe görünürlüğü, rapor performansı) hâlâ geçerli; yeniden doğrulanmadı.

## Öncelik önerisi

Önce 1. bulgu düzeltilmeli; küçük bir iş. 2 ve 3 temizlik niteliğinde.
