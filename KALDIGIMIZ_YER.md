# Kaldığımız Yer (4 Kasım 2026 — Genel Hukuk Bürosu Uyarlaması)

Bu dosya, programı **herhangi bir hukuk bürosunun kullanabileceği genel amaçlı bir ürün** haline getirmek için başlattığımız **5 adımlı dönüşüm planında** kaldığımız noktayı ve tamamlanan/bekleyen adımları özetler.

---

## ✅ Tamamlanan Adımlar

### Adım 1: Genişletilmiş Kullanıcı Rolleri ve İsteğe Bağlı Yardımcı Sorumlu Yapısı (TAMAMLANDI)
- **7 Kullanıcı Rolü (`apps/accounts/models.py` — `accounts/0006`):**
  1. `admin` — **Yönetici**
  2. `senior` — **Kıdemli Avukat**
  3. `lawyer` — **Avukat**
  4. `intern` — **Stajyer Avukat**
  5. `paralegal` — **İcra Katibi / Takip Memuru**
  6. `secretary` — **Sekreter / Büro Yönetimi**
  7. `accountant` — **Muhasebe / Finans**
- **İsteğe Bağlı Yardımcı Sorumlu Ayarı (`OfficeSettings.use_assistant_assignee` — `office/0016`):**
  - `Ayarlar > Ofis bilgileri` ekranına **"Yardımcı sorumlu (stajyer / katip) kullan"** kutucuğu eklendi (varsayılan: `True`).
  - `False` seçiliyse müvekkil ve dosya formlarında/listelerinde/özetlerinde yardımcı sorumlu alanı gizlenir (`clients/0009`, `cases/0033`).

### Adım 2: Modüler Yetki ve Çalışma Düzeni Ayarları (`Ayarlar > Yetkiler ve çalışma düzeni` — TAMAMLANDI)
- **Dosya ve Müvekkil Görünürlüğü (`OfficeSettings.case_visibility_mode` + `User.can_view_all_cases` — `accounts/0007`, `office/0017`):**
  - `public` (Herkese açık) ve `restricted` (Sorumlu bazlı: Yönetici, Kıdemli Avukat, Sekreter, Muhasebe ve seçilen kişiler tümünü; Avukat, Stajyer ve Katip yalnızca sorumlu/görevli olduğu müvekkil ve dosyaları görür).
- **Görevlerde Kontrolcü Onayı İş Akışı (`OfficeSettings.task_review_mode` + `Task.reviewer` nullable — `tasks/0013`):**
  - `required` (Her zaman zorunlu), `assistants_only` (Yalnızca yardımcı personel için zorunlu; avukatlar doğrudan kapatabilir), `optional` (Kontrolcü isteğe bağlı; boşsa doğrudan kapanır).
- **Muhasebe Kaydı Ekleme ve İptal Etme Yetkisi (`OfficeSettings.accounting_edit_mode` + `User.can_manage_accounting`):**
  - `everyone` (Herkes ekleyebilir/iptal edebilir) ve `restricted` (Yalnızca Yönetici, Muhasebe rolü ve seçilen kişiler ekleyebilir/iptal edebilir).

---

## ⏳ Sıradaki Adım (Buradan Devam Edilecek)

### Adım 3: İlk Kurulum Sihirbazı (Onboarding) & Dinamik Ofis Kimliği
Kullanıcıya aşağıdaki **3 tasarım sorusu** soruldu, bu soruların yanıtlarıyla Adım 3'e başlanacak:

1. **İlk Kurulum Ekranı (Onboarding Sihirbazı):**
   - Veritabanında henüz hiç aktif kullanıcı yoksa (yeni kurulumda), giriş ekranı (`/hesap/giris/`) yerine otomatik olarak **"Hukuk Bürosu İlk Kurulum"** sayfası açılsın mı?
   - Bu ekranda tek adımda:
     - **Ofis Adı** (ve isteğe bağlı Telefon / Adres / Logo / Ofis Klasörü)
     - **Yardımcı sorumlu kullanılsın mı?** tercihi
     - **İlk Yönetici (Ad, Soyad, Unvan ve 4 haneli PIN)**
     alınıp kaydedilince doğrudan yönetici olarak oturum açılsın mı?
2. **Dosya ve Yedek İsimlendirmelerinin Dinamikleştirilmesi:**
   - Yedek dosyalarında (`ozkurt-yedek-20261104.zip`), toplu Excel dışa aktarımda (`ozkurt-guncel-listeler-....zip`), içe aktarım şablonunda (`ozkurt-aktarim-sablonu.xlsx`) ve varsayılan ofis adında sabit geçen `"ozkurt"` ifadeleri `OfficeSettings.name` değerinden otomatik üretilen kısa adla dinamikleştirilsin mi?
3. **`setup_office_users` Komutu:**
   - Mevcut `manage.py setup_office_users` komutu korunsun ama yeni kurulum betiğinde (`postinstall.ps1`) otomatik çalıştırılması yerine yeni ofisler kurulum sihirbazıyla kendi kullanıcılarını mı oluştursun?

---

## 📋 Kalan Adımlar (Adım 3'ten Sonra Tek Tek Yapılacak)

- **Adım 4: UYAP / UETS Tarayıcı Eklentisinde Dinamik Sunucu Adresi**
  - Eklenti ayarlarında ve eşleştirme ekranında sunucu adresinin (`http://127.0.0.1:3000` veya ofis yerel IP'si `http://192.168.x.x`) yapılandırılabilir olması.
- **Adım 5: Ofise Göre Özelleştirilebilir İş Kuralları**
  - UETS tebligat varsayılan süre gününün (`+14` gün) ve personel görev puanı sisteminin (`TaskPoint`) `Ayarlar > Ofis bilgileri / Görev türleri` üzerinden açılıp kapatılabilmesi veya değiştirilebilmesi.
