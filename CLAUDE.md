# Hukuk Büro Yönetim Sistemi — Geliştirici & Mimari El Kitabı

Bu dosya projenin **mimari ve geliştirme kuralları için** tek bilgi kaynağıdır (`Single Source of Truth`). Geliştirici ajanlar ve katkıda bulunanlar kuralları buradan okur (`AGENTS.md` buraya yönlendirir). Oturum başında okuyun; mimari, iş kuralı, entegrasyon veya çalışma komutu değiştiğinde güncelleyin. Küçük ve mevcut kuralları etkilemeyen düzenlemelerde gereksiz dokümantasyon değişikliği yapmayın. Gizli değerler, gerçek kullanıcı/müvekkil verileri ve tokenlar yazılmaz; gerekiyorsa yalnızca ortam değişkeni adları belirtilir.

> **Belge statüsü:** 1–4. bölümler mevcut sistemin dokümante edilmiş davranışlarını anlatır. 5–12. bölümler geliştirme ajanları için **uygulanacak kurallardır**; yeni kuralların yazılması ilgili güvenlik/teknik özelliğin kodda zaten uygulandığı anlamına gelmez. Davranıştan emin olunmadığında kod ve testlerle doğrulayın.

---

## 1. Amaç ve Kapsam

Hukuk büroları için dava/icra takibi, müvekkil portföyü, görev/onay iş akışları, duruşma ve ajanda takibi, fiziki arşiv envanteri, UYAP/UETS otomasyonu ve cari hesap/kasa yönetimini tek merkezde toplayan bir ofis yönetim platformudur.

- **Çalışma Ortamı:** Ofis içi yerel ağda (LAN) 5–15 kullanıcının tarayıcı üzerinden eriştiği yerel Windows sunucu.
- **İnternetsiz Çalışabilirlik:** CDN veya harici bulut bağımlılığı yoktur. Tüm kütüphaneler (`static/vendor/`) repoda yereldir.
- **Production Dağıtımı:** Git/Docker gerektirmez. Inno Setup ile derlenen `Setup.exe` ile kurulur; arka planda WinSW servisleri (`HukukBuroApp` ve `HukukBuroDB`) ile Waitress WSGI sunucusu üzerinden port 80'de çalışır.

---

## 2. Teknoloji Yığını ve Geliştirme Komutları

### Yığın
- **Backend:** Python 3.13, Django 5.2 LTS
- **Veritabanı:** PostgreSQL 17 (Geliştirmede host portu 5434, Docker ile)
- **Frontend:** HTMX 2, Alpine.js 3, Bootstrap 5.3, WhiteNoise
- **Paket Yöneticisi:** `uv`

### Geliştirme Komutları
```bash
docker compose -f docker-compose.dev.yml up -d       # Dev PostgreSQL (port 5434)
uv sync                                              # Bağımlılıkları yükle
uv run python manage.py migrate                      # Şemayı uygula
uv run python manage.py setup_office_users --pin <PIN> # Standart ofis kullanıcıları
uv run python manage.py seed_dev                     # Küçük örnek kayıtlar
uv run python manage.py seed_demo                    # Kapsamlı deneme verisi (DEBUG)
uv run python manage.py runserver 0.0.0.0:8000       # Geliştirme sunucusu
uv run pytest                                        # Test süiti (dev DB'de test_ veritabanı)
node --test tests/*.js tests/js/*.cjs              # UYAP/UETS eklentisi ve arayüz betiği testleri (Node)
uv run ruff check .                                  # Linter denetimi
uv run ruff format --check .                         # Format denetimi
```

---

## 3. Mimari ve Modül Yapısı

**Görsel proje haritası:** `docs/obsidian/` klasörü Obsidian'da ayrı kasa olarak açılır; `Proje Haritası.canvas` ana ilişkileri, bağlantılı notlar grafik görünümünü sağlar. Obsidian kurmadan `docs/proje-haritasi.html` tarayıcıda açılabilir; dış bağlantı gerektirmez. Harita koddan otomatik üretilmez; ilgili yapı değiştiğinde notlar, çizim ve tarayıcı görünümü birlikte güncellenir. İş kurallarının asıl kaynağı bu belge ve koddur.

### `apps/core`
- Ortak model altyapısı (`TimeStampedModel`), TCKN / VKN / IBAN doğrulayıcıları.
- Türkçe metin yardımcıları (`fold`, `tr_lower`, `tr_upper`, `tr_capitalize_words`).
- Genel arayüz template tag'leri (`tl` para formatı, `sort_link`, `query_with`).
- Dinamik sayfalama altyapısı (`pagination.py`).
- Arayüz tasarım yönü "sade ve yoğun profesyonel": yumuşak mavi-gri zemin, tek vurgu lacivert `#1F3A63`, 12 px kart / 8 px kontrol köşesi, hafif gölge (`static/css/app.css` sonundaki "Yumuşak görünüm" bloğu; koyu temada aynı köşe, koyu gölge), sayfa başlıklarında serif (Source Serif 4, `static/vendor/source-serif/`), tabloda `tabular-nums` ve sıkı satır. Uzun hücre içeriği `.clip` / `.clip-inline` sınıfıyla tek satırda "…" ile kısalır. Dar ekranda (tarayıcı yakınlaştırması dahil) liste tabloları yana taşmasın diye: `.clip` en çok görünüm genişliğinin %20'si kadardır; az önemli sütunlar `hide-md` (<1400 px), `hide-lg` (<1800 px), `hide-xl` (<2100 px) sınıflarıyla gizlenir (görev, dosya ve duruşma listelerinde uygulandı); 1600 px altında yan menü simge şeridine iner (ad, üzerine gelince `title` ile görünür). Yeni liste tabloları aynı sınıfları kullanmalı. Kayıt incelemesi ve oluşturma pop-up (modal) ile yapılır; yan inceleme paneli kullanılmaz.
- **Modül özet satırı:** Modül ana sayfalarının başlığında salt okunur sayı şeridi (`{% module_strip "anahtar" %}`, `apps/core/module_stats.py`). Sayılar büro geneli ve rolden bağımsızdır, parasal tutar içermez, 60 sn önbelleğe alınır; yeni modülde `BUILDERS`'a eklenir.
- Türkçe hata sayfaları (`templates/400|403|403_csrf|404|500.html`) ve HTMX hata bildirimi (`static/js/htmx-errors.js`, başarısız HTMX isteğinde toast gösterir).
- WhatsApp Click-to-Chat altyapısı (`whatsapp.py`): Uluslararası numara standardizasyonu (`clean_phone_for_whatsapp`), wa.me bağlantı üretici (`build_whatsapp_url`), duruşma/dosya mesaj şablonları ve evrensel düzenleme modalı (`whatsapp_modal.html`).

### `apps/accounts`
- **Özel Kullanıcı Modeli (`User`):** 7 rol desteklenir:
  - `admin`: Yönetici Avukat (Tam sistem yetkisi)
  - `senior`: Kıdemli Avukat
  - `lawyer`: Avukat
  - `intern`: Stajyer Avukat
  - `paralegal`: İcra Katibi / Takip Memuru
  - `secretary`: Sekreter / Büro Yönetimi
  - `accountant`: Muhasebe / Finans
- **Oturum Açma:** Kullanıcı adı/şifre yerine kullanıcı kartı seçilerek 4 haneli PIN ile hızlı giriş; 4. rakam girildiğinde form otomatik gönderilir. Hatalı denemeler `apps/accounts/throttle.py` ile yavaşlatılır (kullanıcı+IP için 5, IP için 20, kullanıcı için 40 hatalı denemeden sonra 30 sn'den başlayıp ikiye katlanan, en çok 15 dk bekleme; beklerken doğru PIN bile denenmez, HTTP 429). Sayaçlar önbellekte tutulur, servis yeniden başlayınca sıfırlanır. Hatalı PIN denemeleri aktivite kaydına "hatalı PIN" olarak yazılır.
- **İlk Kurulum Sihirbazı (`InitialSetupView`, `/hesap/ilk-kurulum/`):** Temiz kurulumda hiç kullanıcı yoksa ilk açılışta büro adı, çalışma modeli ve ilk yönetici hesabını tek adımda oluşturan ekran. Pasif kullanıcılar da kurulu sistem sayılır; bütün hesapların pasifleşmesi anonim yönetici oluşturma yolunu yeniden açmaz. Hesap kurtarma sunucu yöneticisi tarafından yapılır.
- **Oturum Güvenliği:** `OfficeSettings.idle_minutes` süresince işlem yapılmazsa oturum otomatik kapanır (`?zaman_asimi=1`). `NoStoreMiddleware` ile tarayıcı bellekten geri gitmelerinde veri sızıntısı engellenir.

### `apps/office`
- **`OfficeSettings`:** Büro adı, logosu, iletişim bilgileri, doküman kök klasörü (`documents_root`), oturum zaman aşımı ve modüler ofis çalışma kuralları:
  - `use_assistant_assignee`: Dosya ve müvekkillerde yardımcı sorumlu (stajyer/katip) kullanımını açıp kapatır.
  - `role_permissions`: **Rol × yetki matrisi** (Ayarlar > Yetkiler ve çalışma düzeni; yalnızca yönetici). Tek liste: solda yetkiler, üstte roller, işaretli rol yetkilidir; yönetici her yetkide kilitli ve hep yetkilidir. Kayıt defteri `apps/core/permission_registry.py` (`has_perm(user, anahtar)`, `role_has_perm(rol, anahtar)`); kaydı olmayan yetki için varsayılan roller geçerlidir. Yetkiler: `cases.view_all` (tüm dosya/müvekkilleri görme; işaretsiz roller yalnızca sorumlu/görevli olduğu kayıtları görür), `cases.reopen`, `cases.remove_party`, `cases.delete`, `clients.delete`, `tasks.close_without_review` (sorumlunun rolü işaretliyse kontrolcü zorunlu değil, doğrudan kapanır), `tasks.edit_any`, `tasks.delete_any`, `tasks.routines`, `notices.create_task`, `notices.no_task`, `hearings.delete`, `accounting.edit`, `accounting.cancel` (hareket iptali; varsayılan yönetici + dosya/müvekkil sorumlusu ve yardımcısı, `Permission.default_relations`), `accounting.balances`, `accounting.exclude_portal` (UYAP kaynaklı hareketi hesap dışı bırakma; varsayılan yönetici + kıdemli), `petition_pool.delete_any`. Yeni yetki eklemek için kayıt defterine satır ekleyip ilgili görünümde `has_perm` veya `PermissionRequiredMixin` kullanın. Dosya/müvekkil/muhasebe yetkileri `scoped=True`'dur: matriste rolün yanında "Sorumlu" ve "Yardımcı sorumlu" sütunları da işaretlenebilir (`role_permissions` listesinde `responsible`/`assistant`); rolü yetkisiz olsa bile kişi yalnızca sorumlu/yardımcı olduğu dosya veya müvekkilde yetkiyi kullanır. Bunun için `has_perm(user, anahtar, nesne)` (nesne: dosya, müvekkil veya hareket), `PermissionRequiredMixin.permission_object()`, şablonda `{% perm "anahtar" nesne as ok %}` kullanılır. Eski üç mod alanı (`case_visibility_mode`, `task_review_mode`, `accounting_edit_mode`) ve kişiye özel bayraklar (`User.can_view_*`, `can_manage_accounting`) yalnızca ilk geçişte matrise taşındı; artık kullanılmaz.
  - `notice_default_due_days`: UETS tebligatları için varsayılan ek süre (varsayılan: 14 gün).
  - `bank_details`: Ofis banka bilgileri (serbest metin). Doluysa müvekkil ve dosya WhatsApp şablonlarına "Banka Bilgileri" mesajı eklenir, masraf/avans mesajları hesap bilgisini içerir.
  - `use_task_points`: Personel görev puanı sistemini açıp kapatır.
  - `allowed_hosts`: Sunucuya girilebilecek ek bilgisayar adı/IP listesi (Ayarlar > Erişim adresleri, yalnızca yönetici). `config/hosts.py` içindeki `DynamicAllowedHosts`, `DJANGO_ALLOWED_HOSTS` sabit listesine bu adresleri ve her zaman `localhost`/`127.0.0.1` adreslerini ekler (15 sn önbellek; servis yeniden başlatmak gerekmez). Yeni kurulumda `postinstall.ps1` sabit listeyi bilgisayar adı (Türkçe karakterler punycode) ve IPv4'lerle yazar; eski kurulumlardaki `*` korunur, ekranda uyarı gösterilir ve liste ancak `.env` daraltılınca etkili olur.
- **`TaskType`:** Kategorize edilmiş görev türleri, varsayılan puanları, belge zorunluluğu (`requires_document`) ve gelir/gider zorunluluğu (`requires_accounting`) bayrakları. Yöneticiler Ayarlar > Görev türleri ekranından yeni türler ekleyebilir, mevcutları silebilir veya ayarlarını düzenleyebilir.
- **`Court`:** Yargı merci listesi.

### `apps/clients`
- **`Client`:** Gerçek veya tüzel kişi müvekkil kartı.
- **Alt Kayıtlar (`OptionalRowMixin`):** İletişim bilgileri, IBAN satırları, şirket yetkilileri, vekaletnameler (`PowerOfAttorney`) ve avukatlık sözleşmeleri (`RetainerAgreement`).
- **Vekalet No (`Client.poa_no`):** Fiziki vekalet klasöründeki sıra numarası (Örn: `V-121`). Sıradaki numara otomatik kilitli sayaçla atanır.

### `apps/cases`
- **`Case`:** 9 temel dosya türü:
  - `lawsuit` (Hukuk Dava), `criminal` (Ceza), `enforcement` (İcra), `administrative` (İdari Yargı), `investigation` (Soruşturma), `mediation` (Arabuluculuk), `notice` (İhtarname), `bankruptcy` (Satış Memurluğu), `consultancy` (Danışmanlık/Sözleşme/Diğer).
- **Numara Biçimleri:** Yıl ve pozitif sıra numarası (`2026/151`). Hukuk, Ceza ve İdarede `Esas`, `D.İş` veya `Talimat` seçimi. İhtarnamede noter tarihi ve yevmiye no.
- **Safahat (`CaseFlow`):** Aynı hukuki sürece ait dosyaları zincir akış olarak bağlama. Bağlı dosyalar ortak cari bakiyeyi ve safahat listesini paylaşır.
- **Dosya Durumu & Kapanış:** Açık (`active`) veya Kapalı (`closed`). Türe özel aşamalar (`stages.py`). İcra dosyası kapatılırken isteğe bağlı tahsilat satırları girilerek otomatik muhasebe emanet tahsilatı yazılır.
- **Haciz Takibi (`Seizure`):** Maaş, banka, araç, tapu, alacaklı olunan dosya, adres haczi ve 89/1-2-3 hacizleri. Süresi gelen hacizler için `create_seizure_tasks` komutu otomatik haciz yenileme görevi üretir.
- **Taraflar sekmesi:** İki sütun: solda büronun girdikleri (müvekkil + elle eklenen taraf, sıfat + isim alt alta), sağda UYAP/eklentiden gelen salt okunur liste (`summary.party_columns`). Taraflar karşılıklı yan yana değil, liste olarak sıralanır.

### `apps/agenda` & Duruşma Yönetimi
- **Birleşik Takvim (`/takvim/`):**
  - Ay Görünümü (`view=month`): Duruşmalar, müvekkil randevuları ve salt okunur Google Takvim etkinlikleri takvim ızgarasında; görevler gösterilmez.
  - Hafta Görünümü (`view=week`): Saatlik ve günlük ajanda.
  - Liste / Duruşma Görünümü (`view=list`; modül adı Takvim / Duruşma): Yaklaşanlar (bugün dahil), Geçmiş ve Tümü sekmeleri; başlangıç/bitiş tarihi ve hızlı filtreler (Bugün, Bu hafta, Gelecek hafta, Bu ay), sorumlu/tür/katılma filtresi ve Excel dökümü. Listede yalnızca duruşma, ön inceleme ve keşif görünür; diğer türler (toplantı, görüşme, bilirkişi vb.) takvimde etkinlik olarak kalır.
- **`Hearing` Modeli:** Hem dava duruşmalarını hem de dosyasız müvekkil randevularını, arabuluculuk oturumlarını ve ofis toplantılarını destekler (`case=None`, `client`, `title`, `assigned_to`, `ends_at`).
- **Duruşmalar UYAP'tan otomatik gelir:** Duruşma, ön inceleme ve keşif elle eklenmez; yalnızca `hearings.create_manual` yetkisi (varsayılan yönetici) UYAP kesintisi gibi durumlar için elle ekler. "Yeni kayıt > Etkinlik" ile herkes toplantı, müvekkil görüşmesi, bilirkişi, arabuluculuk ve diğer etkinlikleri ekler. UYAP kaydının (`portal_ref` dolu) tarih, saat, mahkeme, dosya ve türü kilitlidir; UYAP'ta saat değişirse kayıt izler, iptal edilirse "iptal" olur. Elle girilmiş duruşma sonradan aynı dosya ve saatte UYAP'tan gelirse birleşir. Kullanıcı yalnızca sorumlu avukat, katılma durumu, not, sonuç ve bilgilendirmeyi girer.
- **Duruşma modülü (görevlerden ayrıdır):** Duruşma listesi takvimin Liste görünümüdür (`hearing_list.py`; `/durusmalar/` oraya yönlenir). Sütunlar: tarih/saat, tür, mahkeme/esas, dosya/müvekkil, sorumlu avukat, katılma durumu (Katılınacak / E-duruşma / Mazeret; `Hearing.attendance`, `is_remote` ve `excuse_submitted` işaretlerinin tek seçimi), işlemler. Sekmeler: Yaklaşanlar, Geçmiş, Tümü. Salon bilgisi sistemden kaldırıldı. Listede gelecek duruşmada "Düzenle" doğrudan düzenleme penceresini açar (ara pencere yok); yapılmış duruşmada "İşlemler" penceresi açılır. Sekmelerde eksik bilgisi olan duruşma sayısı uyarı rozetiyle görünür.
  - **Gün kuralı:** İçinde bulunulan gün ve öncesi yapılmış sayılır, saatten bağımsız (`Hearing.is_done`). Yarın ve sonrası için pencerede yalnızca bilgi ve "Düzenle" (tür, tarih/saat, dosya, müvekkil, sorumlu avukat, katılma durumu) vardır; sorumlu avukat dosyadan otomatik gelmez, seçilir (yönetici, kıdemli, avukat, stajyer). Mahkeme ve esas dosyadan gösterilir.
  - **Yapılmış duruşma penceresi:** (1) sonuç: verilen karar zorunlu, sonraki duruşma tarihi isteğe bağlı (girilirse aynı dosyada duruşma açılır; UYAP'tan da gelir), (2) müvekkil bilgilendirme: karar ve sonraki tarihle hazırlanan WhatsApp mesajı; WhatsApp'ta Aç denince bilgilendirildi işaretlenir (`client_informed_at/by`, `inform_method`), telefonla/yüz yüze için "Başka yolla bildirildi", (3) görev oluştur: normal görev penceresi dosya, müvekkil ve dosya sorumlusuyla dolu açılır (`?dosya=&durusma=`), görev duruşmaya bağlanır.
  - **Uyarı:** Duruşma, ön inceleme ve keşifte yapılmış duruşmada sonuç veya müvekkil bilgilendirme eksikse listede ve dosya sekmesinde kısa "Eksik: sonuç, bilgilendirme" uyarısı çıkar (`result_missing`, `inform_missing`). Etkinliklerde (toplantı, görüşme vb.) aranmaz.
  - **Yetki:** Duruşmayı görebilen herkes düzenleyebilir, sonuç girebilir, bilgilendirebilir ve görev açabilir. Silme yalnızca yönetici.
  - **Kaldırıldı:** Duruşmadan 1 gün önce otomatik görev üretimi, görev kapatırken duruşma sonucu/müvekkil bilgilendirme formu ve duruşma listesindeki "Görev oluştur" penceresi. Eski duruşma görevleri (`Task.hearing`) normal görev olarak kalır. Duruşma görev türü genel görev türü seçimlerinde gösterilmez.
- **Google Takvim API Tek Yönlü Entegrasyon (`google_sync.py`):**
  - Katılma durumu (e-duruşma, mazeret) duruşma listesinde ve Google Takvim başlığında gösterilir.
  - Ayarlar sayfasında iki bağımsız bölüm: 1) Salt okunur iCal okuma adresi (`calendar_ics_url`), 2) Google Calendar API eşitleme ayarları (`google_calendar_api_enabled`, `google_calendar_id`, `google_service_account_json`).
  - Ayarlar arayüzünde canlı API bağlantı testi (`/takvim/google-test/`, `test_google_calendar_connection`) ve tüm duruşmaları toplu eşitleme desteği.
  - Sistemdeki duruşma ve toplantılar ofis Google Takvimi'ne tek yönlü aktarılır ve güncellenir. Başlık formatı: `[Keşif] Sorumlu Adı - Mahkeme Esas No (Müvekkil)` (Duruşma ve Ön İncelemede önek yoktur; Keşifte `[Keşif] ` öneki konur. Sorumlu kişinin soyadı yazılmaz yalnızca adı yazılır ve köşeli parantez kullanılmaz; mazeret sunulmuşsa `Mazeret - ...` olarak aktarılır). Konum alanı sadeleştirme amacıyla Google Takvim'e gönderilmez.
  - Renk desteği: Etkinlik türüne göre ayarlanabilir Google Takvim renk seçimi (`google_color_hearing`: Duruşma/Ön İnceleme - varsayılan Mavi 9, `google_color_discovery`: Keşif - varsayılan Yeşil 2, `google_color_meeting`: Müvekkil Görüşmesi/Toplantı - varsayılan Sarı 5, `google_color_mediation`: Arabuluculuk - varsayılan Kırmızı 11, `google_color_other`: Bilirkişi/Diğer - varsayılan Gri 8).
  - Google Takvim'deki mevcut veya harici etkinliklere kesinlikle dokunulmaz; mükerrer kayıt `google_event_id` ile engellenir.
  - Eşitleme istekten ayrıdır (`queue_hearing_google_sync`): kayıt `google_sync_pending` ile işaretlenir, Google çağrısı işlem tamamlanınca yardımcı iş parçacığında yapılır (`GOOGLE_SYNC_BACKGROUND`, varsayılan açık, testlerde kapalı). `retry_google_sync` iki dakikadan yeni değişen kayıtlara dokunmaz (aynı duruşmaya ikinci etkinlik açılmasın).
  - API açıkken başarısız eşitleme (ağ hatası, servis başlatılamaması; iptalde 404/410 dışındaki Google hataları) duruşma kaydını bozmaz; duruşma `google_sync_pending` ile işaretlenir ve `uv run python manage.py retry_google_sync` (kurulumda `check-reminders.ps1` ile beş dakikada bir) yeniden dener. Başarıda işaret kalkar; iptal edilen duruşmanın silinemeyen etkinlik kimliği yeniden deneme için korunur.
  - Google etkinlikleri varsa iCal adresinden, yoksa etkin API bağlantısından salt okunur alınır. Sistemin gönderdiği etkinlikler kimlikleriyle ayrılarak takvimde ikinci kez gösterilmez; dosya ve müvekkil görünürlük yetkileri uygulanır.
  - Takvimdeki duruşmalar ve Duruşma Listesi'ndeki tarih bağlantısı duruşma penceresini (`/durusmalar/<id>/`) açar; oluşturan, yönetici ve kıdemli avukat aynı pencerede düzenler. Google ve randevu etkinlikleri salt okunur bilgi penceresinde gösterilir; duruşma görevleri Duruşma Listesi'nden yönetilir.
- **Arayüz & Navigasyon:** Sol menüdeki "Sistem" menü grubu sadeleştirme amacıyla kaldırılmış; Sistem monitörü, UYAP/UETS inceleme, Aktivite kaydı, Veri aktarımı ve Django yönetim paneli bağlantıları Ayarlar > Sistem bölümüne taşınmıştır (Ayarlar iç menüsü: Hesabım, Ofis, Sistem). Dava/dosya numara girişi tek satırda kompakt ve estetik olarak hizalanmıştır.

### Fiziki Arşiv Modülü (`/arsiv/`)
- **Klasör Türleri & Dinamik Kategoriler (`ArchiveCategory`):** Standart türler (Dava, İcra, İhtarname, Arabuluculuk, Sözleşme, Vekaletname, Avukatlık Ücret Sözleşmesi, Soruşturma, Satış Memurluğu, Diğer) ile serbest yeni klasör türü (`ArchiveCategoryForm`, `/arsiv/tur-yeni/`) oluşturulabilir.
- **Açık / Kapalı Durum Takibi (`tracks_state`):** Dava, İcra vb. dosyalarda açık/kapalı ayrımı yapılır (`physical_state`: `open`, `closed`); İhtarname ve Arabuluculuk gibi süreçlerde tek durum (`single`) kullanılır.
- **Müvekkile Özel Klasörler (`Client.physical_archive_enabled`):** Müvekkil kartından özel fiziki klasör kullanımı ve açık/kapalı tercihi açılabilir. Müvekkile ait özel kategori ve ilk klasörler otomatik üretilir (`sync_client_archive`). Dava formunda müvekkil seçildiğinde klasör seçenekleri o müvekkile özel ve genel klasörlerle dinamik filtrelenir; başka müvekkilin özel klasörüne yerleşim engellenir.
- **Otomatik Klasör Numaralandırma (`next_folder_number`):** Yeni klasör oluşturulurken tür ve duruma göre sıradaki numara otomatik atanır (Örn: `Açık Dava 1`, `Kapalı Dava 1`, `İhtarname 1`). Klasörlerin yeni yerleşime açık olup olmadığı (`is_active`) denetlenir.
- **Dosya Yerleşimi & Kapatma/Açma Akışı:** Dosya kapatılırken (`close_case`) veya açılırken (`reopen_case`) hedef klasör ve boş numara seçilebilir. Arşiv yeri seçilmeden kapatılan/açılan durum takipli dosyalar inceleme uyarısıyla (`archive_needs_review = True`) işaretlenir.
- **ForeignKey Tabanlı Fiziki Arşiv (`Case.archive_folder`):** Dosya-klasör ilişkisi `ForeignKey(ArchiveFolder)` üzerinden yönetilir; `archive_folder_no` metin alanı geriye dönük uyumluluk ve arama performansı için `save()` metodunda çift yönlü otomatik senkronize tutulur.
- **Dinamik & Yapılandırılabilir Kategori Eşleştirmesi (`default_for_case_types`):** `ArchiveCategory` modelindeki JSON alanı sayesinde hangi dosya türünün hangi klasör türüne atanacağı sabit koddan bağımsız, veritabanından dinamik olarak yönetilir (`category_for_case`).
- **Veritabanı Düzeyinde Klasör Numaralandırma (`Max("number")`):** Yeni klasör numarası regex yerine doğrudan tamsayı aggregasyonu (`aggregate(Max("number"))`) ile hatasız ve hızlı üretilir.
- **Eski Kayıt Bütünlüğü:** Eski klasör adları, kapasiteleri ve dosya yerleri korunur; aktarım motorları (`import_legacy`) yeni klasörleri öksüz bırakmaz, dosya türünün dinamik kategorisine ve durumuna otomatik bağlar.
- Üst çubuktaki "Yeni kayıt" menüsü (her sayfada) görev, dosya, müvekkil, gelir/gider, duruşma/etkinlik ve fiziki klasör oluşturma pencerelerine (pop-up) açılır.
- **Merkezi Fiziki Arşiv Yönetimi (`views_archive.py`):**
  - Sekmeler: Kategori odaklı dinamik sekmeler (*Tümü*, genel klasör tipleri sırayla, *Müvekkile Özel*, *Arşiv Yeri Eksikler*). Açık/kapalı ayrımı olan bir sekme seçildiğinde sağ tarafta anında *Açık / Kapalı / Tümü* durum butonları belirir; tek durumlu türlerde gizlenir.
  - Görünüm & Filtreleme: Sayfa doğrudan Klasör Yönetimi / Gezgini modundadır (tablo görünümü kaldırılmıştır). Doğal sıralama (`natural_sort_key`) ile klasörler 1, 2, 3, ..., 9, 10 şeklinde kusursuz sıralanır. Filtre barı sadeleştirilmiş olup en solda estetik Segmented Pill durum seçici (Açık/Kapalı/Tümü), yalnızca Müvekkile Özel sekmesinde görünen Müvekkil Seçimi (`muvekkil`), sağda genişleyen ve yalnızca Klasör Adı/No ile Müvekkil arayan Arama çubuğu (`q`) ve Temizleme (`x`) butonu içerir; seçim anında otomatik filtrelenir (tuşsuz). Kartlar klasör sayısına göre dinamik CSS Grid ile boyutlanır.
  - **Yeni Klasör Türü (`ArchiveCategoryForm`):** Yeni tür oluşturulurken müvekkile özel klasör türü olup olmadığı (`is_client_specific`) ve ilgili müvekkil (`client`) seçilebilir.
  - **Klasör Detayı & Boş Numara Tespiti (`/arsiv/klasor/<folder_name>/`):** Klasördeki dosyaları sıralar; atlanmış/boşta kalan dosya numaralarını otomatik tespit ederek yeni dosya açılışında önerir.
  - **Hızlı Arşiv Yeri Güncelleme:** Modal üzerinden tek tıkla klasör ve dosya no güncelleme.
  - **Yazdırılabilir Etiketler (`/arsiv/etiketler/`):** A4 standardında Klasör Sırtlığı ve Dosya Kapak Etiketi yazdırma görünümü.
  - **Excel Dışa Aktarım:** Arşiv envanterinin Excel dökümü.

### İcra İşlemleri (`/icra/`, `apps/cases/enforcement.py`, `views_enforcement.py`)
- İcra takibi (`enforcement`) dosyalarının görünür kümesini (`filter_visible_cases`) listeler; yeni model yoktur. Süzgeçler: icra türü, aşama, müvekkilin sıfatı (alacaklı/borçlu/diğer), haciz (var/yok/tür/yenilemesi 30 gün içinde), tebligatı olanlar, avukat, durum. Haciz durumu aktif `Seizure` kayıtlarından, tebligat sayısı `PortalNotice.resolution_case`'den, "Son işlem" dosya, haciz ve tebligat zamanlarının en yenisinden gelir. Excel/PDF çıktısı vardır.
- Tebligatlar (`/tebligatlar/`): İşlem bekleyenler / Göreve bağlananlar / Görev gerekmeyenler / Tümü sekmeleri, arama ve tarih aralığı. Listede "olası son gün" gösterilmez; `calculate_notice_due_date` yalnızca görev formunun varsayılan bitiş tarihi içindir.

### `apps/tasks`
- **İş Akışı:** Sorumlu (`assignee`) ve kontrolcü (`reviewer`) arasında ilerleyen görevler. Durumlar: Aktif (`active`), Kontrolde (`review`), Kapalı (`done`).
- **Detay = düzenleme (tek pop-up):** Görev, duruşma ve tebligat kayıtları tek pencerede açılır; yetkisi olanlar aynı pencerede "Düzenle" ile formu yerinde (HTMX parçası) açar, yetkisizler yalnızca bilgi ve kendi işlem butonlarını görür. Düzenleme yetkisi: oluşturan, yönetici, kıdemli avukat (`services.can_edit`, `can_edit_hearing`); görev yalnızca aktifken düzenlenir. Görev işlemi (kontrole gönder, kapat) yalnızca sorumlunun, onay/revizyon yalnızca sırası gelen kontrolcünün; yönetici bu işlemleri yapamaz, yalnızca yeniden açabilir. Görev formu `templates/tasks/_form.html` + `static/js/task-form.js` ortak parçasıdır (oluşturma sayfası, yerinde düzenleme ve rutin görev kullanır). Tebligat penceresinde işlenmemiş tebligat için "Görev oluştur / Görev yok" bulunur.
- **Çift Kontrolcü (`Task.second_reviewer`):** İsteğe bağlı 2. kontrolcü sıralı onay verir: 1. kontrolcü onaylayınca görev kontrolde kalır ve sıra 2. kontrolcüye geçer (`Task.review_step`, "2. Kontrolde"). 1. kontrolcünün revizesi görevi sorumluya döndürür, sorumlu yeniden gönderince yine 1. kontrolcüye gider. 2. kontrolcü onay veya revize verirse görev sorumluya döner; revizeden sonra sorumlu gönderince görev doğrudan 2. kontrolcüye gider (1. kontrol atlanır). Son onayda belgeler yayınlanır; kapanışta puan her iki kontrolcüye de yazılır. Detay sayfasındaki Ekip bölümü (`Task.team_stages`) görevin kimde olduğunu vurgular.
- **Sorumlu ve kontrolcü seçimi:** Sorumlu yönetici (ve süper kullanıcı) olamaz; kontrolcü ve 2. kontrolcü yalnızca yönetici, kıdemli avukat veya avukat olur (`apps/tasks/people.py`). Eski kayıttaki kişi düzenlemede seçili kalır.
- **Kontrole gönderme notu:** Sorumlu kontrole gönderirken görev notu yazmak zorundadır (dilekçe olsun olmasın); not geçmişe "Kontrole gönderme notu" olarak düşer. İş emri no (dilekçeli görev) ve makbuz no (gelir/gider kayıtlı, dosyalı görev) görev kapatılırken sorulur ve zorunlu değildir (`Task.work_order_no`, `Task.receipt_no`).
- **Belge Zorunluluğu:** Dilekçe zorunlu görevlerde (`Task.requires_document`; seçim yoksa `TaskType.requires_document` varsayılanı) dilekçe yüklenmeden kontrole gönderilemez. İş emri numarası görev kapatılırken sorulur.
- **Görev Belgeleri:** Yüklenen belgeler hem medya deposunda saklanır hem de dosyanın ofis klasöründeki `Görevler` dizinine kopyalanır (`TaskDocument`). Onaylanan belgenin son sürümü dosyanın Belgeler sekmesinde yayınlanır. Dilekçeye ek belgeler ayrı türdedir (`TaskDocument.Kind.ATTACHMENT`, "Dilekçe ekleri"): kontrole göndermek için yalnızca dilekçe sayılır, onayda dilekçeyle birlikte dosyanın Belgeler sekmesine "Ek:" başlığıyla geçer.
- **Rutin Görevler (`RoutineTask`, `/gorevler/rutin/`, yönetici ve kıdemli avukat; Yeni kayıt menüsü ve Görevler ekranında "Rutin görevler" sekmesi, pop-up):** Haftanın belli günü veya ayın belli günü sorumluya görev açan kurallar. Kural formu normal görev formuyla aynı alanları sorar (görev türü, dosya/müvekkil, sorumlu, 1.–2. kontrolcü, gelir/gider kaydı, not, belge); not ve belgeler her açılan göreve kopyalanır (`RoutineDocument`). Dosya seçilmezse görev ofis içidir. `create_routine_tasks` komutu (`check-reminders.ps1` ile beş dakikada bir) günü gelen kuralın görevini bir kez üretir (`Task.routine` + `routine_date` benzersiz); ayın 31'i gibi günler kısa aylarda ayın son gününe kayar; kuralın kontrolcüsü pasifleşmişse ve sorumlu onaysız kapatamıyorsa görev açılmaz (kontrolcü düzeltilince açılır); sunucu kapalı kalırsa en çok 3 gün geriye dönük açılır. Kural silinse açılmış görevler kalır. Sekmede her kuralın açılan/tamamlanan sayısı görünür; kural penceresinde geçmiş (açılan görevler, tamamlanma, sonuç notu, gelir/gider kaydı) listelenir. Sorumluya zamanı gelince normal aktif görev olarak düşer.
- **Dilekçe Havuzu (`PetitionSample`, `/gorevler/dilekce-havuzu/`):** Büronun hazır dilekçe örnekleri (şablon değil). Giriş yapan herkes görür, indirir ve yükler; yalnızca yükleyen veya yönetici siler. Dosyalar `petition-pool/` altında saklanır ve `protected_media` ile girişli herkese sunulur. Arama `search_key` (Türkçe harf farkını yok sayar) üzerinden yapılır.
- **Puanlama (`TaskPoint`):** Görev kapatıldığında görev türünün puanı sorumluya ve kontrolcüye yazılır; yeniden açılırsa puanlar geri alınır.

- **Ana sayfa kontrol kartları:** Yönetici yalnızca "Kontrolümü bekleyenler"; kıdemli avukat ve avukat "Kontrolümü bekleyenler" + "Kontrolde olanlar" (kendi gönderdikleri) alt alta; stajyer yalnızca "Kontrolde olanlar" görür.

### `apps/accounting`
- **`LedgerEntry`:** Masraf (`expense`), Vekalet Ücreti (`fee`), Müvekkilden Tahsilat (`client_payment`), Karşı Taraftan Tahsilat / İcra Emanet (`trust_in`), Müvekkile Ödeme (`trust_out`). Giderlerde (`expense`) isteğe bağlı makbuz numarası (`receipt_no`) tutulur; diğer türlerde sunucu tarafında silinir.
- **Bakiye Formülü:**
  - *Müvekkilin Ofise Borcu:* Vekalet Ücreti + Masraf
  - *Müvekkilin Ofisten Alacağı:* Karşı Taraftan Tahsilat
  - *Cari Bakiye:* `(Ofise Borç − Müvekkilden Tahsilat) − Karşı Taraftan Tahsilat + Müvekkile Ödeme`
  - Pozitif bakiye = Müvekkil ofise borçlu ("Alacağımız"); Negatif bakiye = Ofis müvekkile borçlu ("Borcumuz"). Arayüzde yön kırmızı/yeşil renkle değil bu etiketlerle gösterilir.
- **Ofis içi gelir/gider (kaldırıldı):** Ekran, menü ve URL'ler kaldırıldı; `OfficeEntry` modeli ve verisi (`office-ledger/` belgeleri dahil) silinmedi, ileride yeniden eklenebilir.
- **UYAP kaynaklı hareket (`LedgerEntry.portal_ref` dolu):** Dosya Muhasebe sekmesi sol "Büro kaydı", sağ "UYAP (salt okunur)" olarak ikiye ayrılır; genel bakiye ikisini birlikte hesaplar. UYAP hareketi iptal edilmez, yetkili (`accounting.exclude_portal`) gerekçeyle hesap dışı bırakır/geri alır (`excluded_from_balance`; bakiye, toplam ve ekstre `counted()`/`balance_effect` ile dışlar). Sözleşme, ihtarname ve diğer türde (`Case.has_portal` yanlış) UYAP bölümü (taraflar, muhasebe) gösterilmez.
- **Kayıt Bütünlüğü:** Muhasebe hareketi silinmez; gerekirse iptal edilir (`cancelled`). Veritabanı kısıtları tutarı sıfırdan büyük, iptal kaydını iptal zamanlı tutar (`ledger_amount_positive`, `ledger_cancel_has_time`). Kasa toplamları ve bakiyeler yalnızca bakiye görme yetkisi (`accounting.balances`) olan kullanıcılara gösterilir.

### `apps/imports` & UYAP/UETS Entegrasyonu
- **Tarayıcı Eklentisi (`uyap-uets-eklentisi`):** UYAP Avukat Portal ve UETS oturumlarını yerel sunucuya bağlar. Eklenti yalnızca **ana bilgisayarda** (sunucunun kurulu olduğu, sürekli açık bilgisayar) kurulur; UYAP/UETS orada açık ve oturum geçerliyken aktarım kendiliğinden başlar, sekme kapanınca veya oturum düşünce durur. Eşleştirmeyi yalnızca yönetici yapar; aktarım üretimde de çalışır. Başka bir avukatın verisi için o avukatın hesabı yine ana bilgisayarda açılır. Üst çubukta, herkese görünen UYAP/UETS durum göstergesi vardır (`portal_status.py`): Ayarlar > Eklenti bağlantıları'nda otomasyon izni verilmiş her avukat için o an aktarım olup olmadığı listelenir. Eşzamanlı çoklu hesap veya çoklu bilgisayar aktarımı henüz desteklenmez. Desteklenen davranış ve durumlar: `docs/uyap-uets-davranis.md`.
- **UYAP evrak içeriği:** Eklenti taranan her dosyanın tüm evraklarını `/download_document_brd.uyap` ile indirir; sunucu bunları dosyanın Belgeler sekmesine ve ofis klasöründeki `UYAP Evrakları` alt klasörüne ekler, aynı evrakı ikinci kez almaz (`PortalDocument`). Ayrıntı: `docs/uyap-uets-davranis.md`.
- **Dosya Bilgisi & Taraf Eşitlemesi (`portal_case_sync.py`):** UYAP duruşmaları yalnızca kurulum tarihinden (`OfficeSettings.installed_on`) sonrakiler için aktarılır; öncekiler alınmaz. Canlı UYAP aktarımında eşleşen büro dosyası yoksa otomatik `Case` açılır; vekili olduğumuz taraf sistemdeki bir müvekkille eşleşirse bağlanır, eşleşmezse `client=None` bırakılarak "Eksik büro bilgisi" filtresine (`?missing=1`) düşer. UYAP'tan gelen duruşmalar `Hearing` kaydı olarak aktarılır. UYAP evrakları eklenti taramasıyla dosyanın Belgeler sekmesine indirilir (not: ilk tam tarama uzun sürer).
- **Tebligat Yönetimi:** UETS tebligatlarından tebliğ tarihine yasal süre eklenerek süreli görev oluşturma pop-up'ı.
  - Dosyayla eşleştirilen tebligat belgeleri ilgili dosyanın `Tebligatlar` klasörüne kopyalanır. Dosyası olmayan tebligatlar sistemde saklanır; yanlış dosyaya otomatik yerleştirilmez. Önceden eşleştirilmiş belgeler `uv run python manage.py copy_notice_documents` ile güvenli biçimde yeniden kontrol edilebilir; mevcut farklı içerik ezilmez.

### `apps/reports` & Sistem Monitörü
- **Raporlar (`/raporlar/`)** ortadan ikiye bölünür: solda **Müvekkil raporları** (müvekkile gönderilmek üzere, 4 kategori: dosya durum, duruşma, hesap [ekstre, masraf ve tahsilat özeti], tebligat; müvekkil seçmek zorunludur), sağda **Ofis raporları** (iç kullanım, 5 kategori: dosya, müvekkil, görev, muhasebe, duruşma ve tebligat). Müvekkil raporları ofis içi bilgi içermez: sorumlu/yardımcı sorumlu, arşiv yeri, görev, kontrolcü, zaman çizelgesindeki serbest notlar, katılma durumu, iç sonuç notu, iptal ve hesap dışı muhasebe kayıtları yazılmaz; ortak dosyada diğer müvekkilin adı geçmez; duruşma açıklaması `Hearing.client_note` alanından gelir. Her rapor `definitions.py`'de form + `build_...` + `REPORTS` kaydıdır (`audience`: `client`/`office`, `group`). Mali raporlar `accounting.balances` yetkisiyle görünür. Haciz/yenileme raporu ve sütunları kaldırıldı. Çıktılar Excel (`openpyxl`) ve Türkçe fontlu PDF (`reportlab`).
- **Liste çıktıları:** Dosya, müvekkil, görev, muhasebe, tebligat ve duruşma listelerinin sağ üstünde Excel/PDF düğmeleri vardır (`apps/core/list_export.py`, `ListExportMixin`, `partials/export_buttons.html`, `static/js/list-export.js`); sayfadaki süzgeçler uygulanır, sayfalama yok sayılıp listenin tamamı alınır, görünürlük kuralları geçerlidir.
- **Sistem Monitörü (`SettingsView?bolum=monitor`):** Veritabanı boyutu, disk kullanımı, son yedekler, UYAP sayaçları ve arka plan servislerinin durumunu gösteren yönetici kontrol paneli.
- **Kullanıcı Analizi (`SettingsView?bolum=kullanici_analizi`):** Personel işlem hacimleri, aktif/geciken görev sayıları ve puan dökümleri.

### `apps/backups`
- **Otomatik Yedekleme:** Günlük yedekte veritabanı dökümü parolasız arşive alınır; sistem belgeleri ofis klasöründeki `Sistem Belgeleri` altında ayrı kopyalanır ve silinmez. Aynı adlı farklı içerik varsa üzerine yazılmaz, yedek başarısız bildirilir. Elle ve güncelleme öncesi yedekler belgeleri de arşive alır. Günlük veritabanı yedeğinden geri yükleme mevcut sistem belgelerine dokunmaz; yeni kurulumda ayrı belge kopyası ayrıca yerine konmalıdır.
- **Windows geliştirme ortamı:** `Hukuk Burosu Gelistirme Yedek` zamanlanmış görevi, açık kullanıcı oturumunda `scripts/backup_hidden.vbs` aracılığıyla yarım saatte bir yedek zamanını kontrol eder; komut penceresi açılmaz.
- **Saklama Politikası:** Son 30 günün günlük yedekleri + son 12 ayın aylık ilk yedekleri korunur (`apply_retention`).
- **Geri Yükleme:** `manage.py restore <yedek.zip> --yes` komutu ile tek adımda güvenli geri yükleme.

---

## 4. İş Kuralları ve Prensipler

1. **Dosya ve Müvekkil İlişkisi:** Görevler ilgili dosya bağlamında yönetilir; yeni görev formunda dosya zorunludur ve görevdeki müvekkil dosyadan türetilir. Dosyası olmayan (ofis içi) görev yeni açılamaz; yalnızca rutin görev kuralı dosyasız tanımlanabilir. Eski dosyasız görevler (`Task.case=None`) yalnızca sorumlu, kontrolcü ve yönetici tarafından görülür (`filter_visible_tasks`). **İstisna:** UYAP'tan yeni aktarılan ve müvekkili henüz eşleştirilemeyen `Case` kayıtlarında `client=None` olabilir. Bu dosyalarda müvekkil varmış gibi varsayım yapılmaz; eşleştirme kullanıcı tarafından tamamlanır. Yeni kod bu geçici durumu güvenli biçimde ele almalıdır.
2. **Kayıt Silme Yetkisi:** Dosya, müvekkil, duruşma ve muhasebe kayıtlarını yalnızca yönetici silebilir. Muhasebe hareketleri fiziksel silinmek yerine iptal edilir.
3. **Ofis Klasör Yapısı:** Belgeler `OfficeSettings.documents_root` altında düzenli hiyerarşide tutulur: `<Kök>\Müvekkiller\<Müvekkil Adı>\<Dosya Adı>\`.
4. **Türkçe Karakter Standardı:** Müvekkil adları, dosya konuları ve görev başlıkları model seviyesinde Türkçe kurallarla büyük harfe dönüştürülür (`tr_upper`). Listelerde ve ana sayfada ekranda normal yazım gösterilir (`tr_title` şablon filtresi, kelime bazlı; UYAP, SGK gibi kısaltmalar büyük kalır). Saklanan veri değişmez; yeni liste şablonlarında ad alanları `|tr_title` ile yazılır.
5. **Aktivite Kaydı:** Tüm model değişiklikleri ve kullanıcı giriş/çıkışları `django-auditlog` ile kaydedilir. `OfficeSettings` (yetki matrisi dahil) da kayıtlıdır; Google anahtarı, iCal adresi ve banka bilgisi kayda yazılmaz.

---

## 5. Çalışma Standartları

- **Kod Dili:** Kodlar, fonksiyonlar, modeller ve değişkenler İngilizce; kullanıcı arayüzü, hata mesajları, commit mesajları ve dokümantasyon **Türkçe** olmalıdır.
- **Test ve Denetim:** Yapılan her kod değişikliğinden sonra ilgili hedefli testler, ardından `uv run pytest`, `uv run ruff check .` ve `uv run ruff format --check .` çalıştırılmalıdır. Çalıştırılamayan komutlar veya başarısız sonuçlar açıkça raporlanır; sonuç uydurulmaz.
- **Tek Bilgi Kaynağı:** Mimari kararlar, kalıcı iş kuralları, entegrasyon sınırları ve geliştirme komutlarındaki değişiklikler bu dosyada (`CLAUDE.md`) güncellenir. Geçici görev notları veya her küçük refaktör buraya yazılmaz.

---

## 6. Geliştirici Ajan İş Akışı (Zorunlu)

Ajan her görevde şu sırayı izler; kullanıcı açıkça daha dar kapsam istemedikçe doğrulamayı atlamaz:

1. **Anla:** İsteği, beklenen sonucu, etkilenen kullanıcı rollerini ve iş kurallarını belirle. Belirsiz kritik davranışı mevcut kod/testlerden doğrula; varsayımı gerçek olarak yazma.
2. **İncele:** İlgili `models`, `views`, `forms`, `services`/yardımcı fonksiyonlar, template'ler, URL'ler, mevcut testler ve entegrasyon noktalarını oku. `git status` ile başlangıç değişikliklerini kontrol et; kullanıcıya ait değişiklikleri koru.
3. **Planla:** Etkilenecek dosyaları, veri modeli veya migration ihtiyacını, izin kontrollerini, hata durumlarını ve test senaryolarını kısaca belirle. Gereksiz kapsam genişletme.
4. **Uygula:** Küçük ve odaklı değişiklikler yap. Var olan mimariyi ve adlandırmayı izle; açıklanmamış yeni bağımlılık, servis veya genel soyutlama ekleme.
5. **Doğrula:** Olumlu/olumsuz yolları, rol kısıtlarını, veri bütünlüğünü ve geriye dönük uyumluluğu test et. Bölüm 10'daki kontrolleri çalıştır.
6. **Belgele ve bildir:** İlgili kalıcı kural değişmişse `CLAUDE.md` dosyasını güncelle. Sonuçta değişenleri, test sonuçlarını, uygulanmayan noktaları ve riskleri kısa raporla.

**Güvenli değişiklik ilkeleri:** Kullanıcının ilgisiz değişikliklerini silme; izinsiz `git reset --hard`, `git clean`, veri silme veya production üzerinde migration çalıştırma. Hata düzeltirken önce tekrar üretilebilir bir test oluşturmayı tercih et. Büyük refaktörü kullanıcı istemedikçe işlevsel değişiklikten ayrı tut.

---

## 7. Mimari ve Kod Organizasyonu Kuralları

- **Modül sahipliği:** `accounts` kimlik/rol, `clients` müvekkil, `cases` dosya/safahat, `tasks` görev/onay, `agenda` duruşma/takvim, `imports` dış veri aktarımı, `accounting` finans, `backups` yedekleme alanlarını sahiplenir. Başka bir modülün iş kuralını kopyalama; sahibi olan modülün mevcut arayüzünü kullan.
- **Katman sorumluluğu:** `models` veri kuralları ve bütünlüğü; `forms` kullanıcı girdisi ve form doğrulaması; `views` HTTP akışı/yetki denetimi; `templates` sunum; `services` veya mevcut yardımcı fonksiyonlar birden çok adımlı işlemler ve haricî entegrasyonlar içindir. Mevcut kodda başka bir konvansiyon varsa önce onu incele; yeni bir `services.py` yapısını sırf standart olsun diye zorunlu kılma.
- **İş mantığı:** Kritik kuralları yalnızca template/JavaScript içinde bırakma. HTMX uçları dahil bütün mutasyonlarda sunucu tarafında doğrulama ve yetki kontrolü yap.
- **Bağımlılıklar:** Çapraz modül importlarında döngü oluşturma; yeni bağımlılık için gerekçe, çevrimdışı çalışma etkisi, kurulum/paketleme etkisi ve test ihtiyacını değerlendir.
- **Entegrasyon izolasyonu:** UYAP/UETS, Google Calendar, dosya sistemi ve veritabanı işlemlerini mümkün olduğunca birbirinden ayrılabilir arayüzlerde tut. Ağ hatası, yinelenen kayıt, kısmi başarısızlık ve yeniden deneme senaryolarını ele al.
- **Kullanıcı deneyimi:** Mevcut Türkçe arayüz, HTMX/Alpine.js yaklaşımı ve CDN'siz çalışma korunur. Yeni ekranlar erişim kontrolü, boş durum ve anlaşılır hata mesajı içerir.
- **Tasarım önceliği:** Kullanıcı kullanımın yaklaşık %99’unun bilgisayarda olacağını belirtti. Tasarım değerlendirmelerinde 1366×768 ve 1920×1080 masaüstü ekranları, okunaklı tablolar ve hızlı kayıt geçişleri önceliklidir; mobil iyileştirmeler düşük önceliklidir.

---

## 8. Güvenlik ve Gizlilik Kuralları

- **Sunucu tarafı yetki:** Her dosya, görev, belge, rapor ve finans kaydı için görüntüleme/değiştirme iznini istek bazında doğrula. Arayüzde düğmeyi gizlemek tek başına güvenlik değildir. rol yetki matrisini (`has_perm`) ve görünürlük süzgeçlerini birlikte değerlendir.
- **Dosya erişimi:** Yüklemelerde dosya türü, boyut ve uzantı/içerik uygunluğunu denetle; kullanıcıdan gelen dosya yoluna güvenme. `documents_root` ve `media/` dışına path traversal ile erişimi önle. Dosya indirmelerinde de izin denetimi yap.
- **Kimlik doğrulama:** 4 haneli PIN zayıf bir sırdır; deneme yavaşlatma (bkz. `apps/accounts/throttle.py`) kaba kuvveti zorlaştırır ama PIN'i güçlü kimlik doğrulama yapmaz. Yönetici hesapları için daha uzun PIN/parola, güvenli oturum ayarları ve kalıcı (veritabanı tabanlı) deneme kaydı hâlâ **iyileştirme hedefidir**.
- **Dosya/görev/belge görünürlüğü:** `cases.view_all` yetkisi olmayan roller için dosya, görev, duruşma, haciz, rapor, UETS tebligatı/UYAP kaydı, muhasebe hareket formu ve `/media/` uçlarının tümü `filter_visible_cases` / `filter_visible_tasks` / `filter_visible_hearings` / `filter_visible_clients` / `filter_visible_notices` (`apps/core/permissions.py`) ile nesne alır; görünmeyen kayıt 404 verir. Dosyaya/müvekkile bağlanmamış tebligat işlenmek üzere herkese görünür; dosyasız etkinlikler (toplantı, görüşme) bilinçli olarak herkese açıktır. Muhasebe listesi bilinçli olarak herkese açıktır, ancak hareket yalnızca görünür dosya/müvekkile girilir. Genel arama da görev/belge sonuçlarını ve karşı tarafların dosya bağlantılarını aynı görünürlükle süzer. Yeni uç yazarken `get_object_or_404(Case, ...)` yerine görünür kayıt kümesini kullan; `tests/test_visibility_endpoints.py` bu davranışı sınar.
- **Yüklemeler:** `validate_upload` uzantı ve boyutun yanı sıra imzası bilinen türlerde (PDF, resim, OOXML/ODF, ZIP, eski Office, RTF) dosya imzasını (magic bytes) denetler. `.xls` bilerek denetlenmez (bankalar HTML/CSV içeriği `.xls` adıyla verebilir); metin tabanlı türler yalnızca uzantıyla sınırlıdır ve tarayıcıda açılmaz.
- **Yedekler:** Yedek ZIP'leri parolasızdır; `manage.py restore` geri yüklemeden önce mevcut verinin tam yedeğini (`Geri yükleme öncesi`) otomatik alır, alınamazsa geri yüklemeyi başlatmaz (`--guvenlik-yedegi-alma` ile atlanabilir). Şifreli yedek, ayrı fiziksel konuma (harici disk/NAS) kopya, erişim kısıtları ve düzenli geri yükleme testi **hedef iyileştirmelerdir**; uygulanmadan mevcut özellik diye sunma.
- **Gizli bilgiler:** API anahtarı, bağlantı bilgisi, kimlik/vergi numarası, IBAN, müvekkil belgesi ve gerçek dosya içeriğini log, test fikstürü, ekran görüntüsü, kod yorumu veya dokümantasyona taşıma. Testlerde sentetik veri kullan.
- **Dış servisler:** LAN/çevrimdışı çalışma temel varsayımdır. Müvekkil verilerini veya belgelerini yeni bir dış servise aktaran entegrasyon kullanıcı onayı, veri minimizasyonu, güvenlik ve ilgili mevzuat değerlendirmesi olmadan eklenmez.
- **İşlem izi:** Önemli değişikliklerin mevcut `django-auditlog` mekanizmasını atlamadığını kontrol et. Loglarda gizli içerik tutulmasını engelle.

---

## 9. Veritabanı, Dosya Sistemi ve İşlem Bütünlüğü

1. **Migration:** Model/alan/constraint değişikliğinde Django migration oluştur; var olan migration dosyalarını yeniden yazma. Önce veri göçü ve eski kayıtlarla uyumu değerlendir. Üretim veritabanında izinsiz migrate/restore çalıştırma.
2. **Transaction:** Bir işlemin birden fazla kaydı tutarlı biçimde değiştirmesi gerekiyorsa `transaction.atomic()` ve uygun benzersizlik/kilit mekanizmalarını değerlendir. Özellikle safahat, tahsilat, görev kapama/puanlama ve sayaç atamalarında yarım işlemi önle.
3. **Tekrarlanabilirlik:** UYAP/UETS/Google senkronizasyonları, otomatik görevler ve yeniden denenebilir komutlar aynı olay için mükerrer kayıt üretmemelidir. Mevcut kimlik/eşleştirme alanlarını koru.
4. **Silme ve düzeltme:** Yönetici yetkisi, muhasebede iptal yaklaşımı ve geçmiş kayıtlarını koruma kuralını bozma. Silme/güncelleme işlemlerinde bağlı kayıtların ve audit geçmişinin etkisini test et.
5. **Dosya bütünlüğü:** `TaskDocument`, `media/` ve ofis klasörüne kopyalanan belge sürümleri arasında tutarlılığı koru. Veritabanı işlemi ile dosya sistemi işlemi tek atomik işlem değildir; başarısızlıkta telafi/temizlik ve tekrar deneme davranışını tanımla.
6. **Null ve istisnalar:** UYAP'tan gelen `Case.client=None` ve dosyasız `Hearing.case=None` gibi belgelenmiş istisnalar için güvenli davranış ve test ekle.

---

## 10. Test, Kalite ve Hata Yönetimi

- **Yeni davranış = yeni test:** İş kuralı değişikliğinde en az bir başarılı, bir hatalı/istisnai senaryo ve ilgili izin testi yaz veya güncelle. Regresyon hatasını mümkünse önce başarısız testle göster.
- **Kritik test alanları:** Rol ve dosya görünürlüğü; görev–kontrolcü onay akışı; müvekkili eşleşmeyen UYAP dosyaları; muhasebe bakiyesi ve iptal; tebligat görevleri; dosya yükleme/indirme; mükerrer senkronizasyon; yedek/geri yükleme.
- **Dış bağımlılıklar:** Testleri gerçek UYAP/UETS, Google API, üretim sunucusu ve müvekkil belgelerine bağlama. Mock/fake ve sentetik veri kullan; ağ yokken başarısızlık davranışını test et.
- **Hata yönetimi:** Beklenen kullanıcı hatalarını anlaşılır Türkçe mesajla döndür; teknik ayrıntı ve gizli veri sızdırma. Kritik hataları yapılandırılmış, gereğinden fazla veri içermeyen loglarla kaydet. Hataları sessizce yutup başarılı sonuç dönme.
- **Kontrol sırası:** Önce etkilenen modülün hedefli testleri, ardından proje çapında aşağıdaki komutlar:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- **Raporlama:** Komut başarısızsa neyin ve neden başarısız olduğunu belirt. Testler çalıştırılmadıysa açıkça söyle; başarılıymış gibi yazma. Değişiklik yapmadan önce var olan hataları yeni hatalardan ayır.

---

## 11. Hukuki Süreler ve Dış Veri Sınırları

- **Süre hesabı:** `notice_default_due_days` (varsayılan 14), hukuki sürelerin tamamı için geçerli bir kural değildir; görev oluştururken kullanılan varsayılan ayardır. Kesin süre, tebliğ usulü, başlangıç günü, tatil, dava/takip türü ve ilgili mevzuata göre değişir. Doğrulanmamış süreyi kesin hukuki son gün gibi gösterme; kullanıcı incelemesi gerektiren durumları belirt.
- **UYAP veri kapsamı:** Evrak içerikleri yalnızca tarama o dosya için tamamlandıysa dosyada bulunur; bir dosyada belge yoksa taramanın henüz bitmediği veya evrakın reddedildiği (gösterge ve durum `eksik`) olabilir. Evrak tabanlı işlemler yalnızca gerçekten alınmış belgeler üzerinden yürütülür.
- **Onay mekanizması:** Rol matrisindeki `tasks.close_without_review` ile belirlenen kontrolcü akışını atlama. Duruşma görevinin dokümante edilmiş kontrolcüsüz kapanış istisnasını ve diğer istisnaları değişiklik öncesinde doğrula.

---

## 12. Tamamlanma Kriterleri (Definition of Done)

Bir geliştirme ancak aşağıdaki koşullar sağlandığında **tamamlandı** olarak bildirilir:

- [ ] İstenen davranış uygulanmış; kapsam dışı mevcut işlevler korunmuştur.
- [ ] Roller, dosya görünürlüğü ve gerekli sunucu tarafı izinler kontrol edilmiştir.
- [ ] Giriş doğrulaması, hata/boş durum ve veri bütünlüğü senaryoları ele alınmıştır.
- [ ] İlgili yeni/güncel testler yazılmış; hedefli ve tam test/lint/format kontrolleri çalıştırılmıştır.
- [ ] Migration, yeni ayar, yeni bağımlılık veya paketleme etkisi varsa değerlendirilmiş ve gerekli talimatlar eklenmiştir.
- [ ] Kalıcı mimari/iş kuralı değişikliği varsa `CLAUDE.md` güncellenmiştir.
- [ ] Değişen dosyalar, doğrulama sonuçları, açık riskler ve yapılmayan işler kullanıcıya özetlenmiştir.

**Koşullardan biri sağlanamadıysa** işi tamamlandı diye sunma; hangi koşulun eksik kaldığını belirt.
