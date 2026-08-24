import subprocess
import sys

import pytest


@pytest.mark.unit
def test_v1_plugin_registry_is_absent_in_fresh_interpreter() -> None:
    module_name = ".".join(("src", "infrastructure", "agent", "plugins", "registry"))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import importlib; importlib.import_module({module_name!r})",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stderr
