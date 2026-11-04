# Proje İnceleme Raporu — 1

Tarih: 31 Ekim 2026

Projenin temeli, 5–6 kişinin çalıştığı bir hukuk ofisi için uygun. Müvekkil, dosya, görev, belge ve para hareketlerinin birbirine bağlanması iyi düşünülmüş. **Öncelik yeni özellik eklemekten önce mevcut kayıtların güvenilirliğini sağlamlaştırmak olmalı.** Özellikle silme yetkileri, emanet bakiyesi, belge erişimi ve yedekten dönüş konusunda önemli açıklar var.

İnceleme salt okunur yapıldı. İnceleme sırasında `CLAUDE.md` dahil hiçbir dosya değiştirilmedi; mevcut çalışmalara dokunulmadı. Bu rapor dosyası, inceleme sonrasında kullanıcının isteğiyle oluşturuldu. Aşağıda koddan doğrulanan sorunlarla geliştirme önerileri ayrılmıştır.

**Mevcut yapının korunmaya değer tarafları var.** Görevi yapanla kontrol edenin ayrılması, revizyon için açıklama istenmesi, cari borçla emanet paranın ayrı tutulması, Türkçe arama, belge sürümleri ve işlem geçmişi doğru tercihler. İnternetsiz çalışabilen yerel kurulum da ofisin kullanım biçimine uyuyor. Bunları koruyarak ilerlemek mümkün.

Bulgular önem sırasıyla değerlendirilmiştir:

1. **Yedekleme kodu ortak proje kaydının dışında kalmış — çok önemli.**

   Yedekleme bölümü bu bilgisayarda mevcut; ancak sürüm takibine alınmamış. Bunun nedeni, yedek dosyalarını dışarıda tutmak için yazılan kuralın uygulamanın yedekleme bölümünü de dışlaması.

   Uygulama açılırken bu bölümü zorunlu olarak çağırıyor. Dolayısıyla diğer bilgisayara yalnızca ortak proje kaydı taşındığında uygulama açılmayabilir. Otomatik denetimler de bu eksik kopyada çalışamaz.

   **Öneri:** Yedek dosyalarıyla yedekleme kodunun dışlama kuralları ayrılmalı. Ardından proje sıfırdan alınarak açılış doğrulanmalı.

   Kanıt: [.gitignore, satır 16](.gitignore), [uygulama ayarları, satır 40](config/settings/base.py).

2. **Bazı kayıtları yönetici olmayan kişiler de silebiliyor — çok önemli.**

   Proje kuralı “silme yalnızca yönetici” diyor. Buna rağmen duruşma, tebligat, müvekkilin iletişim/banka/vekalet alt kayıtları ve dosyadaki karşı taraf bağlantısının silinmesinde yönetici kontrolü bulunmuyor.

   Bu yalnızca düğmenin görünmesiyle ilgili değil; işlemi gerçekleştiren kod da yetkiyi denetlemiyor.

   **Örnek:** Bir stajyer yanlışlıkla tebligatı silebilir; son gün uyarısı da kaybolur.

   **Öneri:** Silme yetkisi bütün bölümlerde aynı kurala bağlanmalı. Özellikle tebligat ve duruşmalarda, geri alınabilir kaldırma ve kaldırma nedeni tercih edilmeli.

   Kanıt: [duruşma silme, satır 85](apps/cases/views_records.py), [tebligat silme, satır 122](apps/cases/views_records.py), [alt kayıt silme, satır 234](apps/clients/views.py), [karşı taraf bağlantısını silme, satır 203](apps/cases/views.py).

3. **Belge erişimi, muhasebe yetkilerini tam uygulamıyor — çok önemli.**

   Yüklenen dosyalara erişimde yalnızca kişinin giriş yapmış olması aranıyor. Bu nedenle muhasebeyi görme yetkisi bulunmayan biri, bağlantısı elindeyse muhasebe makbuzunu açabilir.

   Ayrıca belge yükleme alanı, tarayıcıda komut çalıştırabilen sayfa dosyalarını kabul ediyor; genel belge sunumu bunları doğrudan açabiliyor. Kabul ve sunum davranışı dosya değiştirmeden doğrulandı.

   **Öneri:** Belge açılırken belgenin bağlı olduğu kaydın yetkisi kontrol edilmeli. Güvenli belge türleri önizlenmeli; diğerleri indirme olarak sunulmalı. Bu yaklaşım, kullanılan altyapının [resmî güvenlik önerileriyle](https://docs.djangoproject.com/en/5.2/topics/security/) de uyumlu.

   Kanıt: [belge erişimi, satır 26](config/urls.py), [yükleme kontrolü, satır 94](apps/cases/forms.py).

4. **Emanet bakiyesi iki farklı yoldan eksiye düşebilir — çok önemli.**

   Ödeme öncesindeki bakiye kontrolüyle kaydın oluşturulması birlikte korunmuyor.

   **Örnek:** Emanette 10.000 TL varken iki çalışan aynı anda 7.000’er TL ödeme girerse ikisi de yeterli bakiye görebilir.

   İkinci sorun iptal işlemi: Emanete giren 10.000 TL’nin 7.000 TL’si ödendikten sonra ilk tahsilat iptal edilebiliyor. Bu durumda bakiye eksiye düşer.

   **Öneri:** Aynı müvekkilin para işlemleri sırayla ve tek bütün olarak yürütülmeli. İptal öncesinde oluşacak bakiye de hesaplanmalı; sorun yaratacak iptal engellenmeli veya bağlantılı düzeltme işlemi istenmeli.

   Kanıt: [bakiye kontrolü, satır 48](apps/accounting/forms.py), [kayıt oluşturma, satır 100](apps/accounting/views.py), [iptal, satır 115](apps/accounting/views.py).

5. **Dosyanın müvekkili değişince bağlı kayıtlar farklı kişilerde kalabiliyor — çok önemli.**

   Dosya düzenlenirken müvekkil değiştirilebiliyor. Ancak mevcut görev ve muhasebe kayıtlarının müvekkil bilgisi birlikte güncellenmiyor.

   **Örnek:** Dosya A kişisinden B kişisine geçirilirse dosya B’de görünürken önceki borçlar ve görevler A’da kalabilir. Sonraki bir işlem bazı kayıtları ayrıca değiştirebildiği için tutarsızlık büyüyebilir.

   **Öneri:** Bağlı kayıtları olan dosyada müvekkil değişikliği sıradan düzenleme olmamalı. Ya engellenmeli ya da etkilenecek kayıtları gösteren, yöneticiye özel bir taşıma işlemi olmalı.

   Kanıt: [dosya formu, satır 13](apps/cases/forms.py), [görev kaydı, satır 71](apps/tasks/models.py), [para kaydı, satır 130](apps/accounting/models.py).

6. **Yedek alma düşünülmüş; başarısız geri dönüş yeterince korunmamış — önemli.**

   Geri yükleme önce mevcut veritabanını değiştiriyor, ardından belgeleri taşıyor. İşlemin bütünü başarısız olduğunda eski duruma otomatik dönüş güvencesi yok. Yardımcı çalıştırma dosyası, geri yükleme başarısız olsa da uygulamayı yeniden başlatıyor.

   Ayrıca geri yükleme öncesindeki güvenlik yedeği başarısız olursa yardımcı dosya bunu denetleyip durmuyor.

   Mevcut denemelerde gerçek veritabanı geri yüklemesi yerine taklit işlem kullanılmış. Bu nedenle kayıtlı denemeler, gerçek bir arızadan dönüşün çalıştığını kanıtlamıyor.

   **Öneri:** Önce ayrı ortamda geri yükleme doğrulanmalı; başarısızlıkta uygulama bakım durumunda kalmalı. Düzenli olarak başka bir bilgisayara yedekten dönüş provası yapılmalı. Yerel yedeğin ve ikinci kopyanın başarısı ayrı gösterilmeli.

   Kanıt: [geri yükleme, satır 189](apps/backups/services.py), [yardımcı işlem, satır 17](installer/scripts/yedekten-geri-yukle.ps1), [mevcut deneme, satır 86](tests/test_backups.py).

7. **Aynı adlı müvekkillerin ofis klasörleri karışabilir — önemli.**

   Klasör eşleştirmesinde müvekkilin adı kullanılıyor. Aynı adlı iki ayrı kişi aynı klasöre yönlenebilir. Türkçe harf farklarını kaldırarak eşleştirme yapılması da bazı farklı adları aynı kabul edebilir.

   Dosyaların üzerine yazılmaması iyi; fakat bu, farklı kişilerin belgelerinin aynı klasörde toplanmasını engellemiyor.

   **Öneri:** Klasörlerde sabit müvekkil numarası kullanılmalı: örneğin `M000142 - Örnek Kişi`. Dosya klasörleri de sabit dosya numarasıyla ayrılmalı.

   Kanıt: [müvekkil klasörü, satır 72](apps/core/folders.py).

8. **Hatırlatmalar gün içinde eklenen veya değişen işleri kaçırabilir — önemli.**

   Hatırlatma üretimi günün ilk sayfa açılışında bir kez çalışıyor. Sonradan eklenen yakın tarihli iş, o günkü süre hatırlatmasına girmeyebilir.

   Ayrıca kontroldeki görevin süre uyarısı kontrolcüye değil, görevi yapana gidiyor. Tebligat son günleri zil bildirimlerine dahil değil. Görev son günleri takvimde görünmüyor.

   **Öneri:** Hatırlatmalar sayfa açılışından bağımsız çalışmalı; yeni kayıt ve tarih değişiklikleri ayrıca ele alınmalı. Görev, duruşma ve tebligat aynı tarih görünümünde toplanmalı.

   Kanıt: [hatırlatmalar, satır 23](apps/notifications/services.py), [günlük tetikleme, satır 64](apps/notifications/services.py), [takvim kapsamı, satır 167](apps/agenda/services.py).

9. **Kontrole gönderilen belge, kontrol sırasında değiştirilebiliyor — önemli.**

   Görev kontroldeyken de belge yüklemek ve bazı belgeleri silmek mümkün. Zorunlu belge kontrolü yalnızca kontrole gönderme sırasında yapılıyor.

   **Örnek:** Belgeyle kontrole gönderilen görevden belge sonradan silinebilir; onay aşamasında aynı zorunluluk yeniden kontrol edilmiyor. Kontrolcü, baktığı sürümden farklı bir sürümü de onaylayabilir.

   Aynı anda iki onay isteğini engelleyen kayıt kilidi de bulunmuyor; tekrarlı belge ve geçmiş kaydı oluşması ihtimali var.

   **Öneri:** Kontrole gönderilen sürüm sabitlenmeli. Değişiklik yapılırsa görev yeniden kontrole sunulmalı. Tekrarlanan onay isteği ikinci işlem üretmemeli.

   Kanıt: [belge yükleme yetkisi, satır 75](apps/tasks/services.py), [onay işlemi, satır 90](apps/tasks/services.py), [belge silme, satır 276](apps/tasks/views.py).

10. **Geliştirilmekte olan toplu aktarımda yanlış eşleştirme riski var — önemli.**

    Bu bölüm tamamlanmış kabul edilmeden değerlendirildi. Şu sorunlar görüldü:

    - Kimlik numaraları farklı olsa bile aynı adlı yeni kişi “zaten kayıtlı” sayılıp atlanabiliyor. Bu durum bellekte yapılan denemeyle doğrulandı.
    - Ada göre dosya bağlanırken aynı adlı kişiler arasında belirsizlik oluşabiliyor.
    - Aynı açılış bakiyelerinin yeniden aktarılmasını önleyen kalıcı bir kontrol yok.
    - Normal müvekkil girişindeki çıkar çatışması kontrolü burada uygulanmıyor.

    **Öneri:** Kimlik numarası öncelikli olmalı; ad benzerliği otomatik karar yerine kullanıcıya seçim sunmalı. Her aktarımın kimliği bulunmalı ve tekrarında aynı para kaydı oluşmamalı. Önizlemede hangi mevcut kişiye bağlanacağı açıkça gösterilmeli.

    Kanıt: [eşleştirme, satır 186](apps/imports/services.py), [aynı kayıt kontrolü, satır 233](apps/imports/services.py), [bakiye aktarımı, satır 344](apps/imports/services.py).

11. **Giriş kolaylığı ile ofis güvenliği arasında iyileştirme gerekiyor.**

    Kurulumda herkes aynı dört haneli giriş koduyla başlıyor; ilk girişte değiştirme zorunluluğu yok. Ayrıca ofis ağı bağlantısı şifrelenmeden çalışacak şekilde ayarlanmış.

    Hatalı giriş sınırı ve giriş kodlarının korumalı saklanması olumlu. Buna ek olarak ortak başlangıç kodunun zorunlu değiştirilmesi, boşta kalan ekranın kilitlenmesi ve ofis içinde de bağlantının şifrelenmesi uygun olur. [Resmî kurulum rehberi](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/) de giriş bilgilerinin geçtiği bağlantının korunmasını öneriyor.

    Kanıt: [kurulumdaki ortak kod, satır 69](installer/OzkurtHukuk.iss), [canlı kullanım ayarları, satır 8](config/settings/prod.py).

Daha düşük öncelikli, fakat kullanımı etkileyen başka noktalar da var:

| Bulgu | Kullanıcıya etkisi | Öneri |
|---|---|---|
| Excel çıktısında `=` ile başlayan metin hesaplama komutu sayılıyor | Açıklama veya ad, beklenenden farklı yorumlanabilir | Metin hücreleri açıkça metin olarak yazılmalı |
| Dosya seçim yardımcıları 500 kayıtla sınırlı | Eski dosyalar seçim sırasında kaybolabilir; otomatik doldurma eksik kalabilir | Yazarak aranan ve gerektiğinde devamı getirilen seçim |
| “Ofis geliri” hesabına masraf geri ödemeleri de karışabiliyor | Tahsilat, kazanılan ücret gibi okunabilir | Ücret, masraf iadesi ve emanet ayrı gösterilmeli |
| Bazı raporlar her kişi/dosya için ayrıca bilgi çekiyor | Kayıtlar büyüdükçe raporlar yavaşlayabilir | Toplu hesaplama ve büyük örnek veriyle ölçüm |
| Uyarı mesajları 4,5 saniyede kapanıyor | Klasöre kopyalanamayan belge gibi önemli sorunlar gözden kaçabilir | Önemli hatalar kullanıcı kapatana kadar kalmalı |
| Müvekkil sayfasının başlığına yanlışlıkla sayfa komutu eklenmiş | Tarayıcı sekmesinde gereksiz metin görülebilir | Başlık alanı sadeleştirilmeli |

Kaynaklar: [Excel çıktısı, satır 60](apps/reports/renderers.py), [500 kayıt sınırı, satır 205](apps/tasks/views.py), [gelir özeti, satır 288](apps/reports/definitions.py), [sayfa başlığı, satır 3](templates/clients/detail.html).

**Profesyonel örneklerle kıyaslandığında en büyük gelişme alanı, kayıt tutmaktan işin sonraki adımını yönlendirmeye geçmek.** Aşağıdaki karşılaştırma, üreticilerin yayımladığı özelliklere dayanıyor; ürünler uygulamalı olarak denenmedi.

| Alan | Profesyonel örnek | Bu ofise uygun karşılığı |
|---|---|---|
| Standart dosya süreçleri | [Smokeball](https://www.smokeball.com/features/manage/tasks-and-workflows), dosya türü ve aşamasına göre görev dizileri sunuyor | “Yeni dava”, “bilirkişi raporu geldi”, “karar tebliğ edildi” için hazır görev grupları |
| Belge hazırlama | [Smokeball](https://www.smokeball.com/), belge şablonları ve belge hazırlama desteği sunuyor | Müvekkil ve dosya bilgileriyle doldurulan ofise ait yazı şablonları |
| Müvekkil iletişimi | [Clio](https://www.clio.com/manage/), dosyayla bağlantılı iletişim ve müvekkil alanı sunuyor | Önce telefon/görüşme geçmişi ve avukat onaylı durum özeti |
| Emanet kontrolü | [Clio](https://help.clio.com/hc/en-us/articles/21058568234267-Operating-and-Trust-Reconciliation), banka ve hesap kayıtlarını karşılaştırıyor | Bankadaki tutarla sistemdeki emanet toplamını karşılaştıran aylık kontrol |
| Yönetim görünümü | [Clio](https://www.clio.com/manage/), filtrelenebilir ve zamanlanabilir raporlar sunuyor | Kontrolde bekleyen işler, geciken işler ve yaklaşan önemli tarihler için yönetici özeti |

Bu özelliklerin tamamını eklemek gerekmiyor. Küçük ofiste en çok yararı şu geliştirmeler sağlar:

- **Güne başlama ekranı:** “Bugün yapılacaklar”, “kontrolümü bekleyenler”, “son günü yaklaşan tebligatlar” ve “sonucu girilmemiş duruşmalar” birlikte gösterilmeli.
- **Dosyada açık bir sonraki adım:** Her aktif dosyada “Sıradaki işlem, sorumlu kişi, hedef tarih” bulunmalı. Uzun süredir işlem yapılmamış dosyalar ayrıca görünmeli.
- **Duruşma sonrası kısa akış:** Sonuç girildiğinde yeni duruşma tarihi, ara karar görevleri ve gerekli belgeler aynı işlemde oluşturulabilmeli.
- **Personel devri:** İzinli veya ayrılan kişinin açık işleri başka çalışana topluca devredilebilmeli; kontrol bekleyen işler sahipsiz kalmamalı.
- **Kaydedilebilir çalışma listeleri:** “Benim gecikmiş işlerim”, “vekaleti eksik müvekkiller”, “bu hafta duruşması olanlar” tek tıklamayla açılmalı.
- **Belge bütünlüğü:** “Taslak”, “kontrolde”, “onaylı”, “gönderildi” ayrımı yapılmalı. Ofis klasörüne kopyalanamayan belgeler kalıcı bir listede görünmeli.
- **Müvekkile verilecek kısa durum özeti:** Son gelişme, sonraki işlem ve beklenen belge sade bir sayfada hazırlanmalı. Ofis içi yorumlarla paylaşılabilir bilgiler ayrılmalı.
- **Görüşme kaydı:** Kimin, ne zaman, hangi konuda arandığı dosyaya bağlanmalı. “Müvekkile bilgi verildi mi?” sorusu cevapsız kalmamalı.
- **Daha anlaşılır hesap ekranı:** İşlem öncesi ve sonrası borç/emanet tutarı gösterilmeli. “Yeni gelir/gider” yerine mevcut kapsamı anlatan “Müvekkil hesap hareketi” adı daha doğru olur.

Müvekkilin doğrudan giriş yapacağı ayrı bir alan sonraki aşamaya bırakılabilir. Önce avukatın onayladığı paylaşılabilir dosya özeti daha düşük çabayla fayda sağlar. Böyle bir alan ileride yapılırsa mevcut ofis içi uygulamayı doğrudan internete açmak yerine ayrı erişim sınırları tasarlanmalı.

**Önerilen geliştirme sırası:** İlk aşamada silme yetkileri, para hareketleri, belge erişimi, müvekkil değişikliği ve yedekten dönüş düzeltilmeli. İkinci aşamada birleşik tarih ekranı, hatırlatmalar, görev devri ve duruşma sonrası işlem akışı tamamlanmalı. Üçüncü aşamada görev/belge şablonları, banka karşılaştırması ve müvekkil durum özetleri eklenmeli.

Canlı kullanıma hazırlıkta özellikle şu durumlar doğrulanmalı: aynı anda iki ödeme, aynı göreve iki onay, farklı kimlikli aynı adlı kişiler, yetkisiz belge açma, başarısız geri yükleme ve projenin temiz bilgisayarda kurulması.

**Yapılan kontrollerin sonucu:** 157 Python dosyasında sözdizimi incelemesi ve uygulamanın temel ayar denetimi geçti. Genel yazım denetimi de geçti; ancak dışarıda kalan yedekleme kodu ayrıca denetlenince 10 yazım kuralı ihlali ve düzen gerektiren 3 dosya çıktı. Bunlar davranış hatası sayılmaz; genel denetimin eksik kapsamını gösteriyor.

95 deneme işlevi mevcut. Veritabanına ve dosyalara yazacakları için bunların tamamı çalıştırılmadı. Seçili davranışlar bellekte doğrulandı. Ekranlar tarayıcıda kullanılarak, gerçek kurulum yapılarak veya gerçek yedekten dönülerek doğrulama yapılmadı; rapordaki kullanım ve kurulum değerlendirmeleri bu sınırla okunmalı.

## Tasarım ve kullanım kolaylığı değerlendirmesi

**Tasarımın temeli tutarlı; en büyük gelişme alanı, kullanıcının önemli işi daha hızlı fark etmesi ve daha az adımla tamamlaması.** Lacivert–bronz renk düzeni ve genel görünüm korunabilir.

Bu değerlendirme ekran şablonları ve görünüm kurallarına dayanıyor. Canlı ekranlar farklı boyutlarda açılarak görsel doğrulama yapılmadı; bu nedenle yerleşimle ilgili bazı noktalar kullanım denemesi gerektiriyor. Aşağıdaki öneriler henüz uygulanmadı.

### Korunması önerilen güçlü taraflar

- Lacivert, beyaz ve ölçülü bronz kullanımı hukuk ofisine uygun bir kimlik oluşturuyor.
- Başlık, tablo, form ve durum işaretlerinin ortak düzeni var.
- Ana sayfanın kişiye ait görevlerle başlaması doğru.
- Görev sayfasında belge, işlem düğmeleri ve geçmişin birlikte bulunması kullanışlı.
- “Bugün”, “Yarın”, “3 gün gecikti” gibi ifadeler tarihi yorumlama yükünü azaltıyor.
- Boş listelerde açıklama verilmesi ve açık/koyu görünüm seçeneği olumlu.

### Öncelikli iyileştirmeler

1. **Önemli bilgiler fazla soluk ve küçük.**

   Tarihler, açıklamalar, tablo alt bilgileri ve bazı etiketlerde küçük, açık gri yazılar kullanılıyor. Bunlar ofis çalışanının gün boyunca sürekli okuyacağı bilgiler.

   Açık görünümdeki gri metnin beyaz zemine karşı okunurluk oranı hesaplandı: **3,72:1**. Aynı metnin açık sayfa zemini üzerindeki oranı **3,44:1**. Normal boyuttaki metin için erişilebilirlik rehberinin önerdiği alt sınır **4,5:1**. Bu, ölçülebilir bir iyileştirme alanı. Hesap, görünüm dosyasındaki renk değerlerine dayanır; bütün ekranlar için yapılmış kapsamlı bir erişilebilirlik denetimi değildir.

   **Öneri:** Yardımcı yazılar koyulaştırılmalı; son gün, dosya numarası ve sorumlu adı daha belirgin yapılmalı. Özellikle tablo başlıkları ve tarih bilgileri büyütülmeli.

   Kanıt: [renk ve yazı tanımları](static/css/app.css). Ölçüt: [metin okunurluğu için resmî erişilebilirlik açıklaması](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

2. **Ana sayfa, günün iş planını daha açık anlatmalı.**

   “Aktif görevlerim” iyi bir başlangıç. Ancak görev yapan kişiyle kontrol eden avukatın ihtiyaçları farklı.

   Üst bölümde şu dört kısa özet yeterli olur. Aşağıdaki sayılar yalnızca tasarım örneğidir; gerçek ofis verisi değildir.

   | Bugün yapılacak | Kontrolümü bekleyen | Geciken | Yaklaşan önemli tarih |
   |---|---|---|---|
   | 5 görev | 3 belge | 2 iş | 1 duruşma |

   **Öneri:** Her özet ilgili listeyi açmalı. Alt tarafta işler “Bugün”, “Gecikmiş”, “Sonraki günler” şeklinde gruplanabilir. Böylece çalışan sayfayı açınca nereden başlayacağını görür.

   İncelenen ekran: [ana sayfa](templates/core/home.html).

3. **Dosya ayrıntısında çok sayıda sekme arasında bilgi aramak gerekiyor.**

   Görevler, duruşmalar, tebligatlar, zaman çizelgesi, karşı taraflar, belgeler, muhasebe ve geçmiş ayrı yerlerde. Dar ekranlarda sekmeler yatay kaydırılıyor; önemli bir bölüm gözden kaçabilir.

   **Öneri:** Dosya özetinin en üstünde sıradaki işlem ve son günü, sorumlu kişi, yaklaşan duruşma, bekleyen tebligat ve son gelişme her zaman görünmeli.

   Sekmeler ayrıntıya ulaşmak için kullanılabilir. Kullanıcı dosyanın durumunu anlamak için birkaç sekme dolaşmamalı. Sekmelerin birleştirilmesi veya yeniden gruplanması, ofis çalışanlarıyla yapılacak kısa kullanım denemesiyle kararlaştırılmalı.

   İncelenen ekranlar: [dosya ayrıntısı](templates/cases/detail.html), [müvekkil ayrıntısı](templates/clients/detail.html).

4. **Liste filtreleri güçlü, fakat ilk bakışta yoğun.**

   Müvekkil listesinde çok sayıda seçim alanı aynı anda gösteriliyor. Günlük kullanımda çoğu kişi bunların birkaçına ihtiyaç duyacaktır.

   **Öneri:** İlk sırada arama, sorumlu kişi ve aktiflik kalsın. Diğerleri “Diğer filtreler” içinde açılabilsin. Seçilen koşullar ayrıca görünmeli:

   `Vekaleti yok ×` · `Açık görevi var ×` · **Tümünü temizle**

   “Benim dosyalarım” veya “Vekaleti eksik olanlar” gibi kaydedilmiş listeler de tekrarlanan işi azaltır. Seçilen koşulların tek tek kaldırılabilmesi ve bulunan kayıt sayısının görünmesi, neden belirli kayıtların listelenmediğini anlamayı kolaylaştırır.

   İncelenen ekranlar: [müvekkil listesi](templates/clients/list.html), [görev listesi](templates/tasks/list.html).

5. **Formlar, kayıt işlemini daha bütünlüklü tamamlatmalı.**

   Müvekkil oluşturulduktan sonra iletişim bilgilerini ayrıca eklemek gerekiyor. Telefon görüşmesi sırasında kayıt açan biri için bu ek adım oluşturur.

   **Öneri:** İlk kayıt ekranında ad/unvan, telefon ve sorumlular birlikte girilebilmeli. Ayrıntılı kimlik, banka ve vekalet bilgileri sonradan tamamlanabilir. Mevcut zorunlu iş kuralları korunmalı.

   Uzun formlarda alt tarafta görünür kalan kaydetme alanı, kaydedilmemiş bilgiyle çıkarken uyarı, hata olduğunda üstte kısa hata listesi ve hatalı alana doğrudan geçiş yararlı olur.

   Alan yanında açıklama bulunması zaten iyi; genel hata özetiyle tamamlanabilir. Hata mesajı, sorunu ve nasıl düzeltileceğini birlikte anlatmalı.

   İncelenen ekran: [müvekkil formu](templates/clients/form.html), [ortak form alanı](templates/partials/field.html). Kaynak: [form sonuçları ve hata bildirimleri için resmî erişilebilirlik rehberi](https://www.w3.org/WAI/tutorials/forms/notifications/).

6. **İşlem sonuçları daha açık ve kalıcı olmalı.**

   Önemli uyarılar da kısa sürede kapanıyor. Örneğin belge kaydolup ofis klasörüne kopyalanamadığında çalışan sonucu kaçırabilir.

   **Öneri:** Başarı mesajları kısa süreli kalabilir. Eksik kalan işlem ise kullanıcı kapatana kadar görünmeli ve çözüm sunmalı:

   > Belge kaydedildi. Ofis klasörüne kopyalanamadı.
   >
   > **Yeniden dene** · **Ayrıntıyı gör**

   Gönderme ve yükleme sırasında da “Yükleniyor…” gibi açık bir durum gösterilmeli. İşlem sürerken aynı düğmeye yeniden basılması önlenmeli; başarısızlıkta kullanıcının girdiği bilgiler korunmalı.

   İncelenen ekranlar: [ortak bildirimler](templates/base.html), [dosya belgeleri](templates/cases/_documents.html), [görev belgeleri](templates/tasks/_documents.html).

7. **Takvimin telefonda farklı bir sunuma ihtiyacı var.**

   Mevcut takvim yedi sütunlu; etkinlik adları sığmadığında kesiliyor. Telefonda dosya konusu ve saat gibi bilgiler zor okunabilir. Bu durum canlı dar ekran denemesiyle doğrulanmalı.

   **Öneri:** Bilgisayarda ay/hafta görünümü korunabilir. Telefonda tarih sıralı liste daha kullanışlı olur. Aşağıdaki kayıtlar yalnızca tasarım örneğidir:

   > **3 Kasım Salı**
   >
   > 09.30 — Duruşma · Dosya 2026/0142
   >
   > Son gün — Bilirkişi raporuna itiraz

   Etkinliğe basınca ilgili dosya, yer, sorumlu ve yapılacak işlem birlikte açılmalı. Tam metne erişim yalnızca fareyi üzerinde bekletmeye bağlı olmamalı.

   İncelenen ekran: [takvim](templates/agenda/calendar.html). Görünüm tanımları: [takvim sütunları ve etkinlik metinleri](static/css/app.css).

8. **Para ekranında anlam, tutar kadar görünür olmalı.**

   “Cari”, “Emanet” ve “Net” ayrımı doğru. Ancak özellikle yeni çalışan için daha açıklayıcı başlıklar yararlı olur:

   - **Müvekkilin ofise borcu**
   - **Müvekkile ait eldeki para**
   - **İkisi arasındaki fark**

   **Öneri:** Para girişi sırasında “Bu işlemden sonra” özeti gösterilmeli. Örneğin: “Emanette kalan: 3.000 TL.” Bu, yanlış işlem fark etmeyi kolaylaştırır. Renkler açıklayıcı yazıyla birlikte kullanılmalı; tutarın anlamı yalnızca kırmızı veya yeşil olmasına bağlı kalmamalı.

   İncelenen ekranlar: [bakiye özeti](templates/accounting/_balances.html), [para hareketi formu](templates/accounting/form.html).

### Klavyeyle kullanım ve erişilebilirlik

Klavyeyle kullanım üzerinde ayrıca çalışılmalı:

- Arama sonuçlarında ok tuşlarıyla ilerlemek ve seçili sonucu açmak mümkün olmalı.
- Klavyeyle seçili alan belirgin görünmeli.
- Yalnızca simgeden oluşan düğmelerin anlaşılır adı bulunmalı.
- Sekmeler klavyeyle kullanılabilir olmalı; seçili bölüm yardımcı okuma araçlarına doğru bildirilmeli.
- Sayfanın bir bölümü yenilendiğinde hata, başarı veya bulunan sonuç sayısı kullanıcıya anlaşılır biçimde duyurulmalı.

Bu başlıkların bir kısmı mevcut şablonlardan değerlendirildi; tam doğrulama için canlı ekranda klavye ve yardımcı okuma aracıyla deneme gerekiyor.

### Tasarım çalışmasının sırası ve başarı ölçütleri

İlk tasarım çalışması **ana sayfa, dosya ayrıntısı ve görev kontrol ekranına** odaklanmalı. Önce yazılar ve bilgi önceliği düzeltilmeli; ardından form ve bildirim davranışları iyileştirilmeli. Renk ve süsleme değişikliklerinin önceliği daha düşük.

Başarı şu günlük işlerle ölçülmeli:

- Çalışan bugünkü işini hemen bulabiliyor mu?
- Avukat kontrol bekleyen belgeyi kolayca açabiliyor mu?
- Dosyanın sonraki adımı anlaşılabiliyor mu?
- Para işleminin sonucunu kaydetmeden önce görebiliyor mu?

Denemeler gerçek müvekkil bilgisi kullanılmadan örnek kayıtlarla yapılmalı. Bilgisayarda farklı pencere genişlikleri, büyütülmüş yazılar, açık/koyu görünüm ve telefon boyutundaki görünüm ayrıca kontrol edilmeli. İşin tamamlanması için gereken adımlar, yanlış seçimler ve kullanıcının yardım istediği noktalar not edilerek tasarım kararları doğrulanmalı.
