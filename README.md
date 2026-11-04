# Hukuk Büro Yönetim Sistemi

Hukuk büroları için özel olarak tasarlanmış; dava, icra, müvekkil, görev, duruşma, fiziki arşiv, finans ve UYAP/UETS süreçlerini tek merkezden yöneten, yerel ağda (LAN) çalışan güvenli ve modern bir büro yönetim platformudur.

---

## 🏛️ Öne Çıkan Özellikler

### 1. Dava, İcra ve Safahat Takibi
- **9 Farklı Dosya Türü:** Hukuk, Ceza, İcra, İdari Yargı, Soruşturma, Arabuluculuk, İhtarname, Satış Memurluğu ve Danışmanlık/Sözleşme.
- **Akıllı Safahat Zinciri:** Aynı hukuki olaya bağlı dosyaları (ihtarname → arabuluculuk → dava → icra → istinaf vb.) tek bir akışta birleştirme ve ortak bakiye takibi.
- **Dinamik Aşama Yönetimi:** Dosya türüne özel aşamalar, sonuç/karar bilgileri ve icra dosyalarında tahsilat satırlarıyla kapatma.
- **Haciz Takibi:** Maaş, araç, tapu, banka ve 89/1-2-3 hacizleri için otomatik yenileme uyarısı ve görev üretimi.

### 2. Birleşik Takvim & Duruşma Yönetimi
- **3 Farklı Görünüm Modu:** Tek ekranda Ay Görünümü, Hafta Görünümü ve Liste/Duruşmalar Görünümü (`/takvim/`).
- **Duruşma ve Toplantı Takibi:** Duruşmaların yanı sıra dosyasız müvekkil randevuları, arabuluculuk görüşmeleri ve ofis içi toplantılar.
- **Otomatik Duruşma Görevi:** Duruşmadan 1 gün önce sabah dosya sorumlusuna otomatik görev açılır. Görev; duruşmaya girilmediyse *"Mazeret Gönderildi"*, girildiyse *"Duruşmada Verilen Kararlar"* ve *"Müvekkile Bilgi Verildi"* seçenekleriyle kapatılır.
- **Google Takvim API Entegrasyonu:** Sistemdeki duruşma ve randevular ofis Google Takvimi'ne tek yönlü (mükerrer kayıt yapmadan ve mevcut etkinliklere dokunmadan) otomatik aktarılır.
- **Excel Dökümü ve Hızlı Ara Karar:** Tek tıkla ara karar tutanağı girme ve duruşma listesini Excel olarak dışa aktarma.

### 3. Merkezi Fiziki Arşiv Modülü
- **Klasör Gezgini & Tablo Görünümü:** Açık, Kapalı ve İcra arşivlerini klasör ve dosya numarası bazında izleme (`/arsiv/`).
- **Boş Dosya Numarası Tespiti:** Klasör detayında atlanmış veya boşta kalan sıra numaralarını otomatik tespit ederek yeni dosyalara önerir.
- **Yazdırılabilir Arşiv Etiketleri:** A4 formatında standart klasör sırtlığı ve dosya kapak etiketlerini tarayıcıdan yazdırma.
- **Hızlı Konum Güncelleme:** Dosya detayına girmeden modal üzerinden tek tıkla arşiv yeri güncelleme.

### 4. Görev, Onay Döngüsü & Performans
- **Avukat - Stajyer Onay Döngüsü:** Görevler sorumlu ve kontrolcü arasında revizyon, onay ve belge yükleme adımlarıyla ilerler.
- **Esnek Çalışma Modları:** Ofis ayarlarına göre her görev için kontrolcü zorunlu tutulabilir, yalnızca stajyerler için zorunlu kılınabilir veya kontrolcü isteğe bağlı bırakılabilir.
- **Personel Görev Puanları:** Tamamlanan görev türlerine göre personel performans puanlaması.

### 5. UYAP & UETS Otomasyonu
- **Tarayıcı Eklentisi:** UYAP Avukat Portal ve UETS oturumlarıyla doğrudan haberleşen yerel tarayıcı eklentisi (`uyap-uets-deneme`).
- **Dosya, Taraf ve Duruşma Eşitleme:** UYAP'taki dosya bilgileri, taraf listeleri, duruşmalar ve icra dosya hesapları sisteme otomatik aktarılır.
- **Süreli Tebligat Görevleri:** UETS'ten gelen tebligatlardan otomatik yasal süre rozetleri hesaplanır ve tek tıkla görev oluşturulur.

### 6. Cari Hesap, Finans & Muhasebe
- **Müvekkil Cari Bakiyesi:** Masraf, vekalet ücreti, müvekkilden tahsilat, karşı taraftan tahsilat ve ödeme hareketleri.
- **Gelişmiş Yetkilendirme:** Finansal hareketleri herkes girip inceleyebilirken, kasa toplamları ve bakiyeler yalnızca yetkili kullanıcılara açıktır.

### 7. Güvenlik, Roller & İlk Kurulum
- **7 Personel Rolü:** Yönetici Avukat, Kıdemli Avukat, Avukat, Stajyer Avukat, İcra Katibi / Takip Memuru, Sekreter ve Muhasebe.
- **Hızlı PIN Girişi:** Kullanıcı adı/şifre yerine kullanıcı kartı seçilerek 4 haneli PIN ile hızlı giriş; otomatik oturum zaman aşımı.
- **İlk Kurulum Sihirbazı:** Sıfırdan temiz kurulumda büro adı, çalışma düzeni ve ilk yönetici hesabını tek adımda oluşturan sihirbaz (`/hesap/ilk-kurulum/`).
- **Audit Log:** Sistemdeki tüm işlemler `django-auditlog` ile kullanıcı, tarih ve değişiklik detaylarıyla kayıt altındadır.

---

## 🛠️ Teknoloji Mimarisi

- **Backend:** Python 3.13, Django 5.2 LTS
- **Veritabanı:** PostgreSQL 17
- **Frontend:** HTMX 2, Alpine.js 3, Bootstrap 5.3 (CDN kullanılmaz; tüm statik varlıklar yerel sunulur)
- **Paket Yönetimi:** `uv`
- **Statik Dosya & Önbellek:** WhiteNoise
- **Raporlama:** OpenPyXL (Excel), ReportLab (Türkçe karakter destekli DejaVu Sans fontlu PDF)

---

## 🚀 Geliştirme Ortamı Kurulumu

### Gereksinimler
- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop (Geliştirme PostgreSQL veritabanı için)

### Adım Adım Kurulum

1. **Bağımlılıkları Yükleyin:**
   ```bash
   uv sync
   ```

2. **Geliştirme Veritabanını Başlatın:**
   ```bash
   docker compose -f docker-compose.dev.yml up -d
   ```

3. **Veritabanı Şemasını Uygulayın:**
   ```bash
   uv run python manage.py migrate
   ```

4. **Örnek Ofis Kullanıcılarını Oluşturun:**
   ```bash
   uv run python manage.py setup_office_users --pin 1234
   ```
   *(Varsayılan kullanıcılar: `yonetici.avukat`, `avukat.ayse`, `avukat.mehmet`, `stajyer.can`, `katip.murat`, `sekreter.fatma`)*

5. **Geliştirme Sunucusunu Başlatın:**
   ```bash
   uv run python manage.py runserver 0.0.0.0:8000
   ```
   Tarayıcınızdan `http://localhost:8000` adresine gidebilirsiniz.

6. **Testleri ve Kod Denetimini Çalıştırın:**
   ```bash
   uv run pytest
   uv run ruff check .
   ```

---

## 📦 Production Dağıtımı (Windows Servisi)

Uygulama, yerel bir Windows sunucu bilgisayarında internet bağlantısı gerektirmeden çalışacak şekilde paketlenmiştir:
- **Kurulum Paketi:** Inno Setup 6 ile derlenen `installer/HukukBurosu.iss` (`HukukBuro-Kurulum-x.x.x.exe`).
- **Servis Yapısı:** WinSW ile yönetilen iki bağımsız Windows servisi:
  - `HukukBuroDB`: İzole PostgreSQL 17 veritabanı servisi.
  - `HukukBuroApp`: Waitress WSGI sunucusu üzerinden port 80'de çalışan web uygulaması servisi.
- **Otomatik Yedekleme:** Windows Görev Zamanlayıcı ile her gün otomatik olarak parolasız `.zip` yedeği alınır.

---

## 📄 Lisans
Bu proje tescilli ve özel kullanım lisansına tabidir. Tüm hakları saklıdır.
