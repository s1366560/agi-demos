import subprocess
import sys

import pytest


@pytest.mark.unit
def test_plugin_registry_imports_in_fresh_interpreter() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from src.infrastructure.agent.plugins.registry import AgentPluginRegistry; "
                "print(AgentPluginRegistry.__name__)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "AgentPluginRegistry"
