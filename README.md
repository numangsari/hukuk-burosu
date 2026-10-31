# Özkurt Hukuk — Büro Yönetim Sistemi

Ofis içi ağda çalışan görev, dosya, müvekkil ve muhasebe takip uygulaması (Django + PostgreSQL).

Geliştirme kurulumu, mimari ve kurallar için: [CLAUDE.md](CLAUDE.md).

Hızlı başlangıç:

```
docker compose -f docker-compose.dev.yml up -d
uv sync
uv run python manage.py migrate
uv run python manage.py seed_dev
uv run python manage.py runserver
```
