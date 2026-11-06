"""Geri yükleme komutu: geri yüklemeden önce güvenlik yedeği alınır."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.backups.management.commands import restore as restore_command
from apps.backups.models import BackupRecord

pytestmark = pytest.mark.django_db


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "yedek.zip"
    path.write_bytes(b"zip")
    return path


class FakeRecord:
    def __init__(self, status, message="", file_name="guvenlik.zip"):
        self.status = status
        self.message = message
        self.file_name = file_name


@pytest.fixture
def calls(monkeypatch):
    log = {"backup": 0, "restore": []}

    def fake_restore(path):
        log["restore"].append(path)

    monkeypatch.setattr(restore_command, "restore", fake_restore)
    return log


def test_safety_backup_runs_before_restore(archive, monkeypatch, calls):
    def fake_backup(kind):
        calls["backup"] += 1
        assert kind == BackupRecord.Kind.UPDATE
        return FakeRecord(BackupRecord.Status.OK)

    monkeypatch.setattr(restore_command, "run_backup", fake_backup)
    call_command("restore", str(archive), "--yes")
    assert calls["backup"] == 1
    assert calls["restore"] == [archive]


def test_failed_safety_backup_cancels_restore(archive, monkeypatch, calls):
    monkeypatch.setattr(
        restore_command,
        "run_backup",
        lambda kind: FakeRecord(BackupRecord.Status.ERROR, "disk dolu"),
    )
    with pytest.raises(CommandError, match="geri yükleme iptal edildi"):
        call_command("restore", str(archive), "--yes")
    assert calls["restore"] == []


def test_skip_flag_does_not_take_safety_backup(archive, monkeypatch, calls):
    def fail_if_called(kind):
        raise AssertionError("güvenlik yedeği alınmamalıydı")

    monkeypatch.setattr(restore_command, "run_backup", fail_if_called)
    call_command("restore", str(archive), "--yes", "--skip-safety-backup")
    assert calls["restore"] == [archive]
