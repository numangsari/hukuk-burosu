"""installer/scripts/updater.ps1: indirme ve doğrulama adımları (ağ ve servisler taklit edilir).

Kurulum, servis durdurma ve geri dönüş adımları gerçek Windows servisleri gerektirdiğinden burada
yalnızca güvenli erken çıkışları sınanır; tam akış installer/README.md'deki elle denemededir.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="PowerShell betiği yalnızca Windows'ta.")

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "installer/scripts/updater.ps1"
EXE_BYTES = b"sahte kurulum paketi"


def quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def make_install(tmp_path, version="1.2.0"):
    (tmp_path / "app").mkdir()
    (tmp_path / "app/VERSION").write_text(version, encoding="utf-8")
    return tmp_path


def run_updater(install, mode, tag="v1.3.0", sha=None):
    """Ağ çağrılarını taklit ederek betiği çalıştırır."""
    exe_name = f"HukukBurosuOtomasyonu-Kurulum-{tag.lstrip('v')}.exe"
    sha = sha or hashlib.sha256(EXE_BYTES).hexdigest()
    release = {
        "tag_name": tag,
        "assets": [
            {"name": exe_name, "browser_download_url": "https://ornek.test/exe"},
            {"name": f"{exe_name}.sha256", "browser_download_url": "https://ornek.test/sha"},
        ],
    }
    exe_text = EXE_BYTES.decode()
    mocks = (
        f"function Invoke-RestMethod {{ {quote(json.dumps(release))} | ConvertFrom-Json }}; "
        "function Invoke-WebRequest { param($Uri, $Headers, $OutFile, [switch]$UseBasicParsing, "
        "$TimeoutSec) "
        f"if ($Uri -like '*sha') {{ $t = {quote(sha + '  ' + exe_name)} }} "
        f"else {{ $t = {quote(exe_text)} }}; "
        "[IO.File]::WriteAllText($OutFile, $t) }; "
    )
    script = (
        mocks + f"& {quote(UPDATER)} -Mode {mode} -InstallDir {quote(install)} "
        f"-DataDir {quote(install / 'data')} -Relaunched; "
        "exit $LASTEXITCODE"
    )
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=60,
        check=False,
    )


def updates(install) -> Path:
    return install / "data/updates"


def test_check_downloads_and_verifies_newer_version(tmp_path):
    install = make_install(tmp_path)
    result = run_updater(install, "Check")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    pending = json.loads((updates(install) / "pending.json").read_text(encoding="utf-8"))
    assert pending["version"] == "1.3.0"
    assert Path(pending["file"]).read_bytes() == EXE_BYTES
    status = json.loads((updates(install) / "status.json").read_text(encoding="utf-8"))
    assert status["result"] == "downloaded" and status["from_version"] == "1.2.0"


def test_check_skips_same_or_older_version(tmp_path):
    install = make_install(tmp_path, "1.3.0")
    assert run_updater(install, "Check").returncode == 0
    assert not (updates(install) / "pending.json").exists()


def test_check_skips_version_marked_bad(tmp_path):
    install = make_install(tmp_path)
    updates(install).mkdir(parents=True)
    (updates(install) / "bad-versions.txt").write_text("1.3.0\n", encoding="ascii")
    assert run_updater(install, "Check").returncode == 0
    assert not (updates(install) / "pending.json").exists()


def test_check_rejects_hash_mismatch(tmp_path):
    install = make_install(tmp_path)
    result = run_updater(install, "Check", sha="0" * 64)
    assert result.returncode == 1
    assert not (updates(install) / "pending.json").exists()
    assert not list((updates(install) / "indirilen").glob("*.exe*"))
    assert "SHA256" in (install / "logs/guncelleme.log").read_text(encoding="utf-8-sig")


def test_apply_without_pending_does_nothing(tmp_path):
    install = make_install(tmp_path)
    assert run_updater(install, "Apply").returncode == 0
    assert not (updates(install) / "status.json").exists()


def test_apply_discards_pending_that_is_not_newer(tmp_path):
    install = make_install(tmp_path, "1.3.0")
    (updates(install) / "indirilen").mkdir(parents=True)
    exe = updates(install) / "indirilen" / "eski.exe"
    exe.write_bytes(EXE_BYTES)
    pending = {
        "version": "1.3.0",
        "file": str(exe),
        "sha256": hashlib.sha256(EXE_BYTES).hexdigest(),
    }
    (updates(install) / "pending.json").write_text(json.dumps(pending), encoding="utf-8")
    assert run_updater(install, "Apply").returncode == 0
    assert not (updates(install) / "pending.json").exists() and not exe.exists()


def test_all_installer_scripts_parse():
    scripts = sorted((ROOT / "installer").rglob("*.ps1"))
    scripts = [s for s in scripts if "build" not in s.parent.parts and "cache" not in s.parts]
    assert any(s.name == "updater.ps1" for s in scripts)
    files = ", ".join(quote(s) for s in scripts)
    check = (
        f"$bad = @(); foreach ($f in @({files})) {{ $e = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$null, [ref]$e); "
        'if ($e) { $bad += "${f}: $($e[0].Message)" } }; $bad; exit $bad.Count'
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", check],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout.decode(errors="replace")


def test_apply_refuses_package_outside_download_dir(tmp_path):
    install = make_install(tmp_path, "1.2.0")
    updates(install).mkdir(parents=True)
    outside = tmp_path / "baska-yer.exe"
    outside.write_bytes(EXE_BYTES)
    pending = {
        "version": "1.3.0",
        "file": str(outside),
        "sha256": hashlib.sha256(EXE_BYTES).hexdigest(),
    }
    (updates(install) / "pending.json").write_text(json.dumps(pending), encoding="utf-8")
    assert run_updater(install, "Apply").returncode == 0
    assert not (updates(install) / "pending.json").exists()
    assert not (updates(install) / "status.json").exists()  # kurulum hiç başlamadı
    assert outside.exists()  # klasör dışındaki dosya silinmez


def test_finds_install_and_data_dirs_when_run_as_file(tmp_path):
    """Zamanlanmış görev betiği -File ile ve -InstallDir vermeden çalıştırır.

    PowerShell 5.1'de öznitelikli parametresi olan betikte $PSScriptRoot param varsayılanında boş
    gelir; kurulum klasörü gövdede bulunmalı, veri kökü .env'deki DATA_DIR'dan okunmalı.
    """
    install = tmp_path / "Program Files" / "HukukBurosu"
    (install / "tools").mkdir(parents=True)
    (install / "app").mkdir()
    (install / "app/VERSION").write_text("1.2.0", encoding="utf-8")
    data = tmp_path / "veri"
    (install / "app/.env").write_text(f"DATA_DIR={data}\n", encoding="utf-8")
    (install / "tools/updater.ps1").write_bytes(UPDATER.read_bytes())
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(install / "tools/updater.ps1"),
            "-Mode",
            "Check",
            "-ApiBase",
            "http://127.0.0.1:9",
            "-Relaunched",
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1  # ağ yok: hata günlüğe yazılıp çıkılır
    log = (data / "logs/guncelleme.log").read_text(encoding="utf-8-sig")
    assert "[Check] HATA" in log
