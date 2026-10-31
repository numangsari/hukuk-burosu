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
- "Ozkurt Hukuk Hatirlatma" beş dakikada bir görev, duruşma ve tebligat uyarılarını oluşturur. Sayfa açık olması gerekmez. Bu görev yeni kurulumda veya kurulum paketiyle güncellemede eklenir; geliştirme ortamında `uv run python manage.py send_reminders` elle çalıştırılabilir.
- İlk kurulumda masaüstüne **YEDEK PAROLASI** dosyası bırakılır: parola güvenli yerde saklanıp dosya silinmelidir.

## Güncelleme

Yeni sürümün kurulum dosyası aynı sunucuda çalıştırılır. Kurulum önce yedek alır, servisi durdurur,
dosyaları değiştirir, veritabanını günceller (`migrate`) ve servisi başlatır. Veriler ve `.env` korunur.

## Notlar

- Sunucuya sabit IP veya DHCP rezervasyonu verilmesi önerilir; kısayol bilgisayar adını kullanır (`http://SUNUCU-ADI/`).
- Yedek kopyası klasörü (Ayarlar > Yedekleme) için Google Drive'ın sanal `G:` sürücüsü değil, "yansıtma" modundaki gerçek klasör yolu seçilmelidir; servis SYSTEM hesabıyla çalışır.
- Ofis klasörü (Ayarlar > Belge klasörü) sunucunun yerel diski olmalıdır (ör. `D:\Ozkurt Hukuk Ofis`).
