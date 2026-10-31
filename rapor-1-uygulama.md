# Rapor 1 — Uygulanan düzeltmeler

31 Ekim 2026

Excel'den aktarım çalışmasına dokunulmadı. Başlangıçta değişmiş olan `config/settings/base.py`, `config/urls.py`, `pyproject.toml`, `templates/accounts/settings.html`, ayrıca `apps/imports/`, `templates/imports/` ve `rapor-1.md` aynen korundu. Bu 11 dosyanın içeriği işlem öncesi ve sonrası karşılaştırıldı.

| Rapordaki madde | Sonuç |
|---|---|
| 1 — Yedekleme kodunun ortak kayıtta bulunmaması | Dışlama kuralı kökteki yedek klasörüyle sınırlandı; yedekleme uygulaması ve şema dosyaları ortak kayda eklendi. |
| 2 — Yetkisiz silme | Duruşma, tebligat, karşı taraf bağlantısı ve müvekkil alt kayıtları hem işlem tarafında hem düğmelerde yöneticiyle sınırlandı. Geri alınabilir silme ve silme nedeni bu çalışmaya dahil değil. |
| 4 — Emanetin eksiye düşmesi | Ekrandan kayıt ve iptal aynı müvekkil için sırayla yürütülüyor. Bakiye kayıttan hemen önce yeniden kontrol ediliyor; eksi bakiye oluşturacak iptal reddediliyor. |
| 5 — Dosyanın müvekkilinin değişmesi | Görevi veya muhasebe hareketi bulunan dosyada değişiklik engellendi. Aynı anda görev/para kaydı eklenmesiyle düzenleme birbirini bekliyor. |
| 6 — Başarısız geri yükleme | Güvenlik yedeği ve servis durdurma hatalarında işlem başlamıyor. Dönüş başarısızsa uygulama açılmıyor. Belgeler önce hazırlanıyor; veritabanı işlemi bir bütün olarak yürütülüyor; hata halinde önceki belgeler yerine konuyor. Gerçek geri yükleme provası gerekli. |
| 7 — Aynı adlı kişilerin klasörleri | Yeni klasörlerde sabit müvekkil ve dosya numarası kullanılıyor. Kaydedilmiş eski klasörler taşınmıyor. İki kayda bağlanmış ortak klasöre yeni belge kopyalanmıyor; açıklayıcı uyarı gösteriliyor. Eşzamanlı dosya kopyalarının birbirinin üzerine yazması da engellendi. |
| 8 — Hatırlatmalar ve birleşik tarihler | Gün içinde eklenen/değişen işlerden sonra yeniden kontrol yapılıyor. Kontroldeki görev kontrolcüye; tebligat ve duruşma avukat/stajyere hatırlatılıyor. Görev son günleri ana sayfa ve takvime eklendi. Yeni kurulum/güncelleme, sayfa açık değilken de beş dakikada bir kontrol eden görevi ekliyor. |
| 9 — Kontroldeki belge ve tekrarlı onay | Kontroldeki görev ve belgeleri değiştirilemiyor. Önce revizyon istenmeli. Onay belge zorunluluğunu yeniden denetliyor; eşzamanlı iki onay tek sonuç üretiyor. |
| Excel çıktısında hesaplama komutu gibi yorumlanan metin | Başlıklar, özetler ve rapor satırları dahil bütün metin hücreleri açıkça metin olarak yazılıyor. Sayılar sayı olarak korunuyor. |
| Önemli mesajların kısa sürede kapanması | Uyarı ve hata mesajları kullanıcı kapatana kadar kalıyor; kapatma düğmesinin açıklaması eklendi. |
| Müvekkil sayfasının başlığı | Yanlışlıkla başlığa konan sayfa komutu kaldırıldı; cari hesap sekmesini açan mevcut komut sayfa içinde korundu. |

## Ayrı çalışma gerektiren maddeler

- **3 — Belge erişimi:** Belge sunan adresin bulunduğu `config/urls.py`, yarım kalan işte değiştirilmiş olduğu için korundu. Muhasebe makbuzlarının yetki kontrolü ve güvenli belge sunumu hâlâ gerekli.
- Önceden ortak klasörde karışmış belgeler kendiliğinden ayrılmaz; sahiplikleri kontrol edilerek ayrı klasörlere alınmaları gerekir. Bu çalışmada mevcut ofis klasörleri taşınmadı veya silinmedi.
- Sayfa açılmadan yapılan hatırlatma kontrolünün ofis sunucusunda devreye girmesi için kurulum paketiyle güncelleme gerekir. Bu bilgisayarda gerçek zamanlanmış görev oluşturulmadı.
- **10 — Aktarım:** Tamamlanmamış çalışma olduğu için incelenen dosyalar değiştirilmedi. Aktarımın para kayıtları yeni muhasebe korumasından henüz geçmiyor.
- **11 — Giriş ve ağ bağlantısı:** İlk girişte kod değiştirme, boşta ekran kilidi ve şifreli bağlantı henüz yapılmadı.
- 500 kayıt sınırı, gelir raporunun anlamı, raporların hızlandırılması ve kapsamlı ekran önerileri ayrı çalışma olarak duruyor.

## Doğrulama

- Toplam 180 deneme geçti. Aynı adlı kişiler, eski/ortak klasörler, eşzamanlı belge kopyalama, gün içi tarih değişikliği ve hatırlatmaların doğru kişiye gitmesi de kapsama alındı.
- Aynı anda ödeme, mahsup, iptal ve görev onayı gerçek PostgreSQL bağlantılarıyla denendi. Emanet eksiye düşmedi; ikinci onay yeni geçmiş kaydı üretmedi.
- Bozuk yedek, belge kopyalama/klasör değiştirme hatası, veritabanı dönüş hatası ve belgesiz yedek durumları taklit işlemlerle denendi. Gerçek veritabanı geri yüklemesi ve kurulu Windows servisleri denenmedi.
- Genel kod kuralları, biçim denetimi ve Windows yardımcı dosyasının dil denetimi geçti.
- Windows hatırlatma yardımcısı, gerçek servislere dokunmadan dört durumla denendi: servis yok, servis kapalı, başarılı komut ve başarısız komut.
- Ortak proje kaydı ve yalnızca bu düzeltmelerle ayrı kopya oluşturuldu; yarım kalan aktarım ve yerel ayarlar kopyalanmadı. Bu kopyanın açılış denetimi ve 180 denemenin tamamı geçti. Tam Windows kurulum paketi bu çalışmada hazırlanmadı.
- Gerçek müvekkil bilgisi, yerel ayarlar ve erişim bilgileri değiştirilmedi.
