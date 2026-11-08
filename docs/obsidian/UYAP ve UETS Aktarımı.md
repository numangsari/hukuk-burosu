# UYAP ve UETS Aktarımı

Ulusal Yargı Ağı Bilişim Sistemi ile Ulusal Elektronik Tebligat Sistemi bilgileri, ana bilgisayardaki açık oturumlardan yerel uygulamaya alınır.

- [[Tarayıcı Eklentisi]] bilgileri alır; aktarım bölümü eşleştirir ve kaydeder.
- [[Dosyalar ve Safahat]], [[Duruşmalar ve Takvim]], [[Belgeler]] ve [[Muhasebe]] kayıtları güncellenebilir.
- [[Tebligatlar]] işlenmek üzere ayrı listelenir.
- Eşleşmeyen müvekkil dosyanın açılmasını engellemez; [[Müvekkiller|müvekkil]] daha sonra bağlanabilir.
- Aktarım izinleri [[Kullanıcılar ve Yetkiler]] ve bağlantı ayarlarıyla sınırlandırılır.

## Kaynaklar

- `apps/imports/portal_sync.py`
- `apps/imports/portal_ingest.py`
- `apps/imports/portal_case_sync.py`
- `apps/imports/portal_finance.py`
- `docs/uyap-uets-davranis.md`
