# Yedekleme

Veritabanını ve sistem belgelerini yedekler; saklama süresini ve geri yüklemeyi yönetir.

- Günlük yedek veritabanını arşivler; [[Belgeler|sistem belgeleri]] ofis klasörüne ayrı kopyalanır.
- Elle ve güncelleme öncesi yedekler belgeleri de arşive alır.
- Geri yüklemeden önce mevcut verinin güvenlik yedeği alınır.
- Zamanlama [[Kurulum ve Çalışma]] düzeninin parçasıdır.
- Saklama konumları ve belge klasörü [[Büro Ayarları]] ile ilişkilidir.

## Kaynaklar

- `apps/backups/services.py`
- `apps/backups/models.py`
- `apps/backups/management/commands/restore.py`
