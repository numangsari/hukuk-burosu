import datetime as dt

import pytest
import pyzipper
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.backups import services
from apps.backups.models import BackupRecord
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "test-yedek-parolasi"  # yalnızca test


@pytest.fixture
def backup_env(tmp_path, settings, monkeypatch):
    settings.MEDIA_ROOT = tmp_path / "media"
    (tmp_path / "media" / "cases" / "1").mkdir(parents=True)
    (tmp_path / "media" / "cases" / "1" / "dilekce.pdf").write_bytes(b"%PDF belge")
    monkeypatch.setenv("BACKUP_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "yedekler"))
    monkeypatch.setattr(
        services, "dump_database", lambda target: target.write_bytes(b"PGDMP sahte dokum")
    )
    return tmp_path


def test_backup_creates_encrypted_zip_and_copy(backup_env):
    office = OfficeSettings.load()
    office.backup_dir = str(backup_env / "Drive")
    office.save()
    rec = services.run_backup(BackupRecord.Kind.MANUAL)
    assert rec.status == "ok", rec.message
    path = backup_env / "yedekler" / rec.file_name
    assert (backup_env / "Drive" / rec.file_name).exists()
    with pyzipper.AESZipFile(path) as zf:
        with pytest.raises(RuntimeError):
            zf.read("db.dump")  # parolasız açılamaz
        zf.setpassword(TEST_PASSWORD.encode())
        assert zf.read("db.dump") == b"PGDMP sahte dokum"
        assert zf.read("media/cases/1/dilekce.pdf") == b"%PDF belge"


def test_backup_without_password_fails(backup_env, monkeypatch):
    monkeypatch.delenv("BACKUP_PASSWORD")
    rec = services.run_backup()
    assert rec.status == "error" and "BACKUP_PASSWORD" in rec.message


def test_retention_keeps_30_daily_and_12_monthly(tmp_path):
    today = dt.date(2026, 11, 1)
    for i in range(400):
        d = today - dt.timedelta(days=i)
        for hour in ("120000", "180000"):  # günde iki yedek
            (tmp_path / f"ozkurt-yedek-{d:%Y%m%d}-{hour}.zip").write_bytes(b"x")
    (tmp_path / "baska-dosya.txt").write_text("dokunma")
    services.apply_retention(tmp_path, today)
    names = sorted(p.name for p in tmp_path.glob("ozkurt-yedek-*.zip"))
    days = {n[13:21] for n in names}
    assert all(f"{today - dt.timedelta(days=i):%Y%m%d}" in days for i in range(30))
    # Günün en son yedeği (günlük) tutulur; ayın 1'i olduğu için ayın ilk yedeği (aylık) de kalır.
    assert f"ozkurt-yedek-{today:%Y%m%d}-180000.zip" in names
    yesterday = today - dt.timedelta(days=1)
    assert [n for n in names if n[13:21] == f"{yesterday:%Y%m%d}"] == [
        f"ozkurt-yedek-{yesterday:%Y%m%d}-180000.zip"
    ]
    months = {n[13:19] for n in names}
    assert len(months) == 12 and (tmp_path / "baska-dosya.txt").exists()
    assert len(names) <= 30 + 12


def test_scheduled_due(backup_env):
    office = OfficeSettings.load()
    office.backup_time = dt.time(12, 30)
    office.save()
    noon = timezone.localtime().replace(hour=12, minute=0)
    assert not services.scheduled_due(noon)
    later = noon.replace(hour=13)
    assert services.scheduled_due(later)
    services.run_backup()
    assert not services.scheduled_due(later)  # bugün alındı


def test_restore_roundtrip(backup_env, monkeypatch, settings):
    rec = services.run_backup()
    calls = []
    monkeypatch.setattr(
        services, "_run", lambda cmd, stdin=None, **kw: calls.append((cmd, stdin.read()))
    )
    (backup_env / "media" / "cases" / "1" / "dilekce.pdf").write_bytes(b"degisti")
    services.restore(backup_env / "yedekler" / rec.file_name)
    assert "--clean" in calls[0][0] and calls[0][1] == b"PGDMP sahte dokum"
    assert (backup_env / "media" / "cases" / "1" / "dilekce.pdf").read_bytes() == b"%PDF belge"
    assert list(backup_env.glob("media.onceki-*"))  # önceki belgeler saklandı


def test_failed_restore_keeps_previous_media(backup_env, monkeypatch):
    rec = services.run_backup()
    document = backup_env / "media" / "cases" / "1" / "dilekce.pdf"
    document.write_bytes(b"mevcut belge")

    def fail(cmd, **kwargs):
        assert "--single-transaction" in cmd
        assert "--exit-on-error" in cmd
        raise services.BackupError("Örnek veritabanı hatası")

    monkeypatch.setattr(services, "_run", fail)
    with pytest.raises(services.BackupError, match="Örnek veritabanı hatası"):
        services.restore(backup_env / "yedekler" / rec.file_name)
    assert document.read_bytes() == b"mevcut belge"


def test_media_copy_failure_does_not_start_database_restore(backup_env, monkeypatch):
    rec = services.run_backup()
    document = backup_env / "media" / "cases" / "1" / "dilekce.pdf"
    document.write_bytes(b"mevcut belge")
    calls = []
    monkeypatch.setattr(services, "_run", lambda *args, **kwargs: calls.append(args))

    def fail(*args, **kwargs):
        raise OSError("Örnek disk hatası")

    monkeypatch.setattr(services.shutil, "copytree", fail)
    with pytest.raises(services.BackupError):
        services.restore(backup_env / "yedekler" / rec.file_name)
    assert not calls
    assert document.read_bytes() == b"mevcut belge"


def test_restore_without_media_replaces_current_documents(backup_env, monkeypatch):
    archive = backup_env / "bos-belgeli-yedek.zip"
    with pyzipper.AESZipFile(archive, "w", encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(TEST_PASSWORD.encode())
        zf.writestr("db.dump", b"PGDMP ornek")
    monkeypatch.setattr(services, "_run", lambda *args, **kwargs: None)
    services.restore(archive)
    assert list((backup_env / "media").iterdir()) == []
    previous = list(backup_env.glob("media.onceki-*"))
    assert len(previous) == 1
    assert (previous[0] / "cases" / "1" / "dilekce.pdf").read_bytes() == b"%PDF belge"


def test_corrupt_archive_does_not_touch_media(backup_env, monkeypatch):
    archive = backup_env / "bozuk.zip"
    archive.write_bytes(b"arsiv degil")
    calls = []
    monkeypatch.setattr(services, "_run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(services.BackupError, match="Yedek açılamadı"):
        services.restore(archive)
    assert not calls
    assert (backup_env / "media" / "cases" / "1" / "dilekce.pdf").read_bytes() == b"%PDF belge"


def test_media_swap_failure_restores_previous_folder(backup_env, monkeypatch):
    from pathlib import Path

    rec = services.run_backup()
    document = backup_env / "media" / "cases" / "1" / "dilekce.pdf"
    document.write_bytes(b"mevcut belge")
    rename = Path.rename
    calls = []
    monkeypatch.setattr(services, "_run", lambda *args, **kwargs: calls.append(args))

    def fail_staged_swap(source, target):
        if source.parent.name.startswith(".geri-yukleme-"):
            raise OSError("Örnek klasör değiştirme hatası")
        return rename(source, target)

    monkeypatch.setattr(Path, "rename", fail_staged_swap)
    with pytest.raises(services.BackupError):
        services.restore(backup_env / "yedekler" / rec.file_name)
    assert not calls
    assert document.read_bytes() == b"mevcut belge"


def test_backup_now_view_admin_only(backup_env, admin_user, lawyer):
    c = HttpClient()
    c.force_login(lawyer)
    assert c.post(reverse("backups:now")).status_code == 403
    c.force_login(admin_user)
    c.post(reverse("backups:now"))
    assert BackupRecord.objects.filter(status="ok").count() == 1


def test_stale_backup_banner_for_admin(admin_user, lawyer):
    c = HttpClient()
    c.force_login(admin_user)
    assert "başarılı yedek alınmadı" in c.get(reverse("core:home")).content.decode()
    c.force_login(lawyer)
    assert "başarılı yedek alınmadı" not in c.get(reverse("core:home")).content.decode()


def test_user_admin_create_and_self_protection(admin_user):
    from apps.accounts.models import User

    c = HttpClient()
    c.force_login(admin_user)
    url = reverse("accounts:settings")
    r = c.post(url, {"section": "kullanicilar", "first_name": "Deneme", "last_name": "YENİ", "role": "lawyer",
                     "title": "Avukat", "order": 9, "is_active": "on", "pin": "1234"})  # fmt: skip
    assert r.status_code == 302
    u = User.objects.get(username="deneme.yeni")
    assert u.check_password("1234") and not u.is_staff
    r = c.post(url, {"section": "kullanicilar", "user_id": admin_user.pk, "first_name": "Y", "last_name": "Z",
                     "role": "lawyer", "order": 0})  # fmt: skip
    errors = r.context["forms"]["kullanicilar"].errors
    assert "is_active" in errors and "role" in errors
