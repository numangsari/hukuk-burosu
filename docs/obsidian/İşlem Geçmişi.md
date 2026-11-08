# İşlem Geçmişi

Önemli kayıt değişikliklerinin ve kullanıcı giriş/çıkışlarının izini tutar. Ekrandaki geçmiş, ayrı iş alanlarının yaptığı işlemleri bir araya getirir.

- [[Kullanıcılar ve Yetkiler]] giriş olaylarını sağlar.
- [[Dosyalar ve Safahat]], [[Görevler ve Onay]] ve [[Muhasebe]] işlemlerinin izlenmesini destekler.
- Kaydedilecek alanlar ilgili bölümün kayıt tanımlarıyla belirlenir; gizli giriş bilgileri geçmişe yazılmaz.

## Kaynaklar

- `apps/activity/apps.py`
- `apps/activity/signals.py`
- `apps/activity/views.py`
