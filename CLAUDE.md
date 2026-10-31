# Özkurt Hukuk — Büro Yönetim Sistemi

Bu dosya projenin tek bilgi kaynağıdır. Claude Code ve Codex aynı kuralları buradan okur (`AGENTS.md` buraya yönlendirir). Oturum başında okuyun, iş bitince güncelleyin. Değer değil, yalnızca env değişkeni **adları** yazılır.

## Amaç ve kapsam
Hukuk bürosu için görev, dosya, müvekkil ve muhasebe takibi. Ofis içi ağda 5-6 PC tarayıcıdan kullanır. Sunucu, ofisteki bir Windows PC'dir (mesai boyunca açık, akşam kapanır). İstemci PC'lere hiçbir şey kurulmaz.

Production'da git/Docker/geliştirici aracı yoktur: kurulum `Setup.exe` (Inno Setup) ile yapılır, uygulama Windows servisi olarak çalışır (WinSW + Waitress, ayrıca PostgreSQL servisi).

## Yığın
Python 3.13, Django 5.2 LTS, PostgreSQL 17, HTMX 2 + Alpine.js 3, Bootstrap 5.3. Tüm frontend kütüphaneleri `static/vendor/` altında repodadır; CDN kullanılmaz (internetsiz çalışmalı). Bağımlılık yönetimi `uv`.

## Komutlar (geliştirme)
```
docker compose -f docker-compose.dev.yml up -d   # dev PostgreSQL, host portu 5434
uv sync                                          # bağımlılıklar
uv run python manage.py migrate
uv run python manage.py setup_office_users --pin <PIN>   # ofis kullanıcıları (PIN repoya yazılmaz)
uv run python manage.py seed_dev                 # örnek müvekkil/dosya (kullanıcılar önceden olmalı)
uv run python manage.py runserver
uv run pytest                                    # testler (dev DB'de test_ veritabanı açar)
uv run ruff check . && uv run ruff format --check .
```
Dev ayarları `config/settings/dev.py`, varsayılan DB bağlantısı dev compose'daki DB'dir. 5433 portu bu makinede başka bir projede dolu olduğu için 5434 kullanılır.

## Env değişkenleri (production)
`DJANGO_SETTINGS_MODULE=config.settings.prod`, `DJANGO_SECRET_KEY`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, `MEDIA_ROOT`, `STATIC_ROOT`, `LOG_FILE`. Yedekleme aşamasında: `BACKUP_PASSWORD`. Şablon: `.env.example`.

## Mimari
- `config/settings/{base,dev,test,prod}.py`, `config/urls.py`.
- `apps/core`: ortak model (`TimeStampedModel`), validator'lar (TCKN, VKN, IBAN), Türkçe metin yardımcıları (`fold`, `tr_lower`), form mixin'i, template tag'leri (`tl` para formatı, `sort_link`, `query_with`), `seed_dev`.
- `apps/accounts`: özel `User` (rol: admin/lawyer/intern, unvan, giriş ekranı sırası, tema, sayfa boyutu). Giriş kilidi `django-axes` (5 hata, 15 dk).
- Giriş: kullanıcı adı/şifre yok. Giriş ekranında aktif kullanıcıların kartları listelenir, kullanıcı kartına tıklayıp PIN girer. PIN, Django parolası olarak hash'li saklanır (`set_password`); `PinValidator` 4-8 rakam ister. Kullanıcı PIN'ini menüden değiştirir (`/hesap/pin/`). Yönetici `/yonetim/` panelinden başkasının PIN'ini sıfırlayabilir.
- Ofis kullanıcıları `apps/accounts/management/commands/setup_office_users.py` içindeki listedir. Yeni kullanıcı eklemek için listeyi güncelleyip komutu çalıştırın; komut mevcut PIN'leri yalnızca `--reset-pin` ile değiştirir. Unvan ≠ rol: "Koordinatör Avukat" rolü `lawyer`, "Yönetici Avukat" rolü `admin`.
- `apps/office`: `OfficeSettings` (singleton, `OfficeSettings.load()`), `TaskType`, `Court` (merci listesi).
- `apps/clients`: `Client` (gerçek/tüzel), iletişim, IBAN, yetkili, vekalet (`PowerOfAttorney`), karşı taraf (`Party`), çıkar çatışması (`conflicts.py`).
- `apps/cases`: `Case` (8 tür, arşiv no unique, türe göre etiketler `TYPE_LABELS`), `CaseParty`, `Document`.
- Tüm kullanıcı view'ları `LoginRequiredMiddleware` ile korunur. `/media/` de giriş ister.
- Aktivite kaydı `django-auditlog`; her app `ready()` içinde kendi modellerini kaydeder.

## Arayüz
- Tasarım sistemi `static/css/app.css`: tokenlar `:root` ve `[data-bs-theme=dark]` altında (lacivert yan menü, bronz vurgu `--accent`, marka mavisi `--brand`). Font Inter, `static/vendor/inter/` altında gömülü.
- Bileşenler: `.page-header` (eyebrow/başlık/alt başlık/aksiyonlar), `.card.table-card` + `.filter-bar` + tablo + `partials/pagination.html` (`.table-footer`), `.detail-hero` + `.nav-underline-tabs`, form `.form-section` + `.form-footer`, durum rozeti `.chip` (`chip-primary/success/warning/danger/info/accent`), `.stat-card`, `.empty-state`, `.avatar` (`--h` = `User.avatar_hue`). Dosya durumu rozeti: `cases/_status_chip.html`.
- Bildirim mesajları sağ altta toast olarak çıkar. Tema düğmesi `accounts:theme_toggle` ile kullanıcı tercihine yazılır.
- Yeni sayfalar bu bileşenlerle yazılır; satır içi stil yerine token kullanılır.

## İş kuralları
- Her görev bir dosyaya, her dosya bir müvekkile bağlıdır. Görevde müvekkil dosyadan otomatik gelir.
- Her müvekkilin bir sorumlu avukatı (rol admin veya lawyer) ve bir sorumlu stajyeri (rol intern) vardır. Dosyada bunlar müvekkilden varsayılan gelir, değiştirilebilir.
- Herkes tüm kayıtları görür. Silme yalnızca yönetici. Belgeyi yükleyen veya yönetici siler. Muhasebe görme/girme yetkisi `OfficeSettings` içindeki rol bayraklarıyla yönetilir.
- Arşiv no elle girilir, büyük/küçük harf duyarsız unique; form son numarayı artırarak öneri sunar.
- Çıkar çatışması: müvekkil adı (aksansız) veya TCKN/VKN bir karşı tarafla eşleşirse uyarı çıkar; kayıt için onay kutusu gerekir. Tersi de geçerli.
- Tebligat son günü elle girilir (otomatik süre hesabı yok).
- Görev durumları: Bekliyor → Devam ediyor → Kontrolde → Tamamlandı; kontrolcü "Revizyon istendi" ile sorumluya döndürebilir; İptal ayrıdır.
- Muhasebe (TL, vergi yok): **Cari** = vekalet ücreti + masraf − tahsilat − mahsup. **Emanet** = karşı taraftan tahsilat − müvekkile ödeme − mahsup. **Net** = cari − emanet. Hareket silinmez, iptal edilir.

## Yol haritası
1. ✅ İskelet, giriş/roller, müvekkil, karşı taraf + çıkar çatışması, dosya, belgeler.
2. Görev + onay döngüsü, duruşma (ayrı kayıt), tebligat, dosya zaman çizelgesi, ana sayfa özeti, sistem içi bildirim.
3. Muhasebe: hareketler, cari/emanet, mahsup, yetki matrisi; müvekkil listesine bakiye, borçlu ve açık görev filtreleri.
4. Global arama (`unaccent` + `pg_trgm`, eklentiler `core/0001` migration'ında kurulu), aktivite ekranları, 6 rapor (Excel `openpyxl`, PDF `reportlab` + gömülü Noto Sans).
5. Ayarlar ekranları, yedek (`pg_dump` + media → AES ZIP → bulut senkron klasörü, 30 günlük + 12 aylık), Windows kurulum/güncelleme `.exe`.
6. Excel'den içe aktarım (ofisin mevcut dosyaları görüldükten sonra).

## Çalışma kuralları
- Kod/tanımlayıcı İngilizce; arayüz metni, yorum, commit mesajı Türkçe.
- Repoya gerçek müvekkil verisi, `.env`, `media/`, yedek dosyası girmez. Testlerde yalnızca uydurma veri.
- Model değişikliğinde migration üret ve commit'le. Yeni modeli auditlog'a kaydet.
- Yeni sayfa: liste filtreleri HTMX (`hx-get` + `_list_table.html` partial), satır içi alt kayıtlar HTMX partial ile.
- Her değişiklikten sonra `pytest` ve `ruff` çalıştır.
