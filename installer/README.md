# Windows kurulum paketi — Hukuk Bürosu Otomasyonu

Ofis sunucusu (Windows PC) için tek dosyalık kurulum: `HukukBurosuOtomasyonu-Kurulum-<sürüm>.exe`.
Diğer PC'lere kurulum yapılmaz; sunucunun masaüstündeki `Hukuk Bürosu Otomasyonu.url` kısayolu kopyalanır.

**Sürüm:** Tek kaynak `pyproject.toml` içindeki `version`. Paket derlenirken uygulamaya `VERSION` dosyası yazılır; kurulu sürüm Ayarlar > Sistem > Sistem monitörü'nde görünür. Her yeni pakette `version` artırılır.

**Adlar:** Görünen ad "Hukuk Bürosu Otomasyonu". Eski kurulumların güncellenebilmesi için `AppId`, kurulum klasörü (yeni kurulumda `C:\HukukBurosu`; güncellemede önceki klasör kullanılır), servis adları (`HukukBuroApp`, `HukukBuroDB`; eski kurulumda `OzkurtHukuk*`) ve zamanlanmış görev adları (`Hukuk Buro ...`) değiştirilmez.

## Paketi üretmek (geliştirici makinesi)

1. Inno Setup 6'yı kurun: `winget install JRSoftware.InnoSetup`
2. Proje kökünde: `powershell -ExecutionPolicy Bypass -File installer\build.ps1` (sürüm `pyproject.toml`'dan okunur; `-Version` ile ezilebilir)
3. Çıktı: `installer\dist\HukukBurosuOtomasyonu-Kurulum-<sürüm>.exe`

`build.ps1`; gömülü Python'u (python.org), PostgreSQL Windows binary'lerini (EDB), WinSW'yi (GitHub)
ve Visual C++ çalışma kütüphanesini (`vc_redist.x64.exe`, Microsoft; PostgreSQL temiz Windows'ta bunsuz açılmaz)
indirir, `installer\cache\` altında saklar ve SHA256 değerlerini `build\indirilenler.txt`'ye yazar.
`HukukBurosu.iss` UTF-8 (BOM'lu) kalmalıdır; aksi halde Türkçe karakterler bozulur.

## Kurulum (ofis sunucusu)

- Yönetici olarak `HukukBurosuOtomasyonu-Kurulum-*.exe` çalıştırılır, ilk kurulumda varsayılan PIN sorulur.
- Dosyalar kopyalandıktan sonra kurulum önce Visual C++ çalışma kütüphanesini sessizce kurar, ardından `tools\postinstall.ps1`'i çalıştırır. İkisinden biri başarısız olursa hata penceresi çıkar ve "Sistemi tarayıcıda aç" seçeneği gösterilmez; ayrıntı `logs\kurulum.log` içindedir.
- Kurulum `C:\HukukBurosu` altına yapılır (güncellemede mevcut klasör kullanılır):
  - `app\` uygulama, `.env` (gizli anahtarlar; yalnızca yöneticiler okuyabilir)
  - `python\`, `pgsql\` gömülü çalışma ortamı
  - `data\pgdata` veritabanı, `data\media` belgeler, `data\backups` yedekler (kaldırmada silinmez)
  - `tools\` servis, yedek ve geri yükleme betikleri, `logs\` kayıtlar
- Servisler: `HukukBuroDB` (PostgreSQL, yalnızca 127.0.0.1) ve `HukukBuroApp` (port 80). PC açılınca kendiliğinden başlar.
- Güvenlik duvarı: port 80 yalnızca Özel/Etki alanı ağ profili için açılır. Ofis ağının Windows'ta "Özel ağ" olarak işaretli olması gerekir.
- Görev Zamanlayıcı: "Hukuk Buro Yedek" 30 dakikada bir çalışır, Ayarlar'daki saatte günde bir yedek alır.
- "Hukuk Buro Listeler" görevi, uygulama açıkken ofis klasöründeki görüntüleme tablolarını düzenli yeniler; dosyalar üzerinde yapılan değişiklikler sisteme aktarılmaz.
- WhatsApp bağlantısı ve duruşma takibi kullanım dışıdır. Kurulum/güncelleme eski hatırlatma görevini kaldırır; gönderim komutu mesaj göndermez. `Hukuk Buro Haciz Takibi` (eski kurulumlarda `Ozkurt Hukuk Haciz Takibi`) başlangıçta ve beş dakikada bir `check-reminders.ps1` çalıştırır: `create_seizure_tasks` ile haciz yenileme görevlerini, `create_routine_tasks` ile günü gelen rutin görevleri oluşturur, ardından `retry_google_sync` ile başarısız Google Takvim eşitlemelerini yeniden dener (API kapalıysa bir şey yapmaz).
- Yeni yedekler parolasızdır; ofis klasörüne erişimi yalnızca yetkili kişilerle sınırlayın. Eski parolalı yedeklerin parolası korunmalıdır.

## Güncelleme

Yeni sürümün kurulum dosyası aynı sunucuda çalıştırılır. Kurulum önce yedek alır, servisi durdurur,
dosyaları değiştirir, veritabanını günceller (`migrate`) ve servisi başlatır. Veriler ve `.env` korunur.
Eski masaüstü kısayolları (`Hukuk Buro Yonetimi.url`, `Ozkurt Hukuk.url`) silinir, yenisi oluşturulur.

## Gerçek kurulum denemesi (elle, ayrı Windows makinede)

Betikler sözdizimi ve sahte servisle sınanır; gerçek servis, zamanlanmış görev ve port 80 ile aşağıdaki liste elle denenmelidir (üretim sunucusunda değil, temiz bir deneme makinesinde):

1. Temiz kurulum: `HukukBuroApp` ve `HukukBuroDB` servisleri çalışıyor mu, `http://BILGISAYAR-ADI/` açılıyor mu, Programlar listesinde ad "Hukuk Bürosu Otomasyonu" mu, Sistem monitöründe sürüm doğru mu?
2. `.env` içindeki `DJANGO_ALLOWED_HOSTS` bilgisayar adı ve IPv4'leri içeriyor mu (`*` yok mu)?
3. Başka bir bilgisayardan adresle giriş yapılabiliyor mu; Ayarlar > Erişim adresleri uyarısı doğru mu?
4. `Hukuk Buro Haciz Takibi` görevi var ve `check-reminders.ps1` çalıştırınca `create_seizure_tasks` ile `retry_google_sync` çağrılıyor mu (uygulama servisi kapalıyken bir şey yapmamalı)?
5. Eski sürümden güncelleme: aynı klasöre kuruluyor mu, `Ozkurt*` servis ve görev adları korunuyor mu, veri ve `.env` aynı mı, masaüstünde yalnızca yeni kısayol mu var?
6. Kaldırma (`uninstall.ps1`): servisler, görevler ve kısayollar siliniyor, veri klasörü duruyor mu?

## Notlar

- Sunucuya sabit IP veya DHCP rezervasyonu verilmesi önerilir; kısayol bilgisayar adını kullanır (`http://SUNUCU-ADI/`).
- Ofis klasörü (Ayarlar > Ofis klasörü) sunucunun yerel diski olmalıdır (ör. `D:\Hukuk Burosu Ofis`); servis SYSTEM hesabıyla çalışır. Klasördeki Müvekkiller, Şablon Dilekçeler ve Yedekler bir bulut hizmetiyle ayrıca yedeklenebilir.
