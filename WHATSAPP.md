# WhatsApp — arşivlenmiş bağlantı taslağı

**Kullanım dışı:** Kullanıcı kararıyla mesaj ekranları, gelen bildirim adresi ve otomatik gönderim kaldırılmıştır. Aşağıdakiler eski taslaktır; yeniden kurulum kararı olmadan uygulanmaz. Eski kayıtlar korunur.

Program bölümü hazır; gerçek ofis numarası henüz bağlanmadı. Gönderim varsayılan olarak kapalıdır. Mevcut telefon hesabı taşınmadı, gerçek mesaj gönderilmedi.

## Hazır olan kullanım

- Yan menüde **WhatsApp mesajları** ortak kutuyu açar. Müvekkil detayındaki **WhatsApp** düğmesi yazışmayı ve randevuları açar.
- Personel müvekkilin kayıtlı telefonlarından birini seçer, mesaj iznini ve otomatik hatırlatma tercihini kaydeder. Aynı numara iki müvekkile bağlanamaz. Bilinmeyen numaradan gelen mesaj ada bakılarak eşleştirilmez.
- Gelen metinler, gönderilen mesajlar ve teslim/okunma durumları kaydedilir. Metin en fazla 4096 karakterdir. Belge/medya için bu sürümde bildirim gösterilir; asıl içerik WhatsApp'tan açılır. Eski telefon yazışmaları kendiliğinden içe aktarılmaz.
- Randevu eklenebilir, değiştirilebilir veya iptal edilebilir. Randevular uygulama takvimine de girer. Google Takvim'den salt okunur gelen etkinliğin hangi müvekkile ait olduğu varsayılmaz.
- Duruşma/randevu, yöneticinin seçtiği süre içinde bir kez hatırlatılır; başlangıç değeri 24 saattir. Tarih/yer değişikliği ayrı güncel hatırlatma oluşturur. İptal edilmiş veya geçmiş kayıt, izinsiz/pasif müvekkil ve değişmiş telefon için gönderim engellenir. Sunucu kapalıyken gönderim yapılmaz.
- Bağlantı kesilip gönderim sonucu bilinmiyorsa mesaj otomatik tekrarlanmaz. Personel önce WhatsApp'tan kontrol eder. Kesin reddedilen mesajda **Tekrar dene** bulunur.

## Canlı kullanım için kalan adımlar

1. Kodun kullanılacağı bilgisayarda şemayı güncelleyin. Geliştirme: `uv run python manage.py migrate`. Kurulu ofis sunucusunda: `tools\manage.cmd migrate`. Kurulum paketi bu adımı zaten çalıştırır.
2. Mevcut numaranın normal WhatsApp mı, WhatsApp Business uygulaması mı kullandığını netleştirin. Resmî işletme hesabı/numara bağlantısını bu duruma uygun kurun. Mevcut hesabı silme, numara taşıma veya ücretli hizmet başlatma işlemi bu çalışmada yapılmadı.
3. Sunucuda yalnızca ilgili ortam değişkenlerini güvenli biçimde tanımlayın: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_API_VERSION`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`. Sürüm alanı Meta uygulamasının desteklediği sürüm olmalı; kod bir sürüm tahmin etmez. Erişim değerlerini sohbet, ortak proje kaydı, işlem çıktısı veya bu belgeye koymayın.
4. İnternetten güvenli biçimde erişilen bildirim adresini hazırlayın. Uygulamadaki yol `/muvekkiller/mesajlar/bildirim/` adresidir. Mevcut ofis uygulaması yerel ağda çalıştığı için bu bağlantının nasıl sağlanacağı ayrıca seçilmelidir; bütün ofis uygulaması doğrudan yayınlanmış değildir. Meta'nın doğrulama isteği ve imzalı gelen mesaj/teslim denemesi tamamlanmalıdır. Yeni hesap oluşturmadan veya sunucu hizmeti satın almadan önce kullanıcıyla kapsam ve ücret netleştirilmelidir.
5. Resmî hesapta duruşma ve randevu hazır metinlerini onaylatın. Her ikisinin gövde değişkenleri sırasıyla **müvekkil adı, tarih, saat, yer** olmalıdır. Sohbet başlatma metni değişkensiz sabit metindir. Adları ve dilini uygulamada **WhatsApp mesajları > Bağlantı ve hatırlatmalar** bölümüne yazın. Gösterilen hatırlatma özeti, Meta'daki onaylı metnin birebir kopyası değil, gönderilen alanların özetidir.
6. Önce yalnızca izin verilmiş bir deneme numarasıyla gerçek gönderim, gelen cevap, teslim bilgisi ve izin kapatma akışını doğrulayın. Ardından yönetici gönderim anahtarını açabilir. Gerçek müvekkil numarasıyla otomatik deneme yapılmamalıdır.
7. Sayfa kapalıyken kontrol için güncellenmiş kurulum paketi gereklidir. `Ozkurt Hukuk Hatirlatma` görevi beş dakikada bir normal hatırlatmaları ve `send_whatsapp` işlemini çalıştırır. Yardımcı uygulama servisi kapalıysa çalışmaz. Komutu elle çalıştırmak canlı ayarlar açıksa gerçek gönderim yapar.

## Hazır metin örnekleri

Onaya gönderilecek metinler ofisin kendi adıyla düzenlenmelidir:

- Duruşma: `Merhaba {{1}}, {{2}} tarihinde saat {{3}} için duruşma hatırlatmasıdır. Yer: {{4}}. Hatırlatmaları kapatmak için “Hatırlatmaları durdur” yazabilirsiniz.`
- Randevu: `Merhaba {{1}}, {{2}} tarihinde saat {{3}} için randevu hatırlatmasıdır. Yer: {{4}}. Hatırlatmaları kapatmak için “Hatırlatmaları durdur” yazabilirsiniz.`
- Sohbet başlatma: `Merhaba, hukuk ofisimizden sizinle iletişime geçiyoruz. Görüşmeye devam etmek için bu mesaja yanıt verebilirsiniz.`

WhatsApp, görüşmeyi başlatmak için onaylı metin ve alıcı izni ister. Müvekkilin son mesajından sonraki 24 saat içinde serbest metinle yanıt verilebilir. Ücretler mesaj türüne ve ülkeye göre değişir. [Resmî mesajlaşma kuralları](https://whatsappbusiness.com/policy/), [resmî ücretlendirme](https://whatsappbusiness.com/products/platform-pricing/).

## Doğrulamanın sınırı

Geliştirme denemeleri uydurma numaralarla ve taklit hizmet yanıtlarıyla yapıldı; gerçek Meta hesabına gönderim yapılmadı. İmza, tekrar önleme, mesaj süresi, izin kapatma, randevu iptali ve tarih/yer değişikliği denendi. Tam proje denemelerinin sayısı 222. Tarayıcı adresi güvenle doğrulanamadığı için bilgisayar kullanım aracı görünüm kontrolünü sonlandırdı; görsel doğrulama tamamlanmış kabul edilmemelidir.
