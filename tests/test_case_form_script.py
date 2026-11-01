import shutil
import subprocess
from pathlib import Path

import pytest


def test_case_form_button_behaviour():
    node = shutil.which("node")
    if not node:
        pytest.skip("Taraf düğmesi denemesi için Node.js bulunamadı.")
    result = subprocess.run(
        [node, "--test", str(Path(__file__).parent / "js" / "case_form.test.cjs")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
