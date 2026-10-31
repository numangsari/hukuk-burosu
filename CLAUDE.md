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
uv run ruff check .
uv run ruff format --check .
```
Dev ayarları `config/settings/dev.py`, varsayılan DB bağlantısı dev compose'daki DB'dir. 5433 portu bu makinede başka bir projede dolu olduğu için 5434 kullanılır.

## Env değişkenleri (production)
`DJANGO_SETTINGS_MODULE=config.settings.prod`, `DJANGO_SECRET_KEY`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, `MEDIA_ROOT`, `STATIC_ROOT`, `LOG_FILE`. `BACKUP_PASSWORD`, `BACKUP_DIR`, `PG_DUMP`, `PG_RESTORE`, `BACKUP_DATABASE_URL`. Şablon: `.env.example`.

## Mimari
- `config/settings/{base,dev,test,prod}.py`, `config/urls.py`.
- `apps/core`: ortak model (`TimeStampedModel`), validator'lar (TCKN, VKN, IBAN), Türkçe metin yardımcıları (`fold`, `tr_lower`), form mixin'i, template tag'leri (`tl` para formatı, `sort_link`, `query_with`), `seed_dev`.
- `apps/accounts`: özel `User` (rol: admin/lawyer/intern, unvan, giriş ekranı sırası, tema, sayfa boyutu). Giriş kilidi `django-axes` (5 hata, 15 dk).
- Giriş: kullanıcı adı/şifre yok. Giriş ekranında aktif kullanıcıların kartları listelenir, kullanıcı kartına tıklayıp PIN girer. PIN, Django parolası olarak hash'li saklanır (`set_password`); `PinValidator` tam 4 rakam ister; giriş ekranı 4. rakamda formu otomatik gönderir (Enter gerekmez). Kullanıcı PIN'ini Ayarlar > PIN değiştir'den değiştirir. Yönetici `/yonetim/` panelinden başkasının PIN'ini sıfırlayabilir.
- Ofis kullanıcıları `apps/accounts/management/commands/setup_office_users.py` içindeki listedir. Yeni kullanıcı eklemek için listeyi güncelleyip komutu çalıştırın; komut mevcut PIN'leri yalnızca `--reset-pin` ile değiştirir. Unvan ≠ rol: "Koordinatör Avukat" rolü `lawyer`, "Yönetici Avukat" rolü `admin`.
- `apps/office`: `OfficeSettings` (singleton, `OfficeSettings.load()`), `TaskType`, `Court` (merci listesi).
- `apps/clients`: `Client` (gerçek/tüzel), iletişim, IBAN, yetkili, vekalet (`PowerOfAttorney`), karşı taraf (`Party`), çıkar çatışması (`conflicts.py`).
- `apps/cases`: `Case` (8 tür, arşiv no unique, türe göre etiketler `TYPE_LABELS`), `CaseParty`, `Document`, `Hearing` (duruşma/keşif/bilirkişi; sonuç girilince zaman çizelgesine düşer), `Service` (tebligat; son gün elle, "gereği yapıldı" işareti), `CaseEvent` (zaman çizelgesi: elle not + otomatik kayıtlar). Duruşma/tebligat/not HTMX işlemleri `views_records.py`.
- `apps/tasks`: `Task` (tür, ad, dosya, müvekkil = dosyanın müvekkili, sorumlu, kontrolcü ≠ sorumlu, son gün, notlar), `TaskEvent` (geçmiş + yorumlar). Onay döngüsü ve yetkiler `services.py` (`ACTIONS`, `perform`, `available_actions`, `can_edit`). Görev formu müvekkile göre dosya süzer, dosya seçilince müvekkil ve varsayılan sorumlu (dosyanın stajyeri) / kontrolcü (dosyanın avukatı) dolar (`tasks:case_options`).
- `apps/accounting`: `LedgerEntry` (müvekkil, isteğe bağlı dosya — dosya seçilirse müvekkil dosyadan gelir; tür, tutar, tarih, açıklama, makbuz; iptal alanları). Bakiye ifadeleri `CARI_EXPR`/`TRUST_EXPR`, `LedgerEntry.objects.balances()` ve `totals_by_kind()`. Ekstre `views.statement()`. Müvekkile ödeme ve mahsup emanet bakiyesini aşamaz. Yetki `accounting/permissions.py` (`can_view`, `can_edit`; rol bayrakları `OfficeSettings.<rol>_can_view/edit_accounting`, Ayarlar > Muhasebe yetkileri). Görme yetkisi olmayan kullanıcı müvekkil listesindeki bakiye sütununu/filtresini, cari hesap ve dosya muhasebe sekmelerini görmez.
- Müvekkil listesi `annotate_list_values()`: dosya sayısı, açık görev sayısı, cari bakiye alt sorgularla; filtreler tip, vekalet, avukat, stajyer, açık görev, borçlu, aktiflik; tüm sayısal sütunlar sıralanır.
- Belgeler ve ofis klasörü: `TaskDocument` (görev belgesi, sürüm zinciri `previous`/`version`/`is_current`; açık görevde sorumlu, kontrolcü, yönetici yükler; yükleyen/yönetici siler, önceki sürüm güncel olur). `TaskType.requires_document` işaretli türde belge olmadan kontrole gönderilemez (Ayarlar > Görev türleri). Onayda `cases/documents.publish_task_documents()` güncel belgeleri dosyanın `Document` kayıtlarına kopyalar ve ofis klasörüne yazar (`<YYYY-MM-DD> <görev adı>.<uzantı>`). Dosya belgesi yüklemesi ve vekalet PDF'i de klasöre kopyalanır. Klasör mantığı `core/folders.py`: kök `OfficeSettings.documents_root` (Ayarlar > Belge klasörü, kaydederken yazma testi), yapı `<kök>\Müvekkiller\<Client.folder_name>\<Case.folder_name>` ve `<müvekkil>\Vekaletler`; klasör adı boşsa ad ile (aksansız, büyük/küçük harf duyarsız) mevcut klasör aranır, yoksa oluşturulur ve kaydedilir; adlar Windows'a göre temizlenir; üzerine yazılmaz, `(2)` eklenir. Asıl kopya MEDIA_ROOT'tadır; klasör hatası işlemi durdurmaz, uyarı mesajı verir. Klasör adı değiştirilirse eski klasör taşınmaz, yeni belgeler yeni ada gider.
- `apps/search`: global arama (üst çubuk canlı açılır liste + `/ara/` sonuç sayfası; Ctrl+K). Müvekkil/karşı taraf `search_key` (fold) ile, diğer alanlar `__unaccent__icontains` ile; müvekkilde sonuç yoksa `TrigramWordSimilarity` (> 0.45) ile yazım hatası toleransı. Muhasebe kayıtları aranmaz.
- `apps/activity`: auditlog kayıtlarının ekranı (`/aktivite/`; yönetici herkesi, diğerleri kendini görür; kullanıcı/tür/işlem/tarih filtresi). Giriş/çıkış `LogEntry.Action.ACCESS` olarak yazılır (`signals.py`). `User` değişiklikleri parola/son giriş/tema/liste boyutu hariç kaydedilir. Müvekkil ve dosya detayında "Geçmiş" sekmesi (`history_for`).
- `apps/reports`: 6 rapor (`definitions.REPORTS`: parametre formu + `build()` → `ReportResult`); önizleme HTML, `renderers.to_xlsx` (openpyxl) ve `to_pdf` (ReportLab, `reports/fonts/` altında gömülü DejaVu Sans — Türkçe karakter için). Finansal raporlar (`financial: True`) muhasebe görme yetkisi ister.
- `apps/backups`: `manage.py backup [--scheduled|--update]` = `pg_dump -Fc` + MEDIA_ROOT → AES-256 şifreli ZIP (`pyzipper`, parola `BACKUP_PASSWORD`) → `BACKUP_DIR`; ayrıca `OfficeSettings.backup_dir`'e (bulut senkron klasörü) kopya. Saklama: son 30 günün günlük + son 12 ayın ilk yedeği (`apply_retention`, yalnızca `ozkurt-yedek-*.zip` dosyalarına dokunur). Görev Zamanlayıcı 30 dakikada bir `backup --scheduled` çalıştırır; bugün başarılı yedek yoksa ve `backup_time` geçtiyse yedekler (PC o saatte kapalıysa açılınca alınır). `manage.py restore <zip> --yes` (servis durdurulmuşken; mevcut media `media.onceki-…` olarak saklanır). `BackupRecord` geçmişi Ayarlar > Yedekleme'de; yöneticiye 2 günden eski yedekte uyarı bandı. Dev ortamında pg_dump host'ta yok: `PG_DUMP="docker exec -i ozkurt-hukuk-db-1 pg_dump"`, `PG_RESTORE=...pg_restore`, `BACKUP_DATABASE_URL=postgresql://ozkurt:<dev parola>@localhost:5432/ozkurt`.
- Ayarlar > Kullanıcılar: yönetici kullanıcı ekler/düzenler/pasife alır, PIN sıfırlar (`UserAdminForm`; kullanıcı adı ad-soyaddan üretilir; kendi hesabını pasife alamaz/yöneticiliğini kaldıramaz).
- `apps/notifications`: `Notification` (zil). `notify()` kişinin kendi işlemi için bildirim üretmez; `key` ile tekrarı önler. `send_daily_reminders()` (son günü bugün/yarın/geçmiş açık görevler, yarınki duruşmalar) günde bir kez ilk sayfa açılışında context processor'dan tetiklenir (`run_daily_reminders_once`, önbellek anahtarı).
- Tüm kullanıcı view'ları `LoginRequiredMiddleware` ile korunur. `/media/` de giriş ister.
- Aktivite kaydı `django-auditlog`; her app `ready()` içinde kendi modellerini kaydeder.
- `apps/agenda`: takvim = Google Takvim (salt okunur) + sistemdeki planlı duruşmalar ve gereği yapılmamış tebligat son günleri (`combined_events`, `Event.source` google/hearing/deadline). Google kısmı: Yönetici Ayarlar > Google Takvim'e "iCal biçiminde gizli adres"i girer (`OfficeSettings.calendar_ics_url`, ekranda gösterilmez, repoya/log'a yazılmaz). `services.py` ICS'i çeker (5 dk önbellek, erişilemezse 1 güne kadar son kopya), `icalendar` + `recurring-ical-events` ile tekrar eden etkinlikleri açar. Ana sayfada önümüzdeki 7 gün, `/takvim/` sayfasında ay/hafta görünümü. Sunucunun internet erişimi gerekir.
- Ayarlar sayfası `/hesap/ayarlar/?bolum=profil|pin|ofis|takvim` (`accounts.views.SettingsView`); ofis ve takvim bölümleri yalnızca yönetici.

### Kayıt bütünlüğü
- Duruşma, tebligat, dosyadaki karşı taraf bağlantısı ve müvekkil alt kayıtlarını yalnızca yönetici silebilir; düğmeler de aynı kurala bağlıdır.
- Ekrandan muhasebe hareketi oluşturma/iptal işlemleri `apps/accounting/services.py` üzerinden yürür. Müvekkil satırı işlem boyunca kilitlenir; bakiye kayıttan hemen önce yeniden hesaplanır. Emaneti eksiye düşüren ödeme/mahsup ve tahsilat iptali reddedilir. Yeni para işlemleri bu yardımcıları kullanmalıdır; tamamlanmamış `apps/imports` bu kapsama henüz alınmamıştır.
- Bağlı görev veya muhasebe hareketi olan dosyanın müvekkili düzenleme formunda değiştirilemez. Dosya düzenleme ve ekrandan görev/para hareketi ekleme, aynı dosya kilidini kullanır.
- Görev ve belgeleri yalnızca `active` durumunda değiştirilebilir. Kontroldeki belge için önce revizyon istenir; onayda belge zorunluluğu yeniden denetlenir. Durum geçişleri ve belge değişiklikleri görev satırını kilitler; eski durumla gelen ikinci onay yeniden kayıt üretmez.
- Excel raporlarındaki bütün metinler açıkça metin hücresi olarak yazılır. Uyarı ve hata mesajları kullanıcı kapatana kadar görünür kalır; başarı mesajı kısa sürede kapanır.
- Yedek dosyalarını dışlayan kural yalnızca kökteki `/backups/` içindir; `apps/backups/` uygulama kodu ve şema dosyaları ortak proje kaydına dahildir.
- Geri yükleme önce belgeleri aynı diskte geçici klasöre hazırlar. Veritabanı `pg_restore --single-transaction --exit-on-error` ile yüklenir; hata halinde eski belge klasörü geri konur. Başarılı dönüşte eski belgeler `media.onceki-...` altında saklanır. Windows yardımcısı güvenlik yedeği veya servis durdurma başarısızsa başlamaz; geri yükleme hatasında uygulamayı kapalı tutar. Gerçek yedek ve kurulu Windows servisleriyle dönüş provası hâlâ gereklidir.

## Arayüz
- Tasarım sistemi `static/css/app.css`: tokenlar `:root` ve `[data-bs-theme=dark]` altında (lacivert yan menü, bronz vurgu `--accent`, marka mavisi `--brand`). Font Inter, `static/vendor/inter/` altında gömülü.
- Bileşenler: `.page-header` (eyebrow/başlık/alt başlık/aksiyonlar), `.card.table-card` + `.filter-bar` + tablo + `partials/pagination.html` (`.table-footer`), `.detail-hero` + `.nav-underline-tabs`, form `.form-section` + `.form-footer`, durum rozeti `.chip` (`chip-primary/success/warning/danger/info/accent`), `.stat-card`, `.empty-state`, `.avatar` (`--h` = `User.avatar_hue`). Dosya durumu rozeti: `cases/_status_chip.html`.
- Yan menü: üstte ofis adı, altında kullanıcı bloğu (tıklayınca Ayarlar / Çıkış yap). Ana sayfa: yalnızca selamlama başlığı; solda "Aktif görevlerim" (sorumlu olduğu açık görevler + kontrolünü bekleyenler, son güne göre, gecikmiş üstte), sağda 4 hızlı işlem (Yeni görev, Yeni dosya, Yeni müvekkil, Yeni gelir/gider — muhasebe gelene kadar pasif) ve "Yaklaşan tarihler" (süresi geçmiş tebligatlar + 7 gün).
- Bildirim mesajları sağ altta toast olarak çıkar. Tema düğmesi `accounts:theme_toggle` ile kullanıcı tercihine yazılır.
- Yeni sayfalar bu bileşenlerle yazılır; satır içi stil yerine token kullanılır.

## Kurulum (production)
- `installer/build.ps1` → gömülü Python 3.13 + PostgreSQL 17 binary + WinSW + uygulama → Inno Setup ile `installer/dist/OzkurtHukuk-Kurulum-<sürüm>.exe`.
- `installer/scripts/postinstall.ps1` (tekrar çalıştırılabilir): `.env` (yalnızca ilk kurulum; SECRET_KEY, DB ve yedek parolası rastgele), initdb (ICU tr-TR, yalnızca 127.0.0.1), servisler `OzkurtHukukDB` + `OzkurtHukukApp` (Waitress :80), migrate/collectstatic/setup_office_users, güvenlik duvarı (Özel ağ), "Ozkurt Hukuk Yedek" zamanlanmış görevi, istemci `.url` kısayolu, sağlık kontrolü. Güncellemede Inno `PrepareToInstall` önce `backup --update` alır ve servisi durdurur.
- Production'da `manage.py` her zaman `tools\manage.cmd` ile çalışır (DJANGO_SETTINGS_MODULE=prod).
- Vendored JS/CSS dosyalarına `sourceMappingURL` satırı bırakmayın: `CompressedManifestStaticFilesStorage` eksik `.map` dosyası yüzünden collectstatic'i durdurur.

## İş kuralları
- Her görev bir dosyaya, her dosya bir müvekkile bağlıdır. Görevde müvekkil dosyadan otomatik gelir.
- Her müvekkilin bir sorumlu avukatı (rol admin veya lawyer) ve bir sorumlu stajyeri (rol intern) vardır. Dosyada bunlar müvekkilden varsayılan gelir, değiştirilebilir.
- Herkes tüm kayıtları görür. Silme yalnızca yönetici. Belgeyi yükleyen veya yönetici siler. Muhasebe görme/girme yetkisi `OfficeSettings` içindeki rol bayraklarıyla yönetilir.
- Arşiv no elle girilir, büyük/küçük harf duyarsız unique; form son numarayı artırarak öneri sunar.
- Çıkar çatışması: müvekkil adı (aksansız) veya TCKN/VKN bir karşı tarafla eşleşirse uyarı çıkar; kayıt için onay kutusu gerekir. Tersi de geçerli.
- Tebligat son günü elle girilir (otomatik süre hesabı yok).
- Görev durumları yalnızca üç: Aktif → Kontrolde → Tamamlandı ("işe başla" ve "iptal" yok). Kontrolcü revizyon isterse (açıklama zorunlu) görev Aktif'e döner ve `revision_requested` işareti alır; sorumlu tekrar kontrole gönderince kalkar. Tamamlanan görev yeniden açılabilir (oluşturan/kontrolcü). Sorumlu: kontrole gönder. Kontrolcü: onayla/revizyon. Yanlış açılan görevi oluşturan veya yönetici siler. Yönetici: hepsi. Onaylanan görev dosya zaman çizelgesine düşer.
- Muhasebe (TL, vergi yok): **Cari** = vekalet ücreti + masraf − tahsilat − mahsup. **Emanet** = karşı taraftan tahsilat − müvekkile ödeme − mahsup. **Net** = cari − emanet. Hareket silinmez, iptal edilir.

## Yol haritası
1. ✅ İskelet, giriş/roller, müvekkil, karşı taraf + çıkar çatışması, dosya, belgeler.
2. ✅ Görev + onay döngüsü, duruşma (ayrı kayıt), tebligat, dosya zaman çizelgesi, ana sayfa özeti, sistem içi bildirim, Google Takvim.
3. ✅ Muhasebe: hareketler, cari/emanet, mahsup, yetki matrisi; müvekkil listesine bakiye, borçlu ve açık görev filtreleri.
3b. ✅ Görev belgeleri ve ofis klasörü (aşağıdaki "Belgeler ve ofis klasörü" maddesi).
4. ✅ Global arama, aktivite ekranları, 6 rapor (Excel + PDF).
5. ✅ Ayarlar ekranları (kullanıcılar, yedekleme), şifreli yedek/geri yükleme, Windows kurulum betikleri (`installer/`, ayrıntı `installer/README.md`). `Setup.exe` derlemesi Inno Setup 6 ister; henüz derlenip temiz Windows'ta denenmedi.
6. Excel'den içe aktarım (ofisin mevcut dosyaları görüldükten sonra).

## Çalışma kuralları
- Kod/tanımlayıcı İngilizce; arayüz metni, yorum, commit mesajı Türkçe.
- Repoya gerçek müvekkil verisi, `.env`, `media/`, yedek dosyası girmez. Testlerde yalnızca uydurma veri.
- Model değişikliğinde migration üret ve commit'le. Yeni modeli auditlog'a kaydet.
- Yeni sayfa: liste filtreleri HTMX (`hx-get` + `_list_table.html` partial), satır içi alt kayıtlar HTMX partial ile.
- Her değişiklikten sonra `pytest` ve `ruff` çalıştır.
- Eşzamanlı işlem denemeleri `tests/test_report_concurrency.py` içindedir; gerçek PostgreSQL bağlantıları kullanır, kurulumla gelen başlangıç kayıtlarını denemelerden sonra geri koyar. Windows'ta geçici test klasöründe erişim reddi olursa denemeler için ek erişim gerekir.
