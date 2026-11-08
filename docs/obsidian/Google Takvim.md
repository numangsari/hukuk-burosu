# Google Takvim

Bürodaki duruşma ve etkinlikler, ayarlar açılmışsa ofisin Google Takvim hesabına gönderilir. Dış takvim etkinlikleri ayrıca salt okunur gösterilebilir.

- Gönderilen kayıtların sahibi [[Duruşmalar ve Takvim]] bölümüdür.
- Bağlantı ve renk tercihleri [[Büro Ayarları]] içindedir.
- Başarısız aktarım yeniden denemeye bırakılır; duruşma kaydı korunur.
- Harici etkinlikler büro kaydı gibi düzenlenmez; gönderilen etkinlikler ikinci kez gösterilmez.
- Periyodik yeniden deneme [[Kurulum ve Çalışma]] tarafından çalıştırılır.

## Kaynaklar

- `apps/agenda/google_sync.py`
- `apps/agenda/services.py`
- `apps/agenda/management/commands/retry_google_sync.py`
