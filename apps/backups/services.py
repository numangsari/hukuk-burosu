"""Günlük yedek ve geri yükleme.

Yedek = PostgreSQL dökümü (pg_dump -Fc) + yüklenen belgeler (MEDIA_ROOT), tek bir
AES-256 şifreli ZIP içinde. Önce sunucudaki BACKUP_DIR'e yazılır, ardından Ayarlar'daki
yedek kopyası klasörüne (ör. Google Drive senkron klasörü) kopyalanır.
Saklama: son 30 günün günlük yedeği + son 12 ayın ilk yedeği; diğerleri silinir.

Env değişkenleri: BACKUP_PASSWORD (zorunlu), BACKUP_DIR, PG_DUMP, PG_RESTORE,
BACKUP_DATABASE_URL (pg_dump'ın bağlanacağı adres; boşsa DATABASE_URL).
"""

import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import pyzipper
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.office.models import OfficeSettings

from .models import BackupRecord

NAME_RE = re.compile(r"^ozkurt-yedek-(\d{8})-(\d{6})\.zip$")
KEEP_DAILY = 30
KEEP_MONTHLY = 12


class BackupError(Exception):
    pass


def _cfg(name, default=""):
    return os.environ.get(name) or getattr(settings, name, default) or default


def local_dir() -> Path:
    return Path(_cfg("BACKUP_DIR", str(settings.BASE_DIR / "backups")))


def _db_url() -> str:
    url = _cfg("BACKUP_DATABASE_URL")
    if url:
        return url
    db = connection.settings_dict
    return (
        f"postgresql://{db['USER']}:{db['PASSWORD']}@"
        f"{db['HOST'] or 'localhost'}:{db['PORT'] or 5432}/{db['NAME']}"
    )


def backup_ready() -> str:
    """Yedek alınmasını engelleyen bir ayar eksikliği varsa açıklaması."""
    if not _cfg("BACKUP_PASSWORD"):
        return (
            "BACKUP_PASSWORD ayarlanmamış; yedekler şifrelenemez. "
            "Kurulum bu değeri otomatik oluşturur."
        )
    return ""


def _run(cmd: list[str], *, stdin=None, stdout=None, timeout=900):
    try:
        res = subprocess.run(
            cmd, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, timeout=timeout, check=False
        )
    except FileNotFoundError as e:
        raise BackupError(f"Program bulunamadı: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise BackupError("Veritabanı işlemi zaman aşımına uğradı.") from e
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise BackupError(f"{Path(cmd[0]).name} hata verdi: {err}")


def dump_database(target: Path):
    cmd = [
        *shlex.split(_cfg("PG_DUMP", "pg_dump"), posix=False),
        "--format=custom",
        "--no-owner",
        f"--dbname={_db_url()}",
    ]
    with open(target, "wb") as out:
        _run(cmd, stdout=out)
    if target.stat().st_size == 0:
        raise BackupError("Veritabanı dökümü boş.")


def _add_media(zf, media_root: Path) -> int:
    count = 0
    if media_root.is_dir():
        for path in media_root.rglob("*"):
            if path.is_file():
                zf.write(path, f"media/{path.relative_to(media_root).as_posix()}")
                count += 1
    return count


def apply_retention(directory: Path, today: dt.date | None = None) -> list[str]:
    """Saklama kuralı dışında kalan yedekleri siler; silinen dosya adlarını döner."""
    if not directory.is_dir():
        return []
    today = today or timezone.localdate()
    backups = []
    for p in directory.iterdir():
        m = NAME_RE.match(p.name)
        if m:
            backups.append((dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"), p))
    backups.sort(reverse=True)
    keep = set()
    days_seen, months_seen = set(), {}
    for stamp, p in backups:
        d = stamp.date()
        if (today - d).days < KEEP_DAILY and d not in days_seen:
            days_seen.add(d)
            keep.add(p)
        ym = (d.year, d.month)
        months_ago = (today.year - d.year) * 12 + today.month - d.month
        if months_ago < KEEP_MONTHLY:
            months_seen[ym] = p  # ters sırada gezildiği için ayın en eski yedeği kalır
    keep.update(months_seen.values())
    removed = []
    for _, p in backups:
        if p not in keep:
            p.unlink(missing_ok=True)
            removed.append(p.name)
    return removed


def run_backup(kind=BackupRecord.Kind.SCHEDULED) -> BackupRecord:
    rec = BackupRecord.objects.create(kind=kind)
    try:
        if problem := backup_ready():
            raise BackupError(problem)
        password = _cfg("BACKUP_PASSWORD").encode()
        out_dir = local_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        now = timezone.localtime()
        name = f"ozkurt-yedek-{now:%Y%m%d-%H%M%S}.zip"
        target = out_dir / name
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "db.dump"
            dump_database(dump)
            with pyzipper.AESZipFile(
                target, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
            ) as zf:
                zf.setpassword(password)
                zf.write(dump, "db.dump")
                files = _add_media(zf, Path(settings.MEDIA_ROOT))
                zf.writestr(
                    "manifest.json",
                    json.dumps(
                        {"created": now.isoformat(), "media_files": files, "format": 1},
                        ensure_ascii=False,
                    ),
                )
        rec.file_name, rec.size = name, target.stat().st_size
        notes = []
        copy_dir = (OfficeSettings.load().backup_dir or "").strip()
        if copy_dir:
            try:
                Path(copy_dir).mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, Path(copy_dir) / name)
                rec.copied_to = copy_dir
                apply_retention(Path(copy_dir))
            except OSError as e:
                notes.append(f"Kopya klasörüne yazılamadı: {e.strerror or e}")
        removed = apply_retention(out_dir)
        if removed:
            notes.append(f"Saklama kuralıyla {len(removed)} eski yedek silindi.")
        rec.status = BackupRecord.Status.OK
        rec.message = " ".join(notes)
    except (BackupError, OSError) as e:
        rec.status = BackupRecord.Status.ERROR
        rec.message = str(e)
    rec.finished_at = timezone.now()
    rec.save()
    return rec


def scheduled_due(now=None) -> bool:
    """Bugün başarılı yedek yoksa ve ayarlanan saat geçtiyse yedek zamanı gelmiştir."""
    now = now or timezone.localtime()
    if now.time() < OfficeSettings.load().backup_time:
        return False
    return not BackupRecord.objects.filter(
        status=BackupRecord.Status.OK, started_at__date=now.date()
    ).exists()


def last_success():
    return BackupRecord.objects.filter(status=BackupRecord.Status.OK).first()


def backup_stale(days=2) -> bool:
    last = last_success()
    return last is None or (timezone.now() - last.started_at).days >= days


def restore(zip_path: Path, password: str | None = None):
    """Yedeği geri yükler. Uygulama servisi durdurulmuşken çalıştırılmalıdır."""
    password = (password or _cfg("BACKUP_PASSWORD")).encode()
    media_root = Path(settings.MEDIA_ROOT)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        try:
            with pyzipper.AESZipFile(zip_path) as zf:
                zf.setpassword(password)
                zf.extractall(tmp)
        except (RuntimeError, pyzipper.BadZipFile, OSError) as e:
            raise BackupError("Yedek açılamadı: parola yanlış veya dosya bozuk.") from e
        if not (tmp / "db.dump").is_file():
            raise BackupError("Yedek içinde veritabanı dökümü yok.")
        cmd = [
            *shlex.split(_cfg("PG_RESTORE", "pg_restore"), posix=False),
            "--clean",
            "--if-exists",
            "--no-owner",
            "--single-transaction",
            "--exit-on-error",
            f"--dbname={_db_url()}",
        ]
        try:
            media_root.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".geri-yukleme-", dir=media_root.parent
            ) as staging:
                staged_media = Path(staging) / "media"
                if (tmp / "media").is_dir():
                    shutil.copytree(tmp / "media", staged_media)
                else:
                    staged_media.mkdir()
                previous = None
                if media_root.exists():
                    previous = media_root.with_name(
                        f"{media_root.name}.onceki-{timezone.localtime():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
                    )
                    media_root.rename(previous)
                try:
                    staged_media.rename(media_root)
                    with open(tmp / "db.dump", "rb") as f:
                        _run(cmd, stdin=f, timeout=1800)
                except (BackupError, OSError):
                    # Veritabanı işlemi bütünüyle geri alınır; eski belgeleri de yerine koy.
                    if media_root.exists():
                        media_root.rename(staged_media)
                    if previous is not None:
                        previous.rename(media_root)
                    raise
        except OSError as e:
            raise BackupError(
                "Belge klasörü hazırlanamadı veya geri alınamadı. Uygulamayı kapalı tutun."
            ) from e
