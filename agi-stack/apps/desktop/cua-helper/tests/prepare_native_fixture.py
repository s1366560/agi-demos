"""Build a disposable native fixture without launching it or requesting access."""

import json
import os
import tempfile
from pathlib import Path

from fixture_bundle import build_fixture

folder = Path(tempfile.mkdtemp(prefix="memstack-cua-fixture-", dir=os.environ.get("TMPDIR")))
bundle = folder / "ComputerUseFixture.app"

binary = build_fixture(bundle)
print(
    json.dumps(
        {
            "app": "ai.memstack.cua.fixture",
            "bundle": str(bundle),
            "executable": str(binary),
            "icon_file": str(bundle / "Contents/Resources/ComputerUseFixture.icns"),
            "owned_temporary_root": str(folder),
            "layout_file": str(folder / "layout.json"),
        }
    )
)
