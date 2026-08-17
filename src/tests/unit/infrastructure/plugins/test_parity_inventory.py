import json
from pathlib import Path

import pytest

from scripts.generate_platform_plugin_parity import build_inventory


@pytest.mark.unit
def test_generated_platform_plugin_inventory_is_current_and_deterministic() -> None:
    artifact = Path(
        "agi-stack/apps/desktop/contracts/desktop-web-parity/"
        "platform-plugin-capability-inventory.v1.json"
    )
    current = json.loads(artifact.read_text(encoding="utf-8"))
    generated = build_inventory()

    assert current == generated
    assert generated == build_inventory()
    assert generated["capabilities"]
    assert all(
        capability["surfaces"] == ["desktop_cloud", "local_online", "local_offline"]
        for capability in generated["capabilities"]
    )
