import datetime as dt
import json
import zipfile

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


def test_backup_creates_unencrypted_zip_and_copy(backup_env):
    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    rec = services.run_backup(BackupRecord.Kind.MANUAL)
    assert rec.status == "ok", rec.message
    path = backup_env / "yedekler" / rec.file_name
    assert (backup_env / "Ofis" / "Yedekler" / rec.file_name).exists()
    assert rec.copied_to == str(backup_env / "Ofis" / "Yedekler")
    with zipfile.ZipFile(path) as zf:
        assert zf.read("db.dump") == b"PGDMP sahte dokum"
        assert zf.read("media/cases/1/dilekce.pdf") == b"%PDF belge"


def test_scheduled_backup_keeps_documents_separate_and_restore_preserves_them(
    backup_env, monkeypatch
):
    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    rec = services.run_backup(BackupRecord.Kind.SCHEDULED)
    assert rec.status == "ok", rec.message
    document = backup_env / "Ofis" / "Sistem Belgeleri" / "cases" / "1" / "dilekce.pdf"
    assert document.read_bytes() == b"%PDF belge"
    archive = backup_env / "yedekler" / rec.file_name
    with zipfile.ZipFile(archive) as zf:
        assert json.loads(zf.read("manifest.json"))["database_only"] is True
        assert not any(name.startswith("media/") for name in zf.namelist())
    original = backup_env / "media" / "cases" / "1" / "dilekce.pdf"
    original.write_bytes(b"son belge")
    calls = []
    monkeypatch.setattr(services, "_run", lambda cmd, stdin=None, **kw: calls.append(stdin.read()))
    services.restore(archive)
    assert calls == [b"PGDMP sahte dokum"]
    assert original.read_bytes() == b"son belge"


def test_scheduled_backup_refuses_to_overwrite_different_document(backup_env):
    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    target = backup_env / "Ofis" / "Sistem Belgeleri" / "cases" / "1" / "dilekce.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"korunacak")
    rec = services.run_backup(BackupRecord.Kind.SCHEDULED)
    assert rec.status == "error"
    assert "farklı içerikli" in rec.message
    assert target.read_bytes() == b"korunacak"


def test_backup_without_password_succeeds(backup_env, monkeypatch):
    monkeypatch.delenv("BACKUP_PASSWORD")
    rec = services.run_backup()
    assert rec.status == "ok"
    with zipfile.ZipFile(backup_env / "yedekler" / rec.file_name) as archive:
        assert archive.read("db.dump") == b"PGDMP sahte dokum"


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


def test_backup_shows_missing_office_folder(backup_env):
    office = OfficeSettings.load()
    office.documents_root = ""
    office.save()
    record = services.run_backup()
    assert record.status == "ok"
    assert "Ofis klasörü seçilmedi" in record.message
    assert (backup_env / "yedekler" / record.file_name).exists()


def test_office_folder_contains_backup_and_does_not_remove_existing(backup_env):
    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    directory = backup_env / "Ofis" / "Yedekler"
    directory.mkdir(parents=True)
    old = directory / "ozkurt-yedek-20000101-120000.zip"
    old.write_bytes(b"eski yedek")
    record = services.run_backup()
    assert record.status == "ok"
    assert old.read_bytes() == b"eski yedek"
    assert (directory / record.file_name).exists()


def test_settings_unify_folder_and_backup(admin_user):
    client = HttpClient()
    client.force_login(admin_user)
    response = client.get(reverse("accounts:settings") + "?bolum=klasor")
    html = response.content.decode()
    assert "Ofis klasörü" in html
    assert "Günlük yedek saati" in html
    assert "Şimdi yedek al" in html
    assert "OneDrive" in html
    assert "Yedek kopyası klasörü" not in html
    assert client.get(reverse("accounts:settings") + "?bolum=yedek").status_code == 302


def test_backup_copy_failure_reports_error_and_keeps_local_backup(backup_env, monkeypatch):
    from pathlib import Path

    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    original_open = Path.open

    def failing_open(path, mode="r", *args, **kwargs):
        if path.parent.name == "Yedekler" and mode == "xb":
            raise PermissionError("Örnek yazma hatası")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    record = services.run_backup()
    assert record.status == "error"
    assert "ofis klasörüne kopyalanamadı" in record.message
    assert (backup_env / "yedekler" / record.file_name).exists()


def test_development_database_tool_is_limited_to_expected_database(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.delenv("PG_DUMP", raising=False)
    monkeypatch.delenv("BACKUP_DATABASE_URL", raising=False)
    monkeypatch.setattr(services.shutil, "which", lambda name: None)
    from types import SimpleNamespace

    monkeypatch.setattr(
        services,
        "connection",
        SimpleNamespace(
            settings_dict={"NAME": "ozkurt", "USER": "ozkurt", "HOST": "localhost", "PORT": "5434"}
        ),
    )
    assert services._development_database_tool("pg_dump") == [
        "docker",
        "exec",
        "-i",
        "ozkurt-hukuk-db-1",
        "pg_dump",
    ]
    services.connection.settings_dict["NAME"] = "baska"
    assert services._development_database_tool("pg_dump") is None


def test_restore_old_encrypted_backup_with_password(backup_env, monkeypatch):
    archive = backup_env / "eski-yedek.zip"
    with pyzipper.AESZipFile(archive, "w", encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(TEST_PASSWORD.encode())
        zf.writestr("db.dump", b"PGDMP eski")
        zf.writestr("media/cases/ornek.pdf", b"ornek")
    calls = []
    monkeypatch.delenv("BACKUP_PASSWORD")
    monkeypatch.setattr(services, "_run", lambda cmd, stdin=None, **kw: calls.append(stdin.read()))
    services.restore(archive, password=TEST_PASSWORD)
    assert calls == [b"PGDMP eski"]
    assert (backup_env / "media" / "cases" / "ornek.pdf").read_bytes() == b"ornek"


def test_backup_and_restore_include_office_templates(backup_env, monkeypatch):
    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    directory = backup_env / "Ofis" / "Şablon Dilekçeler"
    directory.mkdir(parents=True)
    template = directory / "ornek.udf"
    template.write_bytes(b"uydurma sablon")
    record = services.run_backup()
    assert record.status == "ok", record.message
    archive_path = backup_env / "yedekler" / record.file_name
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("office_templates/ornek.udf") == b"uydurma sablon"
    template.unlink()
    monkeypatch.setattr(services, "_run", lambda *args, **kwargs: None)
    services.restore(archive_path)
    assert template.read_bytes() == b"uydurma sablon"


def test_restore_does_not_overwrite_changed_office_template(backup_env, monkeypatch):
    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    directory = backup_env / "Ofis" / "Şablon Dilekçeler"
    directory.mkdir(parents=True)
    template = directory / "ornek.udf"
    template.write_bytes(b"ilk ornek")
    record = services.run_backup()
    template.write_bytes(b"degisen ornek")
    calls = []
    monkeypatch.setattr(services, "_run", lambda *args, **kwargs: calls.append(True))
    with pytest.raises(services.BackupError, match="aynı adlı dosya"):
        services.restore(backup_env / "yedekler" / record.file_name)
    assert template.read_bytes() == b"degisen ornek"
    assert (backup_env / "media" / "cases" / "1" / "dilekce.pdf").exists()
    assert not calls


def test_backup_rejects_missing_registered_template(backup_env):
    from apps.office.models import TaskType

    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    (backup_env / "Ofis" / "Şablon Dilekçeler").mkdir(parents=True)
    task_type = TaskType.objects.first()
    task_type.petition_template = "olmayan.udf"
    task_type.save(update_fields=["petition_template"])
    record = services.run_backup()
    assert record.status == "error"
    assert "şablonu bulunamadı" in record.message
    assert not list((backup_env / "yedekler").glob("ozkurt-yedek-*.zip"))


def test_failed_database_restore_rolls_back_new_templates(backup_env, monkeypatch):
    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    directory = backup_env / "Ofis" / "Şablon Dilekçeler"
    directory.mkdir(parents=True)
    template = directory / "ornek.udf"
    template.write_bytes(b"uydurma sablon")
    record = services.run_backup()
    template.unlink()
    sample = backup_env / "media" / "cases" / "1" / "dilekce.pdf"
    sample.write_bytes(b"mevcut belge")

    def fail(*args, **kwargs):
        raise services.BackupError("Örnek hata")

    monkeypatch.setattr(services, "_run", fail)
    with pytest.raises(services.BackupError):
        services.restore(backup_env / "yedekler" / record.file_name)
    assert not template.exists()
    assert sample.read_bytes() == b"mevcut belge"


def test_missed_yesterday_backup_runs_after_morning_start(backup_env):
    office = OfficeSettings.load()
    office.backup_time = dt.time(12, 30)
    office.save()
    morning = timezone.localtime().replace(hour=8, minute=0, second=0, microsecond=0)
    record = BackupRecord.objects.create(status=BackupRecord.Status.OK)
    BackupRecord.objects.filter(pk=record.pk).update(
        started_at=morning - dt.timedelta(days=1, hours=1)
    )
    assert services.scheduled_due(morning)
    BackupRecord.objects.filter(pk=record.pk).update(started_at=morning - dt.timedelta(hours=18))
    assert not services.scheduled_due(morning)
    BackupRecord.objects.filter(pk=record.pk).update(started_at=morning - dt.timedelta(minutes=30))
    assert not services.scheduled_due(morning)


def test_backup_uses_dynamic_office_slug(backup_env):
    office = OfficeSettings.load()
    office.name = "Demir & Ortakları Hukuk Bürosu"
    office.save()
    rec = services.run_backup(BackupRecord.Kind.MANUAL)
    assert rec.status == "ok"
    assert rec.file_name.startswith("demir-ortaklari-yedek-")
    assert (backup_env / "yedekler" / rec.file_name).exists()


def test_backup_contains_readable_list_snapshot(backup_env):
    office = OfficeSettings.load()
    office.documents_root = str(backup_env / "Ofis")
    office.save()
    lists = backup_env / "Ofis" / "Güncel Sistem Listeleri"
    lists.mkdir(parents=True)
    (lists / "Örnek.xlsx").write_bytes(b"uydurma liste")
    record = services.run_backup()
    assert record.status == "ok"
    with zipfile.ZipFile(backup_env / "yedekler" / record.file_name) as archive:
        assert archive.read("office_lists/Örnek.xlsx") == b"uydurma liste"
