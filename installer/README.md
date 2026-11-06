# Windows kurulum paketi

Ofis sunucusu (Windows PC) için tek dosyalık kurulum: `OzkurtHukuk-Kurulum-<sürüm>.exe`.
Diğer PC'lere kurulum yapılmaz; sunucunun masaüstündeki `Ozkurt Hukuk.url` kısayolu kopyalanır.

## Paketi üretmek (geliştirici makinesi)

1. Inno Setup 6'yı kurun: `winget install JRSoftware.InnoSetup`
2. Proje kökünde: `powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Version 1.0.0`
3. Çıktı: `installer\dist\OzkurtHukuk-Kurulum-1.0.0.exe`

`build.ps1`; gömülü Python'u (python.org), PostgreSQL Windows binary'lerini (EDB), WinSW'yi (GitHub)
indirir, `installer\cache\` altında saklar ve SHA256 değerlerini `build\indirilenler.txt`'ye yazar.

## Kurulum (ofis sunucusu)

- Yönetici olarak `OzkurtHukuk-Kurulum-*.exe` çalıştırılır, ilk kurulumda varsayılan PIN sorulur.
- Kurulum `C:\OzkurtHukuk` altına yapılır:
  - `app\` uygulama, `.env` (gizli anahtarlar; yalnızca yöneticiler okuyabilir)
  - `python\`, `pgsql\` gömülü çalışma ortamı
  - `data\pgdata` veritabanı, `data\media` belgeler, `data\backups` yedekler (kaldırmada silinmez)
  - `tools\` servis, yedek ve geri yükleme betikleri, `logs\` kayıtlar
- Servisler: `OzkurtHukukDB` (PostgreSQL, yalnızca 127.0.0.1) ve `OzkurtHukukApp` (port 80). PC açılınca kendiliğinden başlar.
- Güvenlik duvarı: port 80 yalnızca Özel/Etki alanı ağ profili için açılır. Ofis ağının Windows'ta "Özel ağ" olarak işaretli olması gerekir.
- Görev Zamanlayıcı: "Ozkurt Hukuk Yedek" 30 dakikada bir çalışır, Ayarlar'daki saatte günde bir yedek alır.
- "Ozkurt Hukuk Listeler" görevi, uygulama açıkken ofis klasöründeki görüntüleme tablolarını düzenli yeniler; dosyalar üzerinde yapılan değişiklikler sisteme aktarılmaz.
- WhatsApp bağlantısı ve duruşma takibi kullanım dışıdır. Kurulum/güncelleme eski hatırlatma görevini kaldırır; gönderim komutu mesaj göndermez. `Hukuk Buro Haciz Takibi` (eski kurulumlarda `Ozkurt Hukuk Haciz Takibi`) başlangıçta ve beş dakikada bir `check-reminders.ps1` çalıştırır: `create_seizure_tasks` ile haciz yenileme görevlerini oluşturur, ardından `retry_google_sync` ile başarısız Google Takvim eşitlemelerini yeniden dener (API kapalıysa bir şey yapmaz).
- Yeni yedekler parolasızdır; ofis klasörüne erişimi yalnızca yetkili kişilerle sınırlayın. Eski parolalı yedeklerin parolası korunmalıdır.

## Güncelleme

Yeni sürümün kurulum dosyası aynı sunucuda çalıştırılır. Kurulum önce yedek alır, servisi durdurur,
dosyaları değiştirir, veritabanını günceller (`migrate`) ve servisi başlatır. Veriler ve `.env` korunur.

## Notlar

- Sunucuya sabit IP veya DHCP rezervasyonu verilmesi önerilir; kısayol bilgisayar adını kullanır (`http://SUNUCU-ADI/`).
- Ofis klasörü (Ayarlar > Ofis klasörü) sunucunun yerel diski olmalıdır (ör. `D:\Ozkurt Hukuk Ofis`); servis SYSTEM hesabıyla çalışır. Klasördeki Müvekkiller, Şablon Dilekçeler ve Yedekler bir bulut hizmetiyle ayrıca yedeklenebilir.
