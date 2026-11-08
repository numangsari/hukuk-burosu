# Muhasebe

Vekalet ücreti, masraf, müvekkilden tahsilat, karşı taraftan tahsilat ve müvekkile ödeme kayıtlarıyla cari hesap tutulur.

- Hareket [[Müvekkiller|müvekkile]], gerektiğinde [[Dosyalar ve Safahat|dosyaya]] bağlanır.
- [[Görevler ve Onay]] ve dosya kapanışı hesap kaydı doğurabilir.
- [[UYAP ve UETS Aktarımı]] kaynaklı hareketler ayrı gösterilir; yetkili kişi gerekçeyle hesap dışında bırakabilir.
- Büro hareketleri silinmek yerine iptal edilir.
- Bakiyeleri görme ve değiştirme izinleri [[Kullanıcılar ve Yetkiler]] ile belirlenir.
- Ekstre ve hesap özetleri [[Arama ve Raporlar]] bölümünden alınır.

## Kaynaklar

- `apps/accounting/models.py`
- `apps/accounting/services.py`
- `apps/accounting/permissions.py`
