# Kaldığımız Yer (4 Kasım 2026 — Takvim/Duruşmalar & Fiziki Arşiv Entegrasyonu)

Bu dosya, programın güncel durumunu, tamamlanan modülleri ve mimari kararları özetler.

---

## 🏛️ Yeni Eklenen & Birleştirilen Modüller

### 1. Birleşik Takvim & Duruşmalar Modülü (`/takvim/`)
Kullanıcı talimatı doğrultusunda **Duruşmalar ve Takvim tek modülde birleştirildi**. Yan menüde tek bir başlık yer alır: **Takvim** (`bi-calendar3`).
- **Tek Sayfada 3 Görünüm Seçeneği (`/takvim/`):**
  1. **Ay Görünümü (`view=month`):** Google Takvim etkinlikleri ve açık görevlerin son günlerini ızgara takvim üzerinde gösterir.
  2. **Hafta Görünümü (`view=week`):** Saatlik ve günlük detaylı haftalık ajanda görünümü.
  3. **Liste / Duruşmalar Görünümü (`view=list`):** Tüm duruşma ve ofis etkinliklerini filtreli tablo olarak sunar:
     - Sekmeler: *Yaklaşan Duruşmalar* (`scope=upcoming`), *Bugün* (`scope=today`), *Sonuç / Ara Karar Bekleyenler* (`scope=pending_result`), *Geçmiş* (`scope=past`) ve *Tümü* (`scope=all`).
     - Hızlı arama, sorumlu, tür ve durum filtreleri.
     - Tek tıkla *Ara Karar / Sonuç Tutanağı Girme* modalı.
     - Excel Dökümü indirme (`/durusmalar/disa-aktar/`).
- **Dosyasız Müvekkil Görüşmeleri & Toplantılar Desteği:**
  - `Hearing` modeli genişletildi (`case=None` desteği, `client`, `title`, `assigned_to`, `ends_at`).
  - Dosyası henüz açılmamış müvekkillerle yapılan görüşmeler, arabuluculuk oturumları veya ofis içi toplantılar doğrudan kaydedilebilir.
- **Otomatik Duruşma Görevi Servisi (`apps/cases/hearing_tasks.py`):**
  - **Duruşmadan 1 gün önce sabah** (ve duruşma günü) dosya sorumlusuna otomatik kontrolcüsüz (`reviewer=None`, doğrudan kapatılabilen) görev açılır:
    `"{case.display_name} DURUŞMASI İŞLEMLERİ YAPILACAK VE MÜVEKKİLE BİLGİ VERİLECEK"`
  - Görev `task.hearing` alanıyla duruşmaya bağlanır ve mükerrer görev açılması engellenir.
- **Özel Duruşma Görevi Kapatma Prosedürü (`apps/tasks/services.py` & `templates/tasks/detail.html`):**
  - Duruşma görevini kapatırken kullanıcıya iki seçenek sunulur:
    1. **"Mazeret Gönderildi (Duruşmaya Girilmedi)":** Mazeret açıklaması girilir; `Hearing.excuse_submitted = True` ve `Hearing.status = POSTPONED` olur, dosya zaman çizelgesine (`CaseEvent`) mazeret sunulduğu işlenir.
    2. **"Duruşmaya Girildi":** "Duruşmada Verilen Kararlar" zorunlu olarak doldurulur; "Müvekkile Bilgi Verildi mi?" (Evet / Hayır; Hayır ise sebebi zorunlu) seçilir. Bilgiler duruşma kaydına (`decisions`, `client_informed`, `client_not_informed_reason`) ve dosya zaman çizelgesine (`CaseEvent`) otomatik işlenir.
- **Google Takvim API Tek Yönlü Entegrasyonu (`apps/agenda/google_sync.py`):**
  - Kullanıcı ofis ayarlarından (`OfficeSettings`) Google Takvim API'yi bağladığında sistem tüm duruşma ve toplantıları Google Takvim'e tek yönlü olarak aktarır ve günceller.
  - **Kritik Güvenlik İlkesi:** Google Takvim'deki harici / mevcut etkinliklere asla dokunulmaz, silinmez veya değiştirilmez. Veri akışı %100 tek yönlüdür ve `google_event_id` üzerinden mükerrer kayıtlar engellenir.

---

### 2. Fiziki Arşiv Modülü (`/arsiv/`)
- **Merkezi Fiziki Arşiv ve Klasör Yönetimi (`apps/cases/views_archive.py`):**
  - Sekmeler: *Tümü* (`scope=all`), *Açık Arşiv* (`scope=open`), *Kapalı Arşiv* (`scope=closed`), *İcra Arşivi* (`scope=enforcement`), *Arşiv Yeri Eksikler* (`scope=missing` — özellikle UYAP'tan yeni çekilen ve henüz fiziki yeri verilmemiş dosyalar).
  - İki Görünüm Modu:
    1. **Tablo Görünümü:** Klasör No, Dosya No, birleşik arşiv referansı (`Açık 1 / 10`), kurum, müvekkil, durum, açılış tarihi ve hızlı düzenle butonu.
    2. **Klasör Gezgini (`view=explorer`):** Bürodaki 168 fiziki klasörün kartlar halinde gösterimi, içindeki dosya sayıları ve açık/kapalı dağılımı.
- **Klasör Detayı ve Boş Numara Tespiti (`/arsiv/klasor/<folder_name>/`):**
  - Klasör içindeki dosyaları sıra numarasına göre dizer.
  - **Boşta / Atlanmış Dosya Numaralarını** otomatik tespit eder (Örn: 1 ve 3 doluysa "2 numaralı dosya boşta" uyarısı verir ve sıradaki yeni numarayı önerir).
- **Hızlı Arşiv Yeri Güncelleme:**
  - Dosyayı baştan sona açmadan modal pencerede tek tıkla klasör no ve dosya no güncelleme imkânı.
- **Yazdırılabilir Arşiv Etiketleri (`/arsiv/etiketler/`):**
  - `@media print` A4 şablonunda standart **Klasör Sırtlığı** (`tip=folder`) ve **Dosya Kapak Etiketi** (`tip=case`) yazdırma desteği.
- **Excel Dışa Aktarım (`/arsiv/disa-aktar/`):**
  - Tüm arşiv envanterini Excel tablosu olarak indirme.

---

## 🎯 Doğrulama ve Test Durumu
- `uv run pytest`: **567 testin 567'si de eksiksiz geçti.**
- `uv run ruff check .`: **Sıfır hata, tertemiz kod.**
- Dev sunucusu arka planda canlı çalışıyor (`http://0.0.0.0:8000/`).
