import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows yardımcı dosyası yalnızca Windows'ta çalışır.")
@pytest.mark.parametrize(
    "status, result", [("Stopped", 0), ("Missing", 0), ("Running", 0), ("Running", 7)]
)
def test_seizure_runner_checks_service_and_command_result(tmp_path, status, result):
    command = tmp_path / "manage.cmd"
    command.write_text(
        '@echo off\n>> "%~dp0called.txt" echo %*\n' + f"exit /b {result}\n", encoding="ascii"
    )
    runner = Path(__file__).resolve().parents[1] / "installer/scripts/check-reminders.ps1"

    def quote(path):
        return "'" + str(path).replace("'", "''") + "'"

    service = "$null" if status == "Missing" else f"[pscustomobject]@{{ Status = '{status}' }}"
    script = (
        f"function Get-Service {{ {service} }}; & {quote(runner)} -ToolsDir {quote(tmp_path)}; "
        "exit $LASTEXITCODE"
    )
    response = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert response.returncode == result, response.stderr.decode(errors="replace")
    marker = tmp_path / "called.txt"
    assert marker.exists() == (status == "Running")
    if marker.exists():
        assert marker.read_text().splitlines() == [
            "create_seizure_tasks",
            "create_routine_tasks",
            "retry_google_sync",
        ]
