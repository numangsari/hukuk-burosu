# Kurulum ve Çalışma

Uygulama bürodaki yerel Windows sunucusunda çalışır; çalışanlar tarayıcıdan erişir. Kurulu kullanımda uygulama ve veritabanı arka planda çalışan iki hizmettir.

- Uygulamanın bölümleri [[Hukuk Büro Yönetimi]] altında toplanır.
- [[Tarayıcı Eklentisi]] sürekli açık ana bilgisayara kurulur.
- Zamanlanmış işler [[Rutin Görevler]], haciz yenileme, [[Google Takvim]] yeniden denemesi ve [[Yedekleme]] akışlarını çalıştırır.
- [[Ortak Altyapı]] yerel ekran dosyalarını sağlar; dış takvim ve portal bağlantıları için ayrıca internet gerekir.

## Kaynaklar

- `installer/README.md`
- `installer/HukukBurosu.iss`
- `installer/scripts/check-reminders.ps1`
- `config/wsgi.py`
- `docker-compose.dev.yml`
