# Yapılacaklar

Tarih: 7 Kasım 2026. Önceki üç incelemenin (`docs/inceleme-2026-11.md`, `docs/inceleme-2026-11-07.md`, `docs/masaustu-tasarim-onerileri.md`) birleşiminden, kullanıcının seçtiği maddeler kaldı.

## Kaldığımız yer (7 Kasım 2026)

- Karar: teknik sağlamlık maddeleri (Y12–Y18) yapılacak; güvenlik (HTTPS, PIN, yedek şifreleme vb.), hukuki özellikler (süre hesaplayıcı vb.) ve kalan büyük arayüz işleri (komut paleti, toplu işlem, erişilebilirlik, telefon, sabit tablo başlığı) listeden çıkarıldı. Gerekirse `docs/inceleme-*.md` dosyalarından geri alınır.
- Arayüz tasarımı tamamlandı: sade ve yoğun profesyonel yön, liste yoğunluğu, tek sekme stili, Kaydet üstte, pop-up kuralları, kompakt dosya detayı, sürükle-bırak yükleme (ayrıntı `CLAUDE.md` §3).
- Yerelde çalıştırma: `uv run python -m pytest` (Windows'ta `uv run pytest` trampoline hatası verir), `PYTHONUTF8=1` artık gerekmez.

Durum: `[ ]` açık · `[~]` kısmen · `[x]` bitti. **Karar** = uygulamadan önce kullanıcıdan karar gerekir.

---

## Teknik sağlamlık ve test

| No | İş | Kaynak | Durum | Not |
|---|---|---|---|---|
| Y12 | Google Takvim eşitlemesini istekten ayır (arka plan kuyruğu) | T7 | [~] | Başarısız eşitleme işaretlenip yeniden deneniyor; eşitleme hâlâ istek içinde. Mimari **karar**. |
| Y13 | UYAP/UETS Node testlerindeki 6 başarısızlığı düzelt ve CI'a ekle; desteklenen davranış matrisi (üretimde `DEBUG=False` iken aktarım kapalı) yaz | B19, B20 | [x] | Yapıldı (7 Kasım): 6 başarısız test güncel davranışa göre yeniden yazıldı (kod bilinçli olarak örneklemeden tam taramaya geçmişti), CI'a `node --test` eklendi, davranış matrisi `docs/uyap-uets-davranis.md`. Not: canlı aktarım üretimde (`DEBUG=False`) kapalı; açmak ayrı karar. |
| Y14 | `postinstall.ps1` ve `check-reminders.ps1`'i gerçek kurulumlu Windows makinede dene | T4 | [~] | Sözdizimi ve sahte servisle çalışma doğrulandı; gerçek servis/zamanlanmış görev denenmedi. |
| Y15 | `OfficeSettings.load()` için istek başına önbellek | T10 | [x] | Yapıldı (7 Kasım): istek başına önbellek (`RequestSettingsCacheMiddleware`); her çağrı ayrı kopya alır, `save()` önbelleği geçersiz kılar, istek dışında önbellek yok. |
| Y16 | CI ve geliştirme veritabanı/kullanıcı adı `ozkurt` adlarını yeniden adlandır | T9 | [ ] | Eski kurulumların yükseltilmesi için `Ozkurt*` servis/görev adları kalmalı. |
| Y17 | Performans: aktivite listesinde N+1, raporların tüm satırları belleğe alması | B23 | [x] | Yapıldı (7 Kasım): aktivite listesindeki kayıt bağlantıları tür başına tek sorguyla alınıyor (N+1 giderildi, test var). Raporlarda ölçüldü: sorgu sayısı satırla artmıyor (koruma testi eklendi); tüm satırların bellekte tutulması gerçek hacimde sorun çıkarırsa ayrıca ele alınır. |
| Y18 | Windows'ta `tests/test_audit_template_security.py` cp1254 kodlama hatası (`read_text()` kodlama vermiyor) | yeni | [x] | Yapıldı (7 Kasım): `read_text(encoding="utf-8")`; `PYTHONUTF8` olmadan da geçer. |

## Bitenler (özet)

- Görünürlük açıkları ve uç bazında yetki testleri (T1), PIN deneme yavaşlatma (T2), Türkçe hata sayfaları ve HTMX bildirimi (T5), haciz middleware hatası (T6), dosya imzası denetimi (T8, kısmen).
- Yatay taşma, koyu tema kontrastı, numara alanı, tutar kırılması, menü gölgesi (U1–U5); anında filtre, durum rozetleri, bakiye etiketi, gizlenebilir yedek uyarısı (U8, U9, U14, U15).
- İlk kurulum yarışının pasif hesap kolu (B01), arama sızıntısı (B04), XSS (B05), dış yönlendirme (B16), kısa arama hatası (B17), yedek uyarısı betiği (B21), form ARIA (B22).
- `ALLOWED_HOSTS`: yeni kurulum ve yönetici ekranı (B12, kısmen).
- Arayüz: renk/yazı tipi tasarımı, kompakt liste, normal yazım, tek sekme stili, Kaydet üstte, görev ve tebligat pop-up, dosya detayı kompakt/sabit sekme, kayıtlı liste konumu, sürükle-bırak yükleme (Y24–Y31, Y33).
