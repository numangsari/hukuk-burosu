# UYAP / UETS eklentisi: desteklenen davranış

Tarih: 7 Kasım 2026. Eklenti (`uyap-uets-eklentisi/`) ile sunucu (`apps/imports/portal_*.py`) arasındaki sözleşmenin özeti. Davranış değişirse bu tablo ve `tests/test_portal_*.js` birlikte güncellenir.

## Kim, nerede çalıştırır

- **Model:** Her avukat kendi bilgisayarında eklentiyi kurar, UYAP/UETS'e kendi hesabıyla girer ve eklentiyi sunucuyla eşleştirir; veri otomatik akar. Tek avukatlı ofiste yalnızca o avukatın bilgisayarı yeterlidir. İstenirse ofiste sürekli açık tek bir bilgisayar da (Chrome, eklenti ve UYAP açık) toplayıcı olarak kullanılabilir.
- **Eşleştirme (`/portal-inceleme/baglanti/`):** Yalnızca ofis ağından (RFC 1918 veya yerel) açılır. Yönetici her zaman eşleştirebilir. Avukat (kıdemli avukat, avukat) yalnızca yönetici ona UYAP veya UETS izni verdiyse eşleştirebilir. Stajyer, katip ve sekreter eşleştiremez (404).
- **Veri kaynağı:** Gelen veri, UYAP/UETS sayfasındaki avukat adının sunucudaki izinli kişiyle (`PortalLawyerAccess`) eşleşmesine göre o kişiye bağlanır. Bağlantı sahibi ile veri sahibi aynı olmak zorunda değildir.
- **Ortam:** Aktarım `DEBUG` ayarından bağımsızdır; üretimde de çalışır.

## Durum göstergesi (üst çubuk)

- Her bağlantı için UYAP ve UETS ayrı değerlendirilir. **Aktif:** eklenti son 3 dakikada haber verdi ve son tarama sonucu oturumun açık olduğunu gösteriyor (`basladi`, `tamamlandi`, `eksik`). **Pasif:** eklenti sessiz ya da durum `oturum_yok`, `sekme_yok`, `sunucu_yok`, `izin_yok`, `sekme_hazir_degil`, `bekliyor`.
- Genel ışık: hepsi aktif yeşil, hiçbiri aktif değil kırmızı, karışık sarı, eşleşmiş eklenti yoksa gri. Üzerine gelince avukat listesi ve son başarılı aktarım saati görünür (yalnızca yönetici ve avukatlara; diğerleri yalnızca ışığı görür).
- **Sınır:** Oturum bilgisi son taramanın sonucudur. Eklenti oturumu ayrıca yoklamadığı için oturum iki taramanın arasında düşerse gösterge geç fark eder. Gerçek oturum denetimi için UYAP'ta hafif bir yoklama isteği keşfedilmelidir.

## Eklenti tarama davranışı

- **Başlatma:** Eşleştirilmiş eklenti, açık UYAP veya UETS sekmesi bulursa tarar. Sekme yoksa durum `sekme_yok` olur. Sayfadaki avukat adı sunucudaki izinli kişiyle eşleşmeden tarama başlamaz (`bridge.js`, `account-name.js`).
- **UYAP:** Altı kategori (Ceza, Hukuk, İcra, İdari Yargı, Satış Memurluğu, Arabuluculuk), her yargı birimi için açık ve kapalı dosyalar 10'luk sayfalarla **eksiksiz** taranır (örnekleme yok). Uç noktalar arası en az 5 sn beklenir.
- **Dosya başına istekler:** dosya ayrıntısı, taraf bilgileri, evrak listesi (sayfalı, içerik indirilmez), icra dosyalarında hesap bilgisi ve tahsilat/reddiyat yanıtı. Dosya türü kodu yoksa finans yanıtı istenmez ve tarama `eksik` sayılır.
- **Yarım kalan tarama:** Tamamlanan dosyaların izi (SHA-256) tarayıcıda saklanır; kesilen tarama sonraki seferde bitmiş dosyaları yeniden sorgulamaz. Tarama bitince iz silinir.
- **UETS:** Tebligat listesi 50'lik sayfalarla alınır; her tebligatın ayrıntısı ve ekleri (en çok 100 belge, 20 MB) sunucuya gönderilir.
- **Durumlar:** `tamamlandi`, `eksik` (bir kayıt alınamadı), `oturum_yok`, `sunucu_yok`, `izin_yok`, `sekme_yok`, `sekme_hazir_degil`, `durduruldu`.

## Testler

`node --test tests/*.js` (CI'da çalışır). Bu testler yukarıdaki davranışı sınar; kapsam değişince testler de değişmelidir.
