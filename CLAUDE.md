# Hukuk Büro Yönetim Sistemi — Geliştirici & Mimari El Kitabı

Bu dosya projenin tek bilgi kaynağıdır (`Single Source of Truth`). Geliştirici ajanlar ve katkıda bulunanlar kuralları buradan okur (`AGENTS.md` buraya yönlendirir). Oturum başında okuyun, yapılan değişikliklerden sonra güncelleyin. Değer değil, yalnızca ortam değişkeni adları yazılır.

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
uv run ruff check .                                  # Linter denetimi
uv run ruff format --check .                         # Format denetimi
```

---

## 3. Mimari ve Modül Yapısı

### `apps/core`
- Ortak model altyapısı (`TimeStampedModel`), TCKN / VKN / IBAN doğrulayıcıları.
- Türkçe metin yardımcıları (`fold`, `tr_lower`, `tr_upper`, `tr_capitalize_words`).
- Genel arayüz template tag'leri (`tl` para formatı, `sort_link`, `query_with`).
- Dinamik sayfalama altyapısı (`pagination.py`).

### `apps/accounts`
- **Özel Kullanıcı Modeli (`User`):** 7 rol desteklenir:
  - `admin`: Yönetici Avukat (Tam sistem yetkisi)
  - `senior`: Kıdemli Avukat
  - `lawyer`: Avukat
  - `intern`: Stajyer Avukat
  - `paralegal`: İcra Katibi / Takip Memuru
  - `secretary`: Sekreter / Büro Yönetimi
  - `accountant`: Muhasebe / Finans
- **Oturum Açma:** Kullanıcı adı/şifre yerine kullanıcı kartı seçilerek 4 haneli PIN ile hızlı giriş. Hatalı PIN'de kilit konmaz; 4. rakam girildiğinde form otomatik gönderilir.
- **İlk Kurulum Sihirbazı (`InitialSetupView`, `/hesap/ilk-kurulum/`):** Temiz kurulumda hiç kullanıcı yoksa ilk açılışta büro adı, çalışma modeli ve ilk yönetici hesabını tek adımda oluşturan ekran.
- **Oturum Güvenliği:** `OfficeSettings.idle_minutes` süresince işlem yapılmazsa oturum otomatik kapanır (`?zaman_asimi=1`). `NoStoreMiddleware` ile tarayıcı bellekten geri gitmelerinde veri sızıntısı engellenir.

### `apps/office`
- **`OfficeSettings`:** Büro adı, logosu, iletişim bilgileri, doküman kök klasörü (`documents_root`), oturum zaman aşımı ve modüler ofis çalışma kuralları:
  - `use_assistant_assignee`: Dosya ve müvekkillerde yardımcı sorumlu (stajyer/katip) kullanımını açıp kapatır.
  - `case_visibility_mode`: `public` (herkese açık) veya `restricted` (yalnızca sorumlu/yardımcı olduğu dosyaları görebilme).
  - `task_review_mode`: `required` (her görevde kontrolcü zorunlu), `assistants_only` (yalnızca yardımcılar için zorunlu; avukatlar doğrudan kapatabilir), `optional` (isteğe bağlı).
  - `accounting_edit_mode`: `everyone` (herkes gelir/gider ekleyebilir) veya `restricted` (yalnızca yönetici, muhasebe ve yetkililer).
  - `notice_default_due_days`: UETS tebligatları için varsayılan ek süre (varsayılan: 14 gün).
  - `use_task_points`: Personel görev puanı sistemini açıp kapatır.
- **`TaskType`:** Kategorize edilmiş görev türleri, varsayılan puanları ve belge zorunluluğu bayrağı.
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

### `apps/agenda` & Duruşma Yönetimi
- **Birleşik Takvim (`/takvim/`):**
  - Ay Görünümü (`view=month`): Google Takvim etkinlikleri ve görev son günleri takvim ızgarasında.
  - Hafta Görünümü (`view=week`): Saatlik ve günlük ajanda.
  - Liste / Duruşmalar Görünümü (`view=list`): Yaklaşanlar, Bugün, Sonuç Bekleyenler, Geçmiş ve Tümü sekmeleri. Sayaçlar, sorumlu/tür/durum filtreleri, hızlı ara karar modalı ve Excel dökümü.
- **`Hearing` Modeli:** Hem dava duruşmalarını hem de dosyasız müvekkil randevularını, arabuluculuk oturumlarını ve ofis toplantılarını destekler (`case=None`, `client`, `title`, `assigned_to`, `ends_at`).
- **Otomatik Duruşma Görevi (`hearing_tasks.py`):**
  - Duruşmadan 1 gün önce sabah dosya sorumlusuna otomatik görev açılır: `"{case.display_name} DURUŞMASI İŞLEMLERİ YAPILACAK VE MÜVEKKİLE BİLGİ VERİLECEK"`.
  - Görev duruşmaya bağlıdır (`task.hearing`) ve kontrolcüsüz doğrudan kapatılabilir.
  - Görev kapatılırken: duruşmaya girilmediyse *"Mazeret Gönderildi"* (mazeret açıklamasıyla), girildiyse *"Duruşmada Verilen Kararlar"* zorunlu doldurulup *"Müvekkile Bilgi Verildi / Verilmedi"* seçenekleri işaretlenir. Bilgiler duruşma kartına ve dosya zaman çizelgesine (`CaseEvent`) otomatik işlenir.
- **Google Takvim API Tek Yönlü Entegrasyon (`google_sync.py`):**
  - Sistemdeki duruşma ve toplantılar ofis Google Takvimi'ne tek yönlü aktarılır ve güncellenir.
  - Google Takvim'deki mevcut veya harici etkinliklere kesinlikle dokunulmaz; mükerrer kayıt `google_event_id` ile engellenir.

### Fiziki Arşiv Modülü (`/arsiv/`)
- **Merkezi Fiziki Arşiv Yönetimi (`views_archive.py`):**
  - Sekmeler: *Tümü*, *Açık Arşiv*, *Kapalı Arşiv*, *İcra Arşivi*, *Arşiv Yeri Eksikler* (özellikle UYAP'tan yeni gelen dosyalar).
  - İki Görünüm: Tablo görünümü ve Klasör Gezgini (`view=explorer`).
  - **Klasör Detayı & Boş Numara Tespiti (`/arsiv/klasor/<folder_name>/`):** Klasördeki dosyaları sıralar; atlanmış/boşta kalan dosya numaralarını otomatik tespit ederek yeni dosya açılışında önerir.
  - **Hızlı Arşiv Yeri Güncelleme:** Modal üzerinden tek tıkla klasör ve dosya no güncelleme.
  - **Yazdırılabilir Etiketler (`/arsiv/etiketler/`):** A4 standardında Klasör Sırtlığı ve Dosya Kapak Etiketi yazdırma görünümü.
  - **Excel Dışa Aktarım:** Arşiv envanterinin Excel dökümü.

### `apps/tasks`
- **İş Akışı:** Sorumlu (`assignee`) ve kontrolcü (`reviewer`) arasında ilerleyen görevler. Durumlar: Aktif (`active`), Kontrolde (`review`), Kapalı (`done`).
- **Belge Zorunluluğu:** `TaskType.requires_document` işaretli türlerde dilekçe yüklenmeden kontrole gönderilemez.
- **Görev Belgeleri:** Yüklenen belgeler hem medya deposunda saklanır hem de dosyanın ofis klasöründeki `Görevler` dizinine kopyalanır (`TaskDocument`). Onaylanan belgenin son sürümü dosyanın Belgeler sekmesinde yayınlanır.
- **Puanlama (`TaskPoint`):** Görev kapatıldığında görev türünün puanı sorumluya ve kontrolcüye yazılır; yeniden açılırsa puanlar geri alınır.

### `apps/accounting`
- **`LedgerEntry`:** Masraf (`expense`), Vekalet Ücreti (`fee`), Müvekkilden Tahsilat (`client_payment`), Karşı Taraftan Tahsilat / İcra Emanet (`trust_in`), Müvekkile Ödeme (`trust_out`).
- **Bakiye Formülü:**
  - *Müvekkilin Ofise Borcu:* Vekalet Ücreti + Masraf
  - *Müvekkilin Ofisten Alacağı:* Karşı Taraftan Tahsilat
  - *Cari Bakiye:* `(Ofise Borç − Müvekkilden Tahsilat) − Karşı Taraftan Tahsilat + Müvekkile Ödeme`
  - Pozitif bakiye = Müvekkil ofise borçlu; Negatif bakiye = Ofis müvekkile borçlu.
- **Kayıt Bütünlüğü:** Muhasebe hareketi silinmez; gerekirse iptal edilir (`cancelled`). Kasa toplamları ve bakiyeler yalnızca bakiye görme yetkisi (`can_view_balances`) olan kullanıcılara gösterilir.

### `apps/imports` & UYAP/UETS Entegrasyonu
- **Tarayıcı Eklentisi (`uyap-uets-deneme`):** UYAP Avukat Portal ve UETS oturumlarını yerel sunucuya bağlar.
- **Tam Dosya & Taraf Eşitlemesi (`portal_case_sync.py`):** Canlı UYAP aktarımında eşleşen büro dosyası yoksa otomatik `Case` açılır; vekili olduğumuz taraf sistemdeki bir müvekkille eşleşirse bağlanır, eşleşmezse `client=None` bırakılarak "Eksik büro bilgisi" filtresine (`?missing=1`) düşer. UYAP'tan gelen duruşmalar `Hearing` kaydı olarak aktarılır.
- **Tebligat Yönetimi:** UETS tebligatlarından tebliğ tarihine yasal süre eklenerek süreli görev oluşturma pop-up'ı.

### `apps/reports` & Sistem Monitörü
- 7 standart rapor (Dava listesi, icra takipleri, görevler, haciz takibi, kasa/mali raporlar). Excel (`openpyxl`) ve Türkçe fontlu PDF (`reportlab`) çıktıları.
- **Sistem Monitörü (`SettingsView?bolum=monitor`):** Veritabanı boyutu, disk kullanımı, son yedekler, UYAP sayaçları ve arka plan servislerinin durumunu gösteren yönetici kontrol paneli.
- **Kullanıcı Analizi (`SettingsView?bolum=kullanici_analizi`):** Personel işlem hacimleri, aktif/geciken görev sayıları ve puan dökümleri.

### `apps/backups`
- **Otomatik Yedekleme:** `manage.py backup` komutu ile PostgreSQL veritabanı dökümü (`db.dump`), yüklenen belgeler (`media/`) ve dilekçe şablonları parolasız `.zip` arşivinde toplanır.
- **Saklama Politikası:** Son 30 günün günlük yedekleri + son 12 ayın aylık ilk yedekleri korunur (`apply_retention`).
- **Geri Yükleme:** `manage.py restore <yedek.zip> --yes` komutu ile tek adımda güvenli geri yükleme.

---

## 4. İş Kuralları ve Prensipler

1. **Dosya ve Müvekkil İlişkisi:** Her görev bir dosyaya, her dosya bir müvekkile bağlıdır. Görevdeki müvekkil dosyadan otomatik gelir.
2. **Kayıt Silme Yetkisi:** Dosya, müvekkil, duruşma ve muhasebe kayıtlarını yalnızca yönetici silebilir. Muhasebe hareketleri fiziksel silinmek yerine iptal edilir.
3. **Ofis Klasör Yapısı:** Belgeler `OfficeSettings.documents_root` altında düzenli hiyerarşide tutulur: `<Kök>\Müvekkiller\<Müvekkil Adı>\<Dosya Adı>\`.
4. **Türkçe Karakter Standardı:** Müvekkil adları, dosya konuları ve görev başlıkları model seviyesinde Türkçe kurallarla büyük harfe dönüştürülür (`tr_upper`).
5. **Aktivite Kaydı:** Tüm model değişiklikleri ve kullanıcı giriş/çıkışları `django-auditlog` ile kaydedilir.

---

## 5. Çalışma Standartları

- **Kod Dili:** Kodlar, fonksiyonlar, modeller ve değişkenler İngilizce; kullanıcı arayüzü, hata mesajları, commit mesajları ve dokümantasyon **Türkçe** olmalıdır.
- **Test ve Denetim:** Yapılan her değişiklikten sonra `uv run pytest` ve `uv run ruff check .` çalıştırılmalı; testler firesiz geçmeli ve lint hatası bulunmamalıdır.
- **Tek Bilgi Kaynağı:** Projeye dair tüm kararlar ve yapısal değişiklikler bu dosyada (`CLAUDE.md`) güncellenerek kayıt altına alınır.
