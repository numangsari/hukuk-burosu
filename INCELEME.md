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

### 4. Dosyalar — inceleme büyük ölçüde tamam, son sekmeler kaldı
**Devam noktası:** Aşağıdakiler kullanıcıyla canlı ekranda gözden geçirildi ve onaylandı: yeni dosya formu (iki sütun, taraflar listesi + pop-up, ek müvekkiller, ilgili dosya oluştur), dosya listesi (sütun sırası, renkli tür/durum düğmeleri, bağlı dosya kümeleme ve "+X dosya bağlı"), açık/kapalı + aşama/kapanma modeli (kaynak `aşamalar.txt`), dosya özeti, Taraflar (sol/sağ yan), Görevler (aktif/tamamlanan, sıralama), Safahat (bağlı dosyaların tek akışı, ortak muhasebe), avukatlık sözleşmesi, numara ekleri (Esas/İcra/Soruşturma/Arabuluculuk/Karar), tebligatın kaldırılması.
- İcra ekleri: kapanışta çoklu tahsilat ve otomatik muhasebe; Haciz takibi sekmesi ve yenileme günü görev oluşturma; dosya listesinde ayrı AŞAMA sütunu/süzgeci. Bu ekranlar kullanıcıyla gözden geçirilecek.
- Kalan kontroller: Belgeler (yükleme ve doğru klasöre kopya kullanıcıyla doğrulandı; klasör adları müvekkil adı ve kurum/numara düzenine çevrilir), Geçmiş sekmesi, dosya silinince bağlı grup ve ek müvekkil davranışı, arama ve süzgeç ayrıntıları, silme yetkileri.
- Bilinen sınırlar: bağlı dosya kümelemesi yalnızca gösterilen sayfa içinde; klasör yapısı yalnızca asıl müvekkili kullanır; sözleşmedeki vekalet ücreti muhasebe kaydıyla bağlı değildir (yalnızca öneri).
- Kullanıcı kararları (uygulandı): tebligat kaldırıldı; safahat aşama kaydı değil bağlı dosyalardır; bağlantıyı koparma yönetici ve avukatlarda; bağlanacak dosyaların en az bir ortak müvekkili olmalı; ek müvekkilin kendi sıfatı vardır; bağlı dosyalar aynı fiziki arşiv yerini paylaşabilir (veritabanı tekillik kısıtı kaldırıldı, form denetler).

### 5. Duruşma ve tebligat — kullanım dışı
- Kullanıcı kararıyla duruşma bölümü kaldırıldı; eski kayıtlar korunur. Tebligat daha önce kaldırılmıştı.

### 6. Görevler
- Liste kapsamları (Bana atanan, Kontrolümde, Oluşturduklarım, Tümü), durum/tür süzgeci, arama.
- Form: müvekkile göre dosya süzme; dosya seçince müvekkil ve varsayılan sorumlu/kontrolcü; stajyer sorumluysa kontrolcü bağlı avukatı; ad büyük harf; kontrolcü ≠ sorumlu.
- Onay döngüsü: kontrole gönder (sorumlu veya yönetici), onayla/revizyon (açıklama zorunlu), yeniden aç; "Yeni görev", "Revizyon istendi", "Onaylandı" rozetleri.
- **Planlanan:** onaylanan görevin "tamamlanma" prosedürünü kullanıcıyla tasarla; "Onaylandı" satırının ana sayfadan ne zaman kalkacağı buna bağlı (şimdilik yalnızca yeniden açılınca kalkar).
- Görev belgeleri: sürümler, belge zorunlu türler, onayda dosyaya ve ofis klasörüne yayın.
- Yorumlar, geçmiş, silme yetkisi (oluşturan veya yönetici).

### 7. Takvim
- Google Takvim iCal bağlantısı ve açık görevlerin son günleri: ana sayfada 7 gün, takvim sayfasında ay/hafta görünümü. Görevler son günlerinde saat alanında `GÖREV`, başlıkta yalnızca görev adıyla görünür ve tıklanınca açılır; tamamlananlar gösterilmez. Google etkinliklerinin tümü gösterilir. Google bağlı değilken veya erişilemezken de görevler görünür. Duruşma ve randevu eklenmez; dosya eşleştirmesi veya etkinlikten görev oluşturma yapılmaz.
- Yoğun günlerde etkinlik listesi kendi içinde kayar; tarih başlığı sabittir.
- Google bağlantısı (Ayarlar > Google Takvim), erişilemeyince uyarıyla son kopya.

### 8. Muhasebe
- Liste: süzgeçler (müvekkil, dosya, tür, tarih, iptaller), toplamlar yalnızca bakiye yetkilisine.
- Kayıt: müvekkil zorunlu, dosya isteğe bağlı; türler (vekalet ücreti, masraf, tahsilat, karşı taraftan tahsilat, müvekkile ödeme, mahsup); makbuz yükleme; emanet eksiye düşebilir.
- İptal: neden zorunlu, herkes iptal edebilir; iptal edilen satırın görünümü.
- Cari/emanet/net hesapları, ekstre; bakiye görme yetkisi (Ayarlar > Bakiye görme yetkisi).

### 9. Raporlar
- 6 rapor: önizleme, Excel, PDF (Türkçe karakter); finansal raporlar yalnızca bakiye yetkilisine; parametreler.

### 10. Hatırlatmalar
- Sistem içi bildirimler ve WhatsApp hatırlatmaları kullanım dışı. Görevler ana sayfa rozetleriyle izlenir.

### 11. Aktivite kaydı
- `/aktivite/` süzgeçleri; yönetici herkesi, diğerleri kendini görür; müvekkil/dosya "Geçmiş" sekmeleri; giriş/çıkış kayıtları.

### 12. WhatsApp — kullanım dışı
- Ekranlar, gelen bildirim adresi ve otomatik gönderim kaldırıldı. Gelecekte tekrar kurulabilmesi için kod ve eski kayıtlar korunur. WhatsApp Web kısayolu bağımsızdır.

### 13. Yönetici ayarları
- Ofis bilgileri, kullanıcılar (rol, unvan, bağlı avukat, PIN sıfırlama, pasife alma), görev türleri (belge zorunlu), bakiye görme yetkisi, belge klasörü (yazma testi), yedekleme (saat, hedef klasör, şimdi yedek al, geçmiş), Google Takvim, boşta kalma süresi.

### 14. Excel'den içe aktarım
- Şablon, önizleme, hatalı satır davranışı, tekrar engelleme (aynı dosya, aynı kimlik, aynı devir kaydı).

### 15. Sürüm ve yayın düzeni
- Ekranda sürüm numarası, `CHANGELOG.md`, branch düzeni, sürüm çıkarma kontrol listesi (kurulum paketi derleme, temiz Windows'ta kurulum denemesi, yedekten dönüş provası).
