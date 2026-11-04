"""Günlük yedek ve geri yükleme.

Günlük yedek veritabanı dökümünü arşive alır, sistem belgelerini ofis klasörüne ayrı kopyalar.
Elle alınan yedekler belgeleri de arşive ekler. Arşivler parolasızdır.
Saklama: son 30 günün günlük yedeği + son 12 ayın ilk yedeği; diğerleri silinir.

Env değişkenleri: BACKUP_PASSWORD (eski yedekler için), BACKUP_DIR,
PG_DUMP, PG_RESTORE, BACKUP_DATABASE_URL (pg_dump'ın bağlanacağı adres; boşsa DATABASE_URL).
"""

import datetime as dt
import filecmp
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pyzipper
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.office.models import OfficeSettings

from .models import BackupRecord

NAME_RE = re.compile(r"^[a-z0-9-]+-yedek-(\d{8})-(\d{6})\.zip$")
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
    """Yedekleme için parola gerekmez."""
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


def _development_database_tool(tool: str) -> list[str] | None:
    """Bu bilgisayardaki geliştirme veritabanına kendi kabından erişir."""
    db = connection.settings_dict
    dev_container = os.environ.get("DEV_DB_CONTAINER")
    if not dev_container:
        dev_container = "ozkurt-hukuk-db-1"
        if shutil.which("docker"):
            with suppress(Exception):
                out = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                ).stdout
                if "hukuk-burosu-db-1" in out and "ozkurt-hukuk-db-1" not in out:
                    dev_container = "hukuk-burosu-db-1"
    configured = _cfg("PG_DUMP" if tool == "pg_dump" else "PG_RESTORE")
    if (
        not settings.DEBUG
        or configured
        or _cfg("BACKUP_DATABASE_URL")
        or shutil.which(tool)
        or db["NAME"] not in ("ozkurt", "hukuk")
        or db["USER"] not in ("ozkurt", "hukuk")
        or db["HOST"] not in ("localhost", "127.0.0.1")
        or str(db["PORT"]) != "5434"
    ):
        return None
    return ["docker", "exec", "-i", dev_container, tool]


def dump_database(target: Path):
    fallback = _development_database_tool("pg_dump")
    cmd = [
        *(fallback or shlex.split(_cfg("PG_DUMP", "pg_dump"), posix=False)),
        "--format=custom",
        "--no-owner",
        *(["--username=ozkurt", "--dbname=ozkurt"] if fallback else [f"--dbname={_db_url()}"]),
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


def _copy_media_to_office(media_root: Path, office_root: Path) -> int:
    """Sistem belgelerini değiştirmeden ofis klasöründe ayrı bir kopyada korur."""
    destination = office_root / "Sistem Belgeleri"
    if destination.is_symlink() or media_root.is_symlink():
        raise BackupError("Belge yedeğinde klasör bağlantısı kullanılamaz.")
    source_resolved, target_resolved = media_root.resolve(), destination.resolve()
    if source_resolved == target_resolved or target_resolved.is_relative_to(source_resolved):
        raise BackupError("Belge yedeği kaynak klasörün içinde olamaz.")
    destination.mkdir(parents=True, exist_ok=True)
    if not media_root.exists():
        return 0
    count = 0
    for source in media_root.rglob("*"):
        if source.is_symlink():
            raise BackupError("Sistem belgelerinde klasör veya dosya bağlantısı var.")
        if not source.is_file():
            continue
        target = destination / source.relative_to(media_root)
        for parent in [target, *target.parents]:
            if parent == destination.parent:
                break
            if parent.is_symlink():
                raise BackupError("Belge yedeğinin hedefinde bağlantı var.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or not filecmp.cmp(source, target, shallow=True):
                raise BackupError("Belge yedeğinde farklı içerikli aynı adlı dosya var.")
        else:
            created = False
            try:
                with source.open("rb") as src, target.open("xb") as dst:
                    created = True
                    shutil.copyfileobj(src, dst)
                shutil.copystat(source, target)
            except OSError:
                if created:
                    with suppress(OSError):
                        target.unlink()
                raise
        count += 1
    return count


def _add_office_templates(zf) -> int:
    from apps.office.models import TaskType

    root = (OfficeSettings.load().documents_root or "").strip()
    directory = Path(root) / "Şablon Dilekçeler" if root else None
    if not directory or not directory.is_dir():
        if TaskType.objects.exclude(petition_template="").exists():
            raise BackupError("Dilekçe şablonlarının bulunduğu ofis klasörü okunamıyor.")
        return 0
    if directory.is_symlink():
        raise BackupError("Şablon klasörü bağlantı olamaz.")
    for stored in TaskType.objects.exclude(petition_template="").values_list(
        "petition_template", flat=True
    ):
        if (
            Path(stored).name != stored
            or not (directory / stored).is_file()
            or (directory / stored).is_symlink()
        ):
            raise BackupError("Kayıtlı bir dilekçe şablonu bulunamadı veya güvenli değil.")
    count = 0
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise BackupError("Şablon klasöründe bağlantı bulunuyor; yedekleme durduruldu.")
        if path.is_file():
            zf.write(path, f"office_templates/{path.relative_to(directory).as_posix()}")
            count += 1
    return count


def _add_office_lists(zf) -> int:
    """Görüntüleme tablolarının o andaki kopyalarını yedeğe ekler."""
    from apps.core.office_lists import DIRECTORY

    root = (OfficeSettings.load().documents_root or "").strip()
    directory = Path(root) / DIRECTORY if root else None
    if not directory or not directory.exists():
        return 0
    if directory.is_symlink() or not directory.is_dir():
        raise BackupError("Liste klasörü güvenli değil.")
    count = 0
    for path in directory.glob("*.xlsx"):
        if path.is_symlink() or not path.is_file():
            raise BackupError("Liste klasöründe güvenli olmayan bir dosya var.")
        zf.write(path, f"office_lists/{path.name}")
        count += 1
    return count


def _restore_office_templates(source: Path) -> list[Path]:
    """Şablonları yalnız eksikse ekler; çakışan dosyaları değiştirmez."""
    if not source.is_dir():
        return []
    root = ""
    with suppress(Exception):
        root = (OfficeSettings.load().documents_root or "").strip()
    if not root or not Path(root).is_dir():
        default_root = Path(r"C:\Users\numan\OneDrive\Masaüstü\Ozkurt Hukuk Test")
        if default_root.is_dir():
            root = str(default_root)
        else:
            raise BackupError("Şablonları geri yüklemek için ofis klasörü erişilebilir olmalı.")
    destination = Path(root) / "Şablon Dilekçeler"
    if destination.is_symlink():
        raise BackupError("Şablon klasörü bağlantı olamaz.")
    entries = [item for item in source.rglob("*") if item.is_file()]
    # Önce bütün hedefleri denetle; kullanıcının dosyası ezilmez.
    for item in entries:
        relative = item.relative_to(source)
        target = destination / relative
        for parent in [target, *target.parents]:
            if parent == destination.parent:
                break
            if parent.is_symlink():
                raise BackupError("Şablon hedefinde bağlantı var; geri yükleme durduruldu.")
        if target.exists() and (
            not target.is_file() or not filecmp.cmp(item, target, shallow=False)
        ):
            raise BackupError(
                "Şablon klasöründe farklı içerikli aynı adlı dosya var; geri yükleme durduruldu."
            )
    created = []
    try:
        for item in entries:
            target = destination / item.relative_to(source)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with item.open("rb") as src, target.open("xb") as dst:
                created.append(target)
                shutil.copyfileobj(src, dst)
    except OSError:
        for path in created:
            with suppress(OSError):
                path.unlink()
        raise
    return created


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


def run_backup(kind=BackupRecord.Kind.MANUAL) -> BackupRecord:
    rec = BackupRecord.objects.create(kind=kind)
    target = None
    archive_created = False
    archive_complete = False
    try:
        if problem := backup_ready():
            raise BackupError(problem)
        out_dir = local_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        now = timezone.localtime()
        office = OfficeSettings.load()
        database_only = kind == BackupRecord.Kind.SCHEDULED
        if database_only:
            if not office.documents_root:
                raise BackupError("Belgeleri korumak için önce ofis klasörünü seçin.")
            _copy_media_to_office(Path(settings.MEDIA_ROOT), Path(office.documents_root))
        name = f"{office.slug}-yedek-{now:%Y%m%d-%H%M%S}.zip"
        target = out_dir / name
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "db.dump"
            dump_database(dump)
            with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as zf:
                archive_created = True
                zf.write(dump, "db.dump")
                files = 0 if database_only else _add_media(zf, Path(settings.MEDIA_ROOT))
                templates = _add_office_templates(zf)
                lists = _add_office_lists(zf)
                zf.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "created": now.isoformat(),
                            "media_files": files,
                            "template_files": templates,
                            "list_files": lists,
                            "format": 1,
                            "database_only": database_only,
                        },
                        ensure_ascii=False,
                    ),
                )
            archive_complete = True
        rec.file_name, rec.size = name, target.stat().st_size
        notes = []
        office_root = (OfficeSettings.load().documents_root or "").strip()
        if office_root:
            copy_dir = Path(office_root) / "Yedekler"
            target_copy = copy_dir / name
            created_copy = False
            try:
                if copy_dir.is_symlink():
                    raise OSError("Yedek klasörü bağlantı olamaz.")
                copy_dir.mkdir(parents=True, exist_ok=True)
                # Var olan bir dosyanın üzerine yazılmaz.
                with target.open("rb") as source, target_copy.open("xb") as destination:
                    created_copy = True
                    shutil.copyfileobj(source, destination)
                rec.copied_to = str(copy_dir)
            except OSError as e:
                if created_copy:
                    with suppress(OSError):
                        target_copy.unlink()
                raise BackupError(f"Yedek ofis klasörüne kopyalanamadı: {e.strerror or e}") from e
        else:
            notes.append("Ofis klasörü seçilmedi; yedek yalnızca sunucuda saklandı.")
        removed = apply_retention(out_dir)
        if removed:
            notes.append(f"Saklama kuralıyla {len(removed)} eski yedek silindi.")
        rec.status = BackupRecord.Status.OK
        rec.message = " ".join(notes)
    except (BackupError, OSError) as e:
        if archive_created and not archive_complete and target is not None:
            with suppress(OSError):
                target.unlink()
        rec.status = BackupRecord.Status.ERROR
        rec.message = str(e)
    rec.finished_at = timezone.now()
    rec.save()
    return rec


def scheduled_due(now=None) -> bool:
    """Günlük veya önceki günden kaçırılmış yedek zamanını denetler."""
    now = now or timezone.localtime()
    successful = BackupRecord.objects.filter(status=BackupRecord.Status.OK)
    if successful.filter(started_at__date=now.date()).exists():
        return False
    due_time = OfficeSettings.load().backup_time
    if now.time() >= due_time:
        return True
    last = successful.first()
    if last is None:
        return False
    yesterday_due = now.replace(
        hour=due_time.hour, minute=due_time.minute, second=due_time.second, microsecond=0
    ) - dt.timedelta(days=1)
    return last.started_at < yesterday_due


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
                if password:
                    zf.setpassword(password)
                zf.extractall(tmp)
        except (RuntimeError, pyzipper.BadZipFile, OSError) as e:
            raise BackupError("Yedek açılamadı: parola yanlış veya dosya bozuk.") from e
        if not (tmp / "db.dump").is_file():
            raise BackupError("Yedek içinde veritabanı dökümü yok.")
        database_only = False
        if (tmp / "manifest.json").is_file():
            try:
                database_only = (
                    json.loads((tmp / "manifest.json").read_text("utf-8")).get(
                        "database_only", False
                    )
                    is True
                )
            except (ValueError, OSError, AttributeError) as e:
                raise BackupError("Yedek bilgileri okunamadı.") from e
        fallback = _development_database_tool("pg_restore")
        cmd = [
            *(fallback or shlex.split(_cfg("PG_RESTORE", "pg_restore"), posix=False)),
            "--clean",
            "--if-exists",
            "--no-owner",
            "--single-transaction",
            "--exit-on-error",
            *(["--username=ozkurt", "--dbname=ozkurt"] if fallback else [f"--dbname={_db_url()}"]),
        ]
        try:
            if database_only:
                with open(tmp / "db.dump", "rb") as f:
                    _run(cmd, stdin=f, timeout=1800)
                return
            media_root.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".geri-yukleme-", dir=media_root.parent
            ) as staging:
                staged_media = Path(staging) / "media"
                if (tmp / "media").is_dir():
                    shutil.copytree(tmp / "media", staged_media)
                else:
                    staged_media.mkdir()
                created_templates = []
                previous = None
                media_replaced = False
                try:
                    created_templates = _restore_office_templates(tmp / "office_templates")
                    if media_root.exists():
                        previous = media_root.with_name(
                            f"{media_root.name}.onceki-{timezone.localtime():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
                        )
                        media_root.rename(previous)
                    staged_media.rename(media_root)
                    media_replaced = True
                    with open(tmp / "db.dump", "rb") as f:
                        _run(cmd, stdin=f, timeout=1800)
                except (BackupError, OSError):
                    # Veritabanı işlemi bütünüyle geri alınır; eski belgeleri de yerine koy.
                    if media_replaced:
                        media_root.rename(staged_media)
                    if previous is not None and previous.exists():
                        previous.rename(media_root)
                    for path in created_templates:
                        with suppress(OSError):
                            path.unlink()
                    raise
        except OSError as e:
            raise BackupError(
                "Belge klasörü hazırlanamadı veya geri alınamadı. Uygulamayı kapalı tutun."
            ) from e
