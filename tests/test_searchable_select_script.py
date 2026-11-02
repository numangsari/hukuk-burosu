import shutil
import subprocess
from pathlib import Path

import pytest


def test_searchable_select_script():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js kurulu değil")
    subprocess.run(
        [node, "--test", str(Path(__file__).parent / "js" / "searchable_select.test.cjs")],
        check=True,
        capture_output=True,
        text=True,
    )
