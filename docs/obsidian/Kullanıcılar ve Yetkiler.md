# Kullanıcılar ve Yetkiler

Yönetici, kıdemli avukat, avukat, stajyer, icra katibi, sekreter ve muhasebe rollerini; giriş ve kayıt erişimini yönetir.

- Rol ve sorumluluk ilişkileri, [[Büro Ayarları]] içindeki yetki seçimleriyle birlikte değerlendirilir.
- [[Müvekkiller]], [[Dosyalar ve Safahat]], [[Görevler ve Onay]] ve [[Belgeler]] için görünürlük kuralları uygulanır.
- [[Muhasebe]] işlemleri ve bakiye görüntüleme ayrıca izin gerektirir.
- Giriş denemeleri ve önemli değişiklikler [[İşlem Geçmişi]] ile izlenir.

## Kaynaklar

- `apps/accounts/models.py`
- `apps/accounts/throttle.py`
- `apps/accounts/middleware.py`
- `apps/core/permission_registry.py`
- `apps/core/permissions.py`
