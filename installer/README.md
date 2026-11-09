# Windows kurulum paketi — Hukuk Bürosu Otomasyonu

Ofis sunucusu (Windows PC) için tek dosyalık kurulum: `HukukBurosuOtomasyonu-Kurulum-<sürüm>.exe`.
Diğer PC'lere kurulum yapılmaz; sunucunun masaüstündeki `Hukuk Bürosu Otomasyonu.url` kısayolu kopyalanır.

**Sürüm:** Tek kaynak `pyproject.toml` içindeki `version`. Paket derlenirken uygulamaya `VERSION` dosyası yazılır; kurulu sürüm Ayarlar > Program > Hakkında ve Sistem monitörü'nde görünür. Her yeni pakette `version` artırılır.

**Adlar:** Görünen ad "Hukuk Bürosu Otomasyonu". Eski kurulumların güncellenebilmesi için `AppId`, servis adları (`HukukBuroApp`, `HukukBuroDB`; eski kurulumda `OzkurtHukuk*`) ve zamanlanmış görev adları (`Hukuk Buro ...`) değiştirilmez; güncellemede önceki kurulum klasörü kullanılır.

## Paketi üretmek (geliştirici makinesi)

1. Inno Setup 6'yı kurun: `winget install JRSoftware.InnoSetup`
2. Proje kökünde: `powershell -ExecutionPolicy Bypass -File installer\build.ps1` (sürüm `pyproject.toml`'dan okunur; `-Version` ile ezilebilir)
3. Çıktı: `installer\dist\HukukBurosuOtomasyonu-Kurulum-<sürüm>.exe`

`build.ps1`; gömülü Python'u (python.org), PostgreSQL Windows binary'lerini (EDB), WinSW'yi (GitHub)
ve Visual C++ çalışma kütüphanesini (`vc_redist.x64.exe`, Microsoft; PostgreSQL temiz Windows'ta bunsuz açılmaz)
indirir, `installer\cache\` altında saklar ve SHA256 değerlerini `build\indirilenler.txt`'ye yazar.
`HukukBurosu.iss` UTF-8 (BOM'lu) kalmalıdır; aksi halde Türkçe karakterler bozulur.

## Kurulum (ofis sunucusu)

- Yönetici olarak `HukukBurosuOtomasyonu-Kurulum-*.exe` çalıştırılır. Kurulum soru sormaz; ilk açılışta tarayıcıdaki İlk Kurulum ekranında büro bilgileri ve ilk yöneticinin PIN'i girilir.
- Dosyalar kopyalandıktan sonra kurulum önce Visual C++ çalışma kütüphanesini sessizce kurar, ardından `tools\postinstall.ps1`'i çalıştırır. İkisinden biri başarısız olursa hata penceresi çıkar ve "Sistemi tarayıcıda aç" seçeneği gösterilmez; ayrıntı `<veri>\logs\kurulum.log` içindedir.
- **Program** `C:\Program Files\HukukBurosu` altına kurulur (herkes okur, yalnızca yöneticiler yazar):
  - `app\` uygulama, `.env` (gizli anahtarlar; yalnızca Administrators ve SYSTEM okuyabilir)
  - `python\`, `pgsql\` gömülü çalışma ortamı
  - `tools\` servis, yedek, geri yükleme ve güncelleme betikleri
  - `eklenti\` UYAP/UETS tarayıcı eklentisi (ana bilgisayarda Chrome'a paketlenmemiş olarak yüklenir)
- **Veri** (`<veri>` = `C:\ProgramData\HukukBurosu`; `.env`'de `DATA_DIR`) yalnızca Administrators ve SYSTEM'e açıktır, kaldırmada silinmez:
  - `pgdata\` veritabanı (servis NetworkService ile çalıştığından ona ayrıca yazma izni verilir), `media\` belgeler, `backups\` yedekler, `updates\` otomatik güncelleme, `logs\` kayıtlar
- Eski düzende (`C:\HukukBurosu\data\pgdata` varsa) kurulu sistem güncellenirse aynı klasörde kalır; program klasörlerinin izinleri yine daraltılır.
- Servisler: `HukukBuroDB` (PostgreSQL, yalnızca 127.0.0.1) ve `HukukBuroApp` (port 80). PC açılınca kendiliğinden başlar.
- Güvenlik duvarı: port 80 yalnızca Özel/Etki alanı ağ profili için açılır. Ofis ağının Windows'ta "Özel ağ" olarak işaretli olması gerekir.
- Görev Zamanlayıcı: "Hukuk Buro Yedek" 30 dakikada bir çalışır, Ayarlar'daki saatte günde bir yedek alır.
- "Hukuk Buro Listeler" görevi, uygulama açıkken ofis klasöründeki görüntüleme tablolarını düzenli yeniler; dosyalar üzerinde yapılan değişiklikler sisteme aktarılmaz.
- WhatsApp bağlantısı ve duruşma takibi kullanım dışıdır. Kurulum/güncelleme eski hatırlatma görevini kaldırır; gönderim komutu mesaj göndermez. `Hukuk Buro Haciz Takibi` (eski kurulumlarda `Ozkurt Hukuk Haciz Takibi`) başlangıçta ve beş dakikada bir `check-reminders.ps1` çalıştırır: `create_seizure_tasks` ile haciz yenileme görevlerini, `create_routine_tasks` ile günü gelen rutin görevleri oluşturur, ardından `retry_google_sync` ile başarısız Google Takvim eşitlemelerini yeniden dener (API kapalıysa bir şey yapmaz).
- Yeni yedekler parolasızdır; ofis klasörüne erişimi yalnızca yetkili kişilerle sınırlayın. Eski parolalı yedeklerin parolası korunmalıdır.

## Güncelleme

Yeni sürümün kurulum dosyası aynı sunucuda çalıştırılır. Kurulum önce yedek alır (yedek alınamazsa
sessiz kurulum durur), uygulama ve veritabanı servislerini durdurur, dosyaları değiştirir, veritabanını
günceller (`migrate`) ve servisleri başlatır. Veriler ve `.env` korunur.
Eski masaüstü kısayolları (`Hukuk Buro Yonetimi.url`, `Ozkurt Hukuk.url`) silinir, yenisi oluşturulur.

### Otomatik güncelleme (`tools\updater.ps1`)

Kaynak kod private repoda kalır; kurulum paketleri ayrı **public** repoda yayınlanır
(`numangsari/hukuk-burosu-releases`, etiket `v<sürüm>`, dosyalar `HukukBurosuOtomasyonu-Kurulum-<sürüm>.exe`
ve `.exe.sha256`). Yayınlama: `build.ps1` (`.sha256` dosyasını da üretir), ardından
`powershell -ExecutionPolicy Bypass -File installer\publish-release.ps1 -Notes "..."`.

- **Kontrol** — "Hukuk Buro Guncelleme Kontrol" görevi her gün 12:00'de (PC kapalıysa ilk açılışta)
  son sürüme bakar. Daha yeniyse ve `<veri>\updates\bad-versions.txt`'de yoksa paketi indirir, SHA256 ile
  doğrular, `<veri>\updates\pending.json` yazar. Kurulum yapmaz. İnternet yoksa sessizce çıkar.
- **Kurulum** — "Hukuk Buro Guncelleme" görevi bilgisayar açılışında bekleyen sürümü kurar:
  veritabanına dokunan görevleri durdurur, uygulama servisini durdurur, `app`, `python`, `tools`
  klasörlerinin ve veritabanının (`pg_dump`) anlık kopyasını `<veri>\updates\rollback\` altına alır,
  port 80'de "Güncelleniyor" sayfasını açar (`maintenance.py`, kopyadaki Python ile), paketi
  `/VERYSILENT /DEFERSTART=1` ile çalıştırır, servisi başlatıp `/saglik/` adresinden yeni sürümü doğrular.
- **Geri dönüş** — Kurulum çıkış kodu sıfır değilse veya sağlık kontrolü 4 dakikada geçmezse klasörler
  ve veritabanı (drop + `pg_restore`) anlık kopyadan geri yüklenir, önceki sürüm başlatılır ve sürüm
  `bad-versions.txt`'ye yazılır; daha yeni bir sürüm yayınlanana kadar tekrar denenmez. Kuruluma
  geçilmeden önce (ör. kopya alınamadı) hata olursa hiçbir şey değişmez, sonraki açılışta yeniden denenir.
- Sonuç `<veri>\updates\status.json`'a yazılır ve Ayarlar > Hakkında'da görünür; ayrıntı
  `<veri>\logs\guncelleme.log` ve `guncelleme-kurulum-<sürüm>.log`. `<veri>\updates` yalnızca
  Administrators ve SYSTEM tarafından okunabilir (anlık kopya `.env` ve veritabanını içerir).
- **Sınır:** PostgreSQL ana sürüm yükseltmesi (ör. 17 → 18) otomatik güncellemeyle yapılmaz; `pgsql`
  klasörü anlık kopyaya alınmaz.

## Gerçek kurulum denemesi (elle, ayrı Windows makinede)

Betikler sözdizimi ve sahte servisle sınanır; gerçek servis, zamanlanmış görev ve port 80 ile aşağıdaki liste elle denenmelidir (üretim sunucusunda değil, temiz bir deneme makinesinde):

1. Temiz kurulum: `HukukBuroApp` ve `HukukBuroDB` servisleri çalışıyor mu, `http://BILGISAYAR-ADI/` açılıyor mu, Programlar listesinde ad "Hukuk Bürosu Otomasyonu" mu, Sistem monitöründe sürüm doğru mu?
2. `.env` içindeki `DJANGO_ALLOWED_HOSTS` bilgisayar adı ve IPv4'leri içeriyor mu (`*` yok mu)?
3. Başka bir bilgisayardan adresle giriş yapılabiliyor mu; Ayarlar > Erişim adresleri uyarısı doğru mu?
4. `Hukuk Buro Haciz Takibi` görevi var ve `check-reminders.ps1` çalıştırınca `create_seizure_tasks` ile `retry_google_sync` çağrılıyor mu (uygulama servisi kapalıyken bir şey yapmamalı)?
5. Eski sürümden güncelleme: aynı klasöre kuruluyor mu, `Ozkurt*` servis ve görev adları korunuyor mu, veri ve `.env` aynı mı, masaüstünde yalnızca yeni kısayol mu var?
6. Kaldırma (`uninstall.ps1`): servisler, görevler ve kısayollar siliniyor, veri klasörü duruyor mu?
7. Otomatik güncelleme: test releases reposuna daha yeni sürüm yükleyip `updater.ps1 -Mode Check` çalıştırın, PC'yi yeniden başlatın; "Güncelleniyor" sayfası çıkıyor, yeni sürüm açılıyor, Hakkında'da "Güncelleme başarılı" görünüyor mu?
7b. Güncelleme sırasında ağdaki başka bir bilgisayardan "Güncelleniyor" sayfası görünüyor mu ve sunucuda güvenlik duvarı izni sorulmuyor mu (port 80 kuralı bakım sayfasını da kapsamalı)?
8. Geri dönüş: bilerek bozuk bir sürüm yayınlayın (ör. `/saglik/` hata veren); açılışta önceki sürüme ve verilere dönülüyor, Hakkında'da uyarı çıkıyor, sürüm bir daha denenmiyor mu?

## Notlar

- Sunucuya sabit IP veya DHCP rezervasyonu verilmesi önerilir; kısayol bilgisayar adını kullanır (`http://SUNUCU-ADI/`).
- Ofis klasörü (Ayarlar > Ofis klasörü) sunucunun yerel diski olmalıdır (ör. `D:\Hukuk Burosu Ofis`); servis SYSTEM hesabıyla çalışır. Klasördeki Müvekkiller, Şablon Dilekçeler ve Yedekler bir bulut hizmetiyle ayrıca yedeklenebilir.
