# Adım adım sistem incelemesi

Kullanıcı sistemi modül modül kendisi deniyor ve revizyon veriyor. Bu dosya, incelemeyi hangi araçla (Claude Code veya Codex) sürdürürse sürdürsün aynı düzende devam etmek içindir. Proje kuralları ve mimari `CLAUDE.md`'dedir; burada yalnızca inceleme süreci ve adımlar vardır.

## Çalışma düzeni
1. Sıradaki adımın kontrol listesini kullanıcıya Türkçe, kısa maddeler halinde ver. Hangi kullanıcıyla girileceğini belirt (yönetici: Ali Samet; stajyer denemesi: Ecenur; avukat: İrfan veya Nursu). Dev ortamında herkesin PIN'i ortak başlangıç PIN'idir; PIN'i dosyaya veya koda yazma, kullanıcıya sor.
2. Kullanıcı bulduklarını tek mesajda yazar. Her revizyonu uygula. Veri modelini, yetkiyi veya geri dönüşü zor bir davranışı etkileyen belirsiz noktada önce soru sor (seçenekli soru, önerilen seçenek başta).
3. Her revizyondan sonra: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`; arayüz değişikliğini tarayıcıda gör (dev sunucusu `uv run python manage.py runserver 0.0.0.0:8000`). Doğrulanmayanı "tamamlandı" diye sunma.
4. Kalıcı kural veya mimari değiştiyse `CLAUDE.md`'yi güncelle (bu dosyayı da adım durumu için güncelle).
5. Kullanıcı adımı onaylayınca adımın işini commit'le (Türkçe, emir kipinde, araç adı ve atıf satırı yok); push yalnızca kullanıcı onayıyla.
6. Yeni model alanında migration üret; dev DB'ye uygula. Test veritabanı eski şemada kalırsa `pytest --create-db`.

## Arayüzde uyulan kararlar (incelemede çıkanlar)
- Sayfa başlığı altına sabit tanıtım metni yok.
- Bilgi yoğun ekranlar tek sütun bırakılmaz; uzun formlarda `.form-masonry` ile dengeli iki sütun.
- Müvekkil adı, dosya konusu, görev adı her zaman büyük harf.
- Listelerde süzgeç + sıralama açılır listesi; sıralama/süzgeç HTMX ile yenilenir.
- Sistem içi bildirim (zil) yok; görev durumları ana sayfadaki rozetlerle izlenir.
- Çıkar çatışması kontrolü yok. Hatalı PIN'de kilit yok.

## Adımlar ve durum

### 1. Giriş, oturum ve kişisel ayarlar — ✅ tamam
### 2. Ana sayfa, üst çubuk, kenar menü, arama — ✅ tamam
### 3. Müvekkiller — ✅ revizyonlar uygulandı ve commit'lendi
Kullanıcının henüz tek tek bakmadığı kontrol maddeleri (Adım 4'e geçmeden sorulabilir):
- Liste: V-no sütunu başta, varsayılan sıra (V-no yeniden eskiye, numarasızlar sonda, en yeni kayıt önce), sıralama menüsü, süzgeçler.
- Form: büyük harf dönüşümü; avukat seçince bağlı stajyer gelmesi (Ayarlar > Kullanıcılar'da stajyerlere bağlı avukat girilmiş olmalı); V-no otomatik/elle/tekrarın reddi; boş satırların yok sayılması; hatada satırların korunması; satır silmenin yalnızca yöneticide olması.
- Detay: başlık (ad, V-kodu / "Vekalet yok", açık/kapalı dosya sayısı), Genel bilgiler iki sütun, Dosyalar sekmesi süzgeç/sıralama, Muhasebe sekmesi (bakiye yalnızca yetkiliye), Raporlar (önizle/Excel/PDF), Geçmiş.
- Silme: yalnızca yönetici, düzenleme ekranının altındaki düğme, onay sayfası ve birlikte silinecek kayıt sayıları.

### 4. Dosyalar — inceleme sürüyor
**Devam noktası:** Yeni dosya formunun son düzenlemeleri kullanıcıyla ekranda doğrulanacak; bu adım henüz onaylanmadı. Son istekte kurum adı ile yıl/numara girişlerinin hizası düzeltildi, notlar iki sütunun dışına ve kaydetme çubuğunun hemen üstüne taşındı. Taraf ekleme kodu form alanlarını `$root` üzerinden bulacak şekilde değiştirildi; canlı tarayıcıda çalıştığı henüz doğrulanmadı.

- İlk kontrol: kurum ve dosya numarası hizası, Sorumlular bölümünün bölünmemesi, notların en altta olması; Taraf ekle ile art arda satır ekleme ve tür değişince sıfat seçenekleri.
- Son kod denetimi: 271 deneme ve iki biçim/yazım denetimi geçti. Düğme için ayrı çalıştırılan üç JavaScript denemesi canlı tarayıcı kontrolünün yerine geçmez.
- Chrome bağlantısında pencere görülüyor, fakat tarayıcı bağlantı aracı kullanılamıyor; adres doğrulanamadığı için bilgisayar kullanım aracı da kontrolü durdurdu. Bağlantı çözülmedi. Kullanıcı bağlantı incelemesini durdurdu; yeniden istemeden bu incelemeye devam etme.
- Çalışma alanında önceki oturumlardan da çok sayıda değişiklik var; bu oturumdaki işler ayrı bir commit veya push yapılmadan yerelde duruyor. Mevcut değişiklikleri koru.

- Liste: sütunlar, süzgeçler (tür, durum, avukat, "benim dosyalarım", müvekkil), arama, sıralama, sayfalama.
- Yeni dosya formu: her türde Konu; Sözleşme/Diğer dışında büyük harf Kurum Adı ve yıl + sayısal Dosya Numarası; bu türlerde görünen dosya adı kurum + numara, Sözleşme/Diğer için konu; varsayılanı bugün olan açılış tarihi; değer/durum/aşama/kapanış alanları formda yok; fiziki arşiv için klasör no + dosya no ve birleşimin tekrar reddi; türe göre değişen alanlar (icra türü, suç, arabulucu); müvekkil seçince avukat/stajyer gelmesi; avukat seçince bağlı stajyer; konu büyük harf; kurum önerileri.
- Düzenleme: bağlı görev/muhasebe hareketi varsa müvekkil değiştirilemez; klasör adı.
- Taraflar: müvekkilin sıfatı ve diğer taraflar aynı bölümde; sıfatlar dosya türüne göre; oluşturma/düzenlemede yeni taraf satırları ve hata halinde korunmaları.
- Detay: başlık ve sekmeler, taraf ekleme (aynı TCKN/VKN'de mevcut kayıt kullanılır), karşı taraf çıkarma yalnızca yönetici; belgeler (yükleme, izinli türler, ofis klasörüne kopya, silme yetkisi); zaman çizelgesi (elle not); muhasebe sekmesi; geçmiş.
- Silme: yalnızca yönetici; bağlı kayıt varken davranış (müvekkil silmeyle tutarlı olmalı mı, kullanıcıya sor).
- Bilgi yoğun ekranları iki sütuna yayma kuralını uygula.

### 5. Duruşma ve tebligat
- Duruşma/keşif/bilirkişi ekleme, düzenleme; sonuç girilince zaman çizelgesine düşmesi; silme yalnızca yönetici.
- Tebligat: son gün elle, "gereği yapıldı" işareti, süresi geçenlerin ana sayfada görünmesi.
- Takvim ve ana sayfa yansımaları (Adım 7'deki takvim kararına göre).

### 6. Görevler
- Liste kapsamları (Bana atanan, Kontrolümde, Oluşturduklarım, Tümü), durum/tür süzgeci, arama.
- Form: müvekkile göre dosya süzme; dosya seçince müvekkil ve varsayılan sorumlu/kontrolcü; stajyer sorumluysa kontrolcü bağlı avukatı; ad büyük harf; kontrolcü ≠ sorumlu.
- Onay döngüsü: kontrole gönder (sorumlu veya yönetici), onayla/revizyon (açıklama zorunlu), yeniden aç; "Yeni görev", "Revizyon istendi", "Onaylandı" rozetleri.
- **Planlanan:** onaylanan görevin "tamamlanma" prosedürünü kullanıcıyla tasarla; "Onaylandı" satırının ana sayfadan ne zaman kalkacağı buna bağlı (şimdilik yalnızca yeniden açılınca kalkar).
- Görev belgeleri: sürümler, belge zorunlu türler, onayda dosyaya ve ofis klasörüne yayın.
- Yorumlar, geçmiş, silme yetkisi (oluşturan veya yönetici).

### 7. Takvim
- **Planlanan:** takvim yalnızca Google Takvim'i gösterecek; görev/duruşma/tebligat son günleri takvime eklenmeyecek; Google etkinlikleri sisteme kayıt olarak aktarılmayacak. Bir Google etkinliğine sistemden sorumlu atanabilecek; atanınca o etkinlikle ilgili görev oluşacak ve tamamlanması istenecek (ör. duruşma hakkında müvekkile WhatsApp'tan bilgi vermek). Ana sayfadaki Takvim paneli de buna göre değişecek.
- Ay/hafta görünümü, Google bağlantısı (Ayarlar > Google Takvim), erişilemeyince son kopya.

### 8. Muhasebe
- Liste: süzgeçler (müvekkil, dosya, tür, tarih, iptaller), toplamlar yalnızca bakiye yetkilisine.
- Kayıt: müvekkil zorunlu, dosya isteğe bağlı; türler (vekalet ücreti, masraf, tahsilat, karşı taraftan tahsilat, müvekkile ödeme, mahsup); makbuz yükleme; emanet eksiye düşebilir.
- İptal: neden zorunlu, herkes iptal edebilir; iptal edilen satırın görünümü.
- Cari/emanet/net hesapları, ekstre; bakiye görme yetkisi (Ayarlar > Bakiye görme yetkisi).

### 9. Raporlar
- 6 rapor: önizleme, Excel, PDF (Türkçe karakter); finansal raporlar yalnızca bakiye yetkilisine; parametreler.

### 10. Hatırlatmalar
- Sistem içi bildirimler kaldırıldı. Kalan: WhatsApp hatırlatmaları (Adım 12) ve ana sayfa rozetleri. Kullanıcıya başka hatırlatma ihtiyacı olup olmadığını sor.

### 11. Aktivite kaydı
- `/aktivite/` süzgeçleri; yönetici herkesi, diğerleri kendini görür; müvekkil/dosya "Geçmiş" sekmeleri; giriş/çıkış kayıtları.

### 12. WhatsApp
- Mesaj kutusu, müvekkil ekranı, randevular, izin/alıcı seçimi, hazır metinler. Canlı bağlantı `WHATSAPP.md`'deki adımlarla kullanıcıyla kurulacak (gerçek gönderim henüz yapılmadı).

### 13. Yönetici ayarları
- Ofis bilgileri, kullanıcılar (rol, unvan, bağlı avukat, PIN sıfırlama, pasife alma), görev türleri (belge zorunlu), bakiye görme yetkisi, belge klasörü (yazma testi), yedekleme (saat, hedef klasör, şimdi yedek al, geçmiş), Google Takvim, boşta kalma süresi.

### 14. Excel'den içe aktarım
- Şablon, önizleme, hatalı satır davranışı, tekrar engelleme (aynı dosya, aynı kimlik, aynı devir kaydı).

### 15. Sürüm ve yayın düzeni
- Ekranda sürüm numarası, `CHANGELOG.md`, branch düzeni, sürüm çıkarma kontrol listesi (kurulum paketi derleme, temiz Windows'ta kurulum denemesi, yedekten dönüş provası).
