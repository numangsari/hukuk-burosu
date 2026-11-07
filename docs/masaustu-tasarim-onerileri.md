# Masaüstü odaklı tasarım önerileri

Tarih: 7 Kasım 2026

**Kullanım önceliği:** Kullanıcının belirttiği üzere kullanımın yaklaşık %99’u bilgisayarda olacak. Tasarım çalışmaları masaüstünde hızlı, okunaklı ve yoğun veriyle çalışmaya odaklanmalı. Mobil iyileştirmeler düşük önceliklidir.

**Belge durumu:** Bu metin öneri ve önceliklendirme belgesidir. Burada anlatılan değişiklikler uygulanmış özellikler değildir. Uygulama öncesinde ekran tasarımları ve iş kuralları ayrıca değerlendirilmelidir.

## 1. Tasarım yönü

Mevcut lacivert–gri renk düzeni, sınırlı altın vurgusu ve Inter yazı tipi korunabilir. Temel yatırım; daha fazla işe yarar bilgiyi okunaklı göstermek, kayıtlar arasında geçişi hızlandırmak ve tekrarlanan işlemleri azaltmak olmalı.

Birincil değerlendirme boyutları:

- 1366×768 dizüstü ekranı.
- 1920×1080 masaüstü ekranı.
- Tarayıcı yakınlaştırması ve klavye kullanımı da doğrulanmalı.

Bilgisayarda dosyaları karşılaştırmak, sıralamak ve taramak için tablolar temel görünüm olarak korunmalı. Bilgi yoğunluğu, yazıları aşırı küçülterek değil; gereksiz boşlukları, büyük kartları ve tekrarlanan başlıkları azaltarak artırılmalı.

## 2. Öneriler

| Alan | Önerilen değişiklik | Beklenen fayda |
|---|---|---|
| Ekran yoğunluğu | Büyük kartları ve gereksiz boşlukları küçült; aynı ekranda daha fazla kayıt göster | Daha az kaydırma, daha kolay karşılaştırma |
| Tablolar | Sabit başlık, yeniden boyutlandırılabilir sütunlar, sütun göster/gizle ve kayıtlı sıralama | Kullanıcının işine uygun çalışma alanı |
| Filtreler | Sık kullanılan filtreleri üstte tek sırada tut; gelişmiş filtreleri açılabilir bölüme al | Tekrarlanan aramaları hızlandırma |
| Kayıt inceleme | Listeyi terk etmeden sağ panelde görev, belge veya dosya özeti aç | Liste bağlamını kaybetmeden işlem yapma |
| Dosya detayları | Geniş ana çalışma alanı ve sağda dar süre/sorumlu/sıradaki iş bölümü | Önemli bilgilere sürekli erişim |
| Navigasyon | Daraltılabilir sol menü ve son açılan dosyalara hızlı erişim | Kullanılabilir yatay alanı artırma |
| Klavye kullanımı | Arama, kaydetme, sonraki kayıt ve panel kapatma için tutarlı kısayollar | Fareye bağımlılığı azaltma |
| Görsel düzen | Tutarlı satır hizaları, okunaklı tarih/tutarlar, hafif ayırıcılar ve belirgin seçili satır | Uzun listeleri taramayı kolaylaştırma |
| Çoklu işlem | Uygun listelerde satır seçimi ve kontrollü toplu atama/dışa aktarma | Tekrarlı işlemleri azaltma |

## 3. Liste ve sağ inceleme paneli

Görev listesinde bir satıra tıklandığında sağ tarafta görev açıklaması, belgeler ve yetkili onay işlemleri açılabilir. Kullanıcı incelerken liste, filtreler, sıralama ve kaydırma konumu korunmalı.

- Panel kapandığında odak ilgili satıra dönmeli.
- Seçili kayıt ve panel başlığı açıkça anlaşılmalı.
- Dar dizüstü ekranlarında panel isteğe bağlı açılmalı; iki alan okunamayacak kadar sıkıştırılmamalı. Gerektiğinde tam detay sayfasına geçiş sunulmalı.
- Kaydedilmemiş düzenlemeler varken kayıt değiştirildiğinde kullanıcı uyarılmalı.
- Panelde görüntüleme ve değişiklik izinleri tam sayfadakiyle aynı olmalı.

İlk pilot için görev listesi uygundur. Aynı yaklaşım, kullanım sonuçlarına göre dosya ve belge listelerine yayılabilir.

## 4. Muhasebe ekranı

Dört büyük özet kartı yerine üstte kompakt, tek satırlık mali özet önerilir. Hemen altında filtreler ve hareket tablosu bulunmalı; ekranın büyük bölümü gerçek hareketlere ayrılmalı.

- Alacağımız ve borcumuz yönleri metinle açıkça gösterilmeli; anlam yalnızca renge bağlanmamalı.
- Tutarlar sağa hizalanmalı ve rakamlar eş genişlikli gösterilmeli.
- Tarihler tutarlı genişlikte olmalı.
- Uzun açıklamalar satırı gereksiz büyütmeden genişletilebilmeli veya inceleme panelinde okunabilmeli.
- Mali özet ve dışa aktarma seçenekleri mevcut yetki kurallarına tabi olmalı.
- Tarih aralığı ve seçili filtreler özet toplamların hangi kayıtları kapsadığını açıkça belirtmeli.

## 5. Dosya detay ekranı

Önerilen yerleşim:

1. Üstte kompakt dosya kimliği: dosya adı, esas numarası, müvekkil, durum ve temel işlemler.
2. Ana alanda seçilen bölüm: belgeler, görevler, safahat veya muhasebe.
3. Sağda sıradaki işlem, yakın süreler ve sorumlular.
4. Uzun içerikte dosya başlığı ve bölüm navigasyonu görünür kalmalı; sabit alanlar 768 px yüksekliğinde çalışma alanını tüketmemeli.

Mevcut sekmeler ve dosya özeti bu düzenin temelidir; aynı bilgiyi gösteren paralel ekranlar oluşturulmamalı. Önerilen tarih ile avukat tarafından teyit edilmiş tarih görsel olarak ayrılmalı.

## 6. Tipografi ve görsel standartlar

- Gövde metni yaklaşık 14–15 px olabilir; ikincil metinlerin okunabilirliği ve kontrastı ayrıca kontrol edilmeli.
- Kritik tarih, tutar ve sorumlular yeterli görsel ağırlığa sahip olmalı.
- Boşluklarda 8/16/24 px gibi tutarlı bir ölçek kullanılmalı.
- Mavi ana işlem, kırmızı tehlike/gecikme, amber dikkat, yeşil tamamlanma için tutarlı kullanılmalı.
- Altın rengi marka ve küçük vurgu alanlarıyla sınırlı kalmalı.
- Seçili satır, fareyle üzerine gelinen satır ve klavye odağı birbirinden ayırt edilmeli.
- Sık ve önemli işlemlerde ikon + metin tercih edilmeli. Silme gibi işlemler bağlama uygun ayrı menüde ve gerekli onayla sunulmalı.
- Rahat/kompakt görünüm seçeneği değerlendirilebilir; ilk sürümde çok sayıda kişiselleştirme ayarı yerine iyi bir varsayılan tercih edilmeli.
- Tarih, para ve takvim ifadeleri Türkçe biçimde tutarlı gösterilmeli.

## 7. Uygulama önceliği

1. **Görev, dosya ve muhasebe tablolarını iyileştir:** satır yoğunluğu, sabit başlık, sütun hizaları ve okunabilirlik.
2. **Filtre ve sütun tercihlerini kaydet:** kişisel görünümler; kayıt dönüşünde filtre/sayfa konumunu koruma.
3. **Liste yanında inceleme paneli ekle:** önce görevlerde pilot, ardından gerekirse diğer listeler.
4. **Dosya detayını geniş ekran için düzenle:** kompakt başlık, ana içerik ve yardımcı bilgi bölümü.
5. **Klavye kısayolları ve son açılan kayıtları ekle:** tarayıcı kısayollarıyla çakışmayı önle, kısayolları görünür biçimde belgele.

Mobil kart dönüşümleri, kapsamlı offline kullanım ve yalnız görsel yenilik amacıyla teknoloji değişimi bu planın öncelikleri değildir.

## 8. Kabul ölçütleri

- Her iki hedef ekran boyutunda temel işlem düğmeleri ve kritik bilgiler erişilebilir olmalı.
- Daha fazla kayıt gösterilirken metin okunabilirliği, odak görünürlüğü ve yakınlaştırma desteği korunmalı.
- İnceleme paneli açılıp kapatıldığında filtre, sıralama, sayfa ve kaydırma konumu kaybolmamalı.
- Kullanıcı tercihleri erişim hakkı kazandırmamalı; yetkisi kaldırılan kayıt son açılanlar ve aramada görünmemeli.
- Toplu işlemler sunucuda kayıt bazlı izinleri doğrulamalı; onay akışını atlamamalı. Hukuki süre ve mali iptal gibi kritik işlemler genel toplu işlem kapsamına otomatik alınmamalı.
- Kullanıcılar klavyeyle filtreye, tabloya, inceleme paneline ve ana işlemlere ulaşabilmeli.
- Liste performansı ve sık yapılan işlerin tamamlanma süresi önce/sonra ölçülmeli; ölçüm yapılmadan verim artışı oranı iddia edilmemeli.
