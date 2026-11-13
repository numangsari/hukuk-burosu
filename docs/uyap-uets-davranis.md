# UYAP / UETS eklentisi: desteklenen davranış

Tarih: 7 Kasım 2026. Eklenti (`uyap-uets-eklentisi/`) ile sunucu (`apps/imports/portal_*.py`) arasındaki sözleşmenin özeti. Davranış değişirse bu tablo ve `tests/test_portal_*.js` birlikte güncellenir.

## Kim, nerede çalıştırır

- **Model:** Eklenti yalnızca **ana bilgisayarda** (sunucunun kurulu olduğu, sürekli açık bilgisayar) kurulur. UYAP veya UETS o bilgisayarın Chrome'unda açık ve oturum geçerliyken aktarım kendiliğinden başlar; sekme kapanınca veya oturum düşünce durur. Diğer kullanıcılar sisteme yalnızca tarayıcıdan bağlanır, eklenti kurmaz.
- **Birden fazla avukat:** Başka bir avukatın verisi için o avukatın UYAP/UETS hesabı yine ana bilgisayarda açılır; aktarım o hesap için başlar. Aynı anda birden fazla hesap veya birden fazla bilgisayardan aktarım **şimdilik desteklenmez** (sonraki iş).
- **Eşleştirme (`/portal-inceleme/baglanti/`):** Yalnızca ofis ağından açılır ve yalnızca yönetici eşleştirir; diğer roller 404 alır.
- **Veri kaynağı:** Gelen veri, UYAP/UETS sayfasındaki avukat adının sunucudaki izinli kişiyle (`PortalLawyerAccess`, Ayarlar > Eklenti bağlantıları) eşleşmesine göre o kişiye bağlanır. Adı izinli kimseyle eşleşmeyen hesaptan veri alınmaz.
- **Ortam:** Aktarım `DEBUG` ayarından bağımsızdır; üretimde de çalışır.

## Oturum yoklaması ve durum göstergesi (üst çubuk)

- **Yoklama (`session.js`):** UYAP/UETS sayfası açıkken dört dakikada bir oturumun geçerli olup olmadığı sorulur (UYAP: `POST /get_avukat_id.ajx`, UETS: `GET /v1/messages?count=1`). `401` veya geçersiz yanıt "oturum kapalı", `200` "oturum açık", ağ ve sunucu hatası "belirsiz" (bildirilmez). Oturum açıksa sayfada görünen hesap adı da bildirilir. Başka veri toplanmaz, yanıt gövdesi okunmaz. Sonuç eklenti durum bildirimiyle (`session: {ok, at, name}`) sunucuya gider; `PortalConnection.*_session_ok/_at` alanlarında saklanır ve ad izinli avukatla eşleşirse `*_account` alanına yazılır.
- **Otomatik başlama:** Oturum kapalıyken (veya ilk kez) açık algılanınca eklenti taramayı beklemeden başlatır (iki saatlik süre kuralı yine geçerlidir). Son tarama `izin_yok` (avukata henüz izin verilmemiş veya ad eşleşmemiş) ya da `sunucu_yok` ile kaldıysa iki saat beklenmez; oturum yoklaması veya zamanlayıcı beş dakikada bir yeniden dener. Sekme kapanınca veya oturum düşünce tarama durur.
- **Gösterge (herkese görünür):** Üst çubukta UYAP ve UETS için ışık; üzerine gelince Ayarlar > Eklenti bağlantıları'nda otomasyon izni verilmiş her avukat ve o an aktarımı olup olmadığı listelenir. Bir avukatta **aktarım var**: hesabı ana bilgisayarda açık, oturumu geçerli ve eklenti son 3 dakikada haber verdi (oturum bilgisi 10 dakikadan eskiyse son tarama sonucuna bakılır; `izin_yok` ve `sunucu_yok` durumunda aktarım yok sayılır).
- **Genel ışık:** hepsinde aktarım varsa yeşil, hiçbirinde yoksa kırmızı, karışıksa sarı, otomasyon izni verilmiş avukat yoksa gri. Yalnızca aktarımı olması gereken avukatlara izin verilmelidir; izin verilen ama hesabı ana bilgisayarda açılmayan avukat ışığı sarı tutar.
- **Oturumu canlı tutma:** Yoklama başarılıysa (oturum açık) `session.js` sayfaya hafif bir `mousemove` olayı gönderir; sayfanın kendi boşta kalma sayacı sıfırlanır. Etkisi UYAP/UETS'te uzun süreli gözlemle doğrulanmadı. Sunucu tarafı boşta kalma süresini yoklama isteği uzatmıyorsa ayrı bir yenileme isteği araştırılmalıdır.

## Eklenti tarama davranışı

- **Başlatma:** Eşleştirilmiş eklenti, açık UYAP veya UETS sekmesi bulursa tarar. Sekme yoksa durum `sekme_yok` olur. Sayfadaki avukat adı sunucudaki izinli kişiyle eşleşmeden tarama başlamaz (`bridge.js`, `account-name.js`).
- **UYAP:** Altı kategori (Ceza, Hukuk, İcra, İdari Yargı, Satış Memurluğu, Arabuluculuk), her yargı birimi için açık ve kapalı dosyalar 10'luk sayfalarla **eksiksiz** taranır (örnekleme yok). Sıra: önce **bütün birimlerin açık dosyaları**, sonra açık dosyaların evrakları, en son bütün birimlerin kapalı dosyaları (kapalı dosya sayısı çok fazla olabildiği için). Her turda ağır ceza birimleri (evrakı çok olduğu için) diğer birimlerden sonra taranır. Uç noktalar arası en az 5 sn beklenir.
- **Duruşmalar:** Her tarama başında avukatın önümüzdeki altı aylık duruşmaları `POST /avukat_durusma_sorgula_brd.ajx` (`baslangicTarihi`, `bitisTarihi`, `gg.aa.yyyy`) ile 30 günlük parçalar halinde sorulur (UYAP en fazla bir aylık aralık kabul eder). Gelen duruşmalar sunucuda dosyalarına bağlanır; Google Takvim açıksa takvime de yazılır.
- **Dosya başına istekler:** dosya ayrıntısı, taraf bilgileri, evrak listesi (sayfalı), icra dosyalarında hesap bilgisi, tahsilat/reddiyat yanıtı ve açık dosyalarda **evrakların içeriği** (aşağıda, ikinci turda). Dosya türü kodu yoksa finans yanıtı istenmez ve tarama `eksik` sayılır.
- **Yarım kalan tarama:** Tamamlanan dosyaların izi (SHA-256) tarayıcıda saklanır; kesilen tarama sonraki seferde bitmiş dosyaları yeniden sorgulamaz. Tarama bitince iz silinir.
- **UETS:** Tebligat listesi 50'lik sayfalarla alınır. Yalnızca **son 30 günün** tebligatlarının (`inserttime`) ayrıntısı ve ekleri (en çok 100 belge, 20 MB) sunucuya gönderilir; daha eski tebligatlar atlanır. Liste sıralama yönü doğrulanmadığı için sayfaların tamamı gezilir (hafif istek), yeni mesaj kaçmaz.
- **Durumlar:** `tamamlandi`, `eksik` (bir kayıt alınamadı), `oturum_yok`, `sunucu_yok`, `izin_yok`, `sekme_yok`, `sekme_hazir_degil`, `durduruldu`.

## Keşfedilen uç noktalar (7 Kasım 2026, canlı oturumda doğrulandı)

Veri içermez; yalnızca yol ve yanıt biçimi. UYAP arayüzü değişirse yeniden doğrulanmalıdır.

| Amaç | İstek | Oturum açıkken | Oturum yokken |
|---|---|---|---|
| UYAP oturum yoklaması | `POST /get_avukat_id.ajx` gövde `{}` (sayfanın kendi çağırdığı hafif istek) | `200`, `text/json`, gövde bir sayı | `401`, `text/xml`, `<root><error>nosessionobject</error></root>` |
| UETS oturum yoklaması | `GET https://api.etebligat.gov.tr/v1/messages?sort=inserttime&count=1&start=0` + `Authorization: Bearer <erişim anahtarı>` | `200`, JSON dizi | `401`, JSON nesne |
| UYAP evrak listesi | `POST /list_dosya_evraklar.ajx` `{dosyaId, pageNumber}` | `son20Evrak` dizisi; her öğede `evrakId`, `dosyaId`, `tur`, `tip` (`DOSYA`/`GDN`/`GLN`), `isYetkili`, `ekEvrakListesi`, `birimEvrakNo`, `onaylandigiTarih` | |
| UYAP evrak içeriği | `GET /download_document_brd.uyap?dosyaId=…&evrakId=…` | `200`, `application/pdf`, `Content-Disposition: inline; filename=…`, `Content-Length` yok (akış) | |
| Diğer | `POST /get_evrak_mimeType_brd.ajx` (evrak türü), `GET /view_document_brd.uyap` (görüntüleme) | | |

- UYAP, aynı tarayıcı profilindeki yeni sekmede mevcut oturumu paylaşır; oturum için ayrı giriş gerekmedi.
- Oturum yoklaması UYAP sunucu tarafındaki boşta kalma süresini uzatır mı, doğrulanmadı. Etkisi, uzun süreli gözlemle ölçülmelidir.
- Evrak indirme PDF döndürdü; diğer türlerde (UDF vb.) yanıt biçimi denenmedi.

## Evrak içeriği indirme

- **Kapsam:** Yalnızca **açık** dosyaların evrakları ve varsa ek evrakları indirilir; kapalı dosyaların evrak listesi gelir ama içeriği indirilmez. İndirme **ikinci turda** yapılır: önce bütün birimlerdeki dosyaların bilgisi alınır, sonra açık dosyaların evrakları sırayla iner. Evraklar arasında en az 2,5 sn, diğer istekler arasında 5 sn beklenir; bu yüzden evrak turu uzun sürer (binlerce evrak için saatler). Tarama kesilirse kaldığı yerden sürer.
- **İzleme:** Dosyanın belgeleri tamamlanınca dosya başına tek bir iz (`belge2:<dosya anahtarı>`) tarayıcıda saklanır. Dosya anahtarı birim adı + esas no + dosya türü kodudur; UYAP `dosyaId` her oturumda değiştiği için kullanılmaz, böylece yeniden girişte tamamlanan dosyalar tekrar sorgulanmaz. Dosya yarım kalırsa o dosyanın evrakları yeniden istenir; sunucu aynı evrakı ikinci kez almaz.
- **Sunucu (`type: uyap_document`):** `dosyaId`, `evrakId`, `meta` (tür, tip, onay tarihi), dosya adı ve içerik (base64) gelir. Evrak, dosyanın **Belgeler** sekmesine eklenir (evrak adı UYAP'taki gibi kalır, kategori tahmin edilmez) ve ofis klasörü ayarlıysa dosya klasörünün `UYAP Evrakları` alt klasörüne kopyalanır. UYAP onay tarihi `Document.document_date` alanına yazılır; Belgeler sekmesi bu tarihi gösterir ve belgeleri ona göre (yoksa yüklenme gününe göre) yeniden eskiye sıralar. Aynı `(UYAP dosyası, evrakId)` yeniden alınmaz; kullanıcı belgeyi dosyadan silse bile tekrar indirilmez (`PortalDocument`).
- **Reddedilenler:** 404 dosya yok, 403 evrak başka avukatın dosyasına ait, 409 UYAP dosyası henüz büro dosyasına bağlanmadı (sonraki taramada yeniden denenir), 400 geçersiz (sonraki taramada yeniden denenir); 20 MB üstü evrak istemcide atlanır ve bir daha denenmez. Bunlar taramayı durdurmaz, durum `eksik` olur. 5xx veya ağ hatası taramayı `sunucu_yok` ile durdurur.
- **Belgeler sekmesi:** İki ayrı bölüm. **Büro belgeleri** elle yüklenenlerdir. **UYAP evrakları** ayrı, salt okunur bölümdür: silinemez ve düzenlenemez (sunucu da engeller), yalnızca açılır ve indirilir. Belgeye `kaynak` alanı (`office`/`uyap`) ve UYAP'taki ham evrak adı (`uyap_type`) yazılır.
- **Adlandırma:** Evrak adı UYAP'taki gibi kalır, kategori tahmin edilmez. Başlık `Kapalı Tebligat · 14/10/2026`, dosya adı `14-10-2026 Kapalı Tebligat.pdf` (dosya adında `/` kullanılamaz, bu yüzden tire; ofis klasöründe `UYAP Evrakları` altında düz liste). UYAP bölümünde tarihler `gg/aa/yyyy` gösterilir.
- **Sıralama ve filtre (UYAP bölümü):** Varsayılan UYAP tarihine göre yeniden eskiye; "Evrak adı" ve "UYAP tarihi" başlığına tıklayınca ada (A→Z) veya tarihe göre iki yönde sıralanır. Filtre: UYAP'taki evrak adı (açılır liste, adet ile), arama metni, tarih aralığı. 50'şerli sayfalama.
- **Güvenlik:** PDF imzası denetlenir, tanınmayan uzantılar `.bin` olur, dosya adı temizlenir, her evrak yalnızca UYAP oturumundaki avukatın kendi dosyasına eklenebilir.

## Eklentiyi güncelleme

Eklenti yeniden yüklenince (Chrome > Uzantılar > yenile) açık UYAP/UETS sekmelerinde eski betikler çalışmaya devam eder ve "Extension context invalidated" hatası verebilir. Betikler bunu artık sessizce yok sayıp durur, ama yeni sürümün çalışması için **açık UYAP/UETS sekmelerini yenilemek (F5)** gerekir.

## Testler

`node --test tests/*.js` (CI'da çalışır). Bu testler yukarıdaki davranışı sınar; kapsam değişince testler de değişmelidir.
