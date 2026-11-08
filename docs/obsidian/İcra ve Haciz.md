# İcra ve Haciz

İcra ekranı, dosya kayıtlarının icra türünde olanlarını gösterir. Haciz türü, borçlu ve yenileme bilgileri dosyaya bağlı tutulur.

- Ana kayıt [[Dosyalar ve Safahat]] içindedir; ayrı bir icra dosyası kaydı oluşturulmaz.
- Yenileme zamanı gelen hacizler [[Görevler ve Onay|görev]] doğurabilir.
- İcra listesinde ilgili [[Tebligatlar]] da izlenir.
- Dosya kapanışında girilen tahsilatlar [[Muhasebe]] bölümüne aktarılabilir.

## Kaynaklar

- `apps/cases/enforcement.py`
- `apps/cases/seizures.py`
- `apps/cases/management/commands/create_seizure_tasks.py`
