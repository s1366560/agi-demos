"""Global collection must not import unverified runtime artifact entrypoints."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_agent_spine_collection_preserves_real_member_generation_initialization() -> None:
    root = Path(__file__).resolve().parents[3]
    # A fresh interpreter reproduces collection before the first real initializer.
    # The member fixture stages the production generation; the spine is collected
    # but deliberately not executed, just as before the original suite failure.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "src/tests/contract/test_member_management_contract.py",
            "src/tests/integration/agent/test_v2_agent_spine.py",
            "-k",
            "test_list_members_response_structure",
            "-q",
            "--tb=short",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
