# Kurulum Rehberi — Hukuk Bürosu Otomasyonu

Bu rehber programı bir büroya sıfırdan kurmak içindir. Teknik bilgi gerektirmez; adımları sırayla izleyin.

## 1. Neye ihtiyacınız var?

- **Ana bilgisayar (sunucu):** Büroda **sürekli açık kalacak** bir Windows 10 veya 11 bilgisayar (64 bit). Program bu bilgisayara kurulur; diğer bilgisayarlar ona tarayıcıyla bağlanır.
  - En az 8 GB bellek, 50 GB boş disk önerilir (belgeler arttıkça disk ihtiyacı büyür).
  - Gece kapatılabilir; açılınca program kendiliğinden başlar.
- **Diğer bilgisayarlar:** Yalnızca güncel bir tarayıcı (Chrome veya Edge). Kurulum yapılmaz.
- **Ağ:** Bütün bilgisayarlar aynı ofis ağında (aynı modem/switch) olmalı. Ana bilgisayara modemden **sabit IP** (DHCP rezervasyonu) verilmesi önerilir.
- **Kurulum dosyası:** `HukukBurosuOtomasyonu-Kurulum-<sürüm>.exe` (en son sürüm: https://github.com/numangsari/hukuk-burosu-releases/releases).
- Ana bilgisayarda **yönetici (administrator)** hesabıyla oturum.

## 2. Kurulum (ana bilgisayarda)

1. Kurulum dosyasına sağ tıklayın > **Yönetici olarak çalıştır**.
2. Windows "bilinmeyen yayımcı" uyarısı verirse **Ek bilgi > Yine de çalıştır** deyin.
3. **İleri > Kur** ile devam edin. Kurulum birkaç dakika sürer ve soru sormaz.
4. Bitince **Sistemi tarayıcıda aç** işaretliyken **Son**'a basın.

Kurulum hata verirse ekrandaki mesajı ve `C:\ProgramData\HukukBurosu\logs\kurulum.log` dosyasını saklayın; destek için bu dosya gerekir.

Kurulum şunları kendiliğinden yapar: veritabanı ve uygulama servislerini kurar (bilgisayar açılınca kendiliğinden çalışır), güvenlik duvarında ofis ağı için 80 numaralı portu açar, günlük yedek ve otomatik güncelleme görevlerini oluşturur, masaüstüne **Hukuk Bürosu Otomasyonu** kısayolunu koyar.

## 3. İlk kurulum ekranı

Tarayıcıda açılan **İlk Kurulum** ekranında:

1. **Büro bilgileri:** büro adı, telefon ve adres (telefon ve adres isteğe bağlı).
2. **Ofis belge klasörü:** belgelerin düzenli tutulacağı klasör, ör. `D:\Hukuk Burosu Ofis`. Ana bilgisayarın **kendi diskinde** olmalı (ağ sürücüsü değil). Sonra Ayarlar'dan da girilebilir.
3. **Çalışma düzeni:** stajyer/katip gibi yardımcı sorumlu kullanılıp kullanılmayacağı.
4. **İlk yönetici:** adınız, soyadınız, unvanınız ve **4 haneli PIN**'iniz. Bu hesap tam yetkilidir; PIN'i unutmayın.

**Kurulumu tamamla** deyince ana sayfaya girersiniz.

## 4. İlk ayarlar (yönetici)

Sol menüde **Ayarlar**'dan:

1. **Kullanıcılar:** her çalışanı ekleyin (ad, soyad, rol, ilk PIN). Roller: Yönetici Avukat, Kıdemli Avukat, Avukat, Stajyer, İcra Katibi, Sekreter, Muhasebe. Çalışan ilk girişte kendi PIN'ini belirler.
2. **Ofis bilgileri:** logo, banka bilgileri (WhatsApp mesajlarında kullanılır), oturum zaman aşımı.
3. **Ofis klasörü:** belge klasörü ve günlük yedek saati. Yedeklerin bir kopyasını ayrıca harici diske veya buluta almanız önerilir.
4. **Yetkiler ve çalışma düzeni:** hangi rolün neyi görüp yapabileceği (varsayılanlar çoğu büroya uygundur).
5. **Görev türleri:** büronuza özel görev türleri ve puanları.
6. **Google Takvim** (isteğe bağlı): duruşmaların büro takvimine aktarılması.

## 5. Diğer bilgisayarlardan bağlanma

1. Ana bilgisayarın masaüstündeki **Hukuk Bürosu Otomasyonu** kısayolunu (USB veya ağ üzerinden) diğer bilgisayarların masaüstüne kopyalayın. Ya da tarayıcıya `http://ANA-BILGISAYAR-ADI/` yazın.
2. Açılmazsa:
   - Ana bilgisayarda **Ayarlar > Ağ ve İnternet**'ten ağın **Özel ağ** olarak işaretli olduğunu kontrol edin (Ortak ağda güvenlik duvarı bağlantıya izin vermez).
   - Bilgisayar adı yerine IP adresiyle deneyin (`http://192.168.1.20/` gibi).
   - Programda **Ayarlar > Erişim adresleri**'nden kullanılan adın/IP'nin listede olduğunu kontrol edin.

## 6. UYAP / UETS eklentisi (yalnızca ana bilgisayarda)

UYAP dosyaları, duruşmalar, evraklar ve UETS tebligatları bu eklentiyle programa kendiliğinden aktarılır.

1. Ana bilgisayarda Chrome'u açın, adres çubuğuna `chrome://extensions` yazın.
2. Sağ üstten **Geliştirici modu**'nu açın.
3. **Paketlenmemiş öğe yükle** > `C:\Program Files\HukukBurosu\eklenti` klasörünü seçin.
4. Programda yönetici olarak **Ayarlar > Eklenti ayarları**'ndan eşleştirmeyi yapın ve aktarım yapılacak avukatlara UYAP/UETS izni verin.
5. UYAP Avukat Portal'a veya UETS'ye bu bilgisayarın Chrome'unda giriş yapın. Oturum açık kaldıkça aktarım kendiliğinden çalışır; üst çubuktaki UYAP/UETS ışığı durumu gösterir.

Eklenti güncellendiğinde açık UYAP/UETS sekmelerini yenileyin (F5).

## 7. Güncellemeler

Program **kendiliğinden güncellenir**; bir şey yapmanız gerekmez.

- Her gün yeni sürüm olup olmadığına bakılır, varsa indirilir.
- Kurulum, ana bilgisayar **bir sonraki açılışta** yapılır (birkaç dakika). Bu sırada diğer bilgisayarlarda "Program güncelleniyor" sayfası görünür ve iş bitince normal ekran gelir.
- Güncelleme başarısız olursa program **önceki sürüme ve verilere kendiliğinden döner**; o sürüm bir daha denenmez.
- Kurulu sürümü ve son güncellemenin sonucunu **Ayarlar > Hakkında**'da görebilirsiniz.

Ana bilgisayarın internete bağlı olması yeterlidir; internet yoksa program yine çalışır, yalnızca güncelleme yapılmaz.

## 8. Yedek ve geri yükleme

- Yedek her gün Ayarlar'da belirlediğiniz saatte (bilgisayar kapalıysa açılışta) alınır. Son 30 günün günlük ve son 12 ayın aylık yedekleri saklanır.
- **Ayarlar > Sistem monitörü**'nden son yedeği görebilir ve elle yedek alabilirsiniz.
- Geri yükleme destek eşliğinde yapılır: `C:\Program Files\HukukBurosu\tools\yedekten-geri-yukle.ps1`. Geri yüklemeden önce mevcut verinin yedeği kendiliğinden alınır.
- Yedekler parolasızdır; ofis klasörüne erişimi yalnızca yetkili kişilere verin.

## 9. Kaldırma

**Ayarlar > Uygulamalar**'dan "Hukuk Bürosu Otomasyonu" kaldırılabilir. Servisler ve görevler silinir; **veriler** (`C:\ProgramData\HukukBurosu`) ve ofis klasörü **silinmez**.

## 10. Sorun giderme

| Sorun | Ne yapmalı |
|---|---|
| Hiçbir bilgisayarda açılmıyor | Ana bilgisayarı yeniden başlatın; 2–3 dakika bekleyin. Sürerse `C:\ProgramData\HukukBurosu\logs` klasörünü destek ile paylaşın. |
| Yalnızca diğer bilgisayarlarda açılmıyor | 5. bölümdeki ağ kontrolleri. |
| "Program güncelleniyor" sayfası 15 dakikadan uzun sürüyor | Ana bilgisayarı yeniden başlatın; program önceki sürümle açılır. `C:\ProgramData\HukukBurosu\logs\guncelleme.log` dosyasını destekle paylaşın. |
| PIN'i unutan çalışan | Yönetici **Ayarlar > Kullanıcılar**'dan yeni PIN verir. |
| Yöneticinin PIN'i unutuldu | Başka bir yönetici hesabı yoksa destekten yardım alın. |
| UYAP ışığı kırmızı | Ana bilgisayarda UYAP'ın Chrome'da açık ve oturumun geçerli olduğunu kontrol edin. |
