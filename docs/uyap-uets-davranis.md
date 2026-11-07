# UYAP / UETS eklentisi: desteklenen davranış

Tarih: 7 Kasım 2026. Eklenti (`uyap-uets-eklentisi/`) ile sunucu (`apps/imports/portal_*.py`) arasındaki sözleşmenin özeti. Davranış değişirse bu tablo ve `tests/test_portal_*.js` birlikte güncellenir.

## Ortam matrisi

| Durum | Geliştirme (`DEBUG=True`) | Üretim (`DEBUG=False`) |
|---|---|---|
| Eşleştirme sayfası (`/portal-inceleme/baglanti/`) | Açık | **404**: `check_import_access` `RuntimeError` verir |
| Eklentiden veri alma (`/portal-inceleme/eklentiden-al/`) | Çalışır | Kapalı: bağlantı sahibi için erişim denetimi başarısız, veri alınmaz |
| Durum bildirimi, isim kontrolü | Çalışır | Kapalı |
| Eklenti davranışı | Taramayı başlatır, sunucu reddedince `sunucu_yok` der ve 5 dakika sonra yeniden dener | Aynı; sunucu hep reddeder |

Yani canlı UYAP/UETS aktarımı şu an yalnızca geliştirme modunda çalışır. Üretimde açmak ayrı bir karardır (güvenlik ve izin değerlendirmesi gerekir).

## Eklenti tarama davranışı

- **Başlatma:** Eşleştirilmiş eklenti, açık UYAP veya UETS sekmesi bulursa tarar. Sekme yoksa durum `sekme_yok` olur. Sayfadaki avukat adı sunucudaki izinli kişiyle eşleşmeden tarama başlamaz (`bridge.js`, `account-name.js`).
- **UYAP:** Altı kategori (Ceza, Hukuk, İcra, İdari Yargı, Satış Memurluğu, Arabuluculuk), her yargı birimi için açık ve kapalı dosyalar 10'luk sayfalarla **eksiksiz** taranır (örnekleme yok). Uç noktalar arası en az 5 sn beklenir.
- **Dosya başına istekler:** dosya ayrıntısı, taraf bilgileri, evrak listesi (sayfalı, içerik indirilmez), icra dosyalarında hesap bilgisi ve tahsilat/reddiyat yanıtı. Dosya türü kodu yoksa finans yanıtı istenmez ve tarama `eksik` sayılır.
- **Yarım kalan tarama:** Tamamlanan dosyaların izi (SHA-256) tarayıcıda saklanır; kesilen tarama sonraki seferde bitmiş dosyaları yeniden sorgulamaz. Tarama bitince iz silinir.
- **UETS:** Tebligat listesi 50'lik sayfalarla alınır; her tebligatın ayrıntısı ve ekleri (en çok 100 belge, 20 MB) sunucuya gönderilir.
- **Durumlar:** `tamamlandi`, `eksik` (bir kayıt alınamadı), `oturum_yok`, `sunucu_yok`, `izin_yok`, `sekme_yok`, `sekme_hazir_degil`, `durduruldu`.

## Testler

`node --test tests/*.js` (CI'da çalışır). Bu testler yukarıdaki davranışı sınar; kapsam değişince testler de değişmelidir.
