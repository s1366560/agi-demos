#!/usr/bin/env python3
"""Generate the deterministic platform plugin parity capability inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests


def build_inventory() -> dict[str, Any]:
    """Return the canonical builtin plugin capability inventory."""
    manifests = default_builtin_manifests()
    capabilities: list[dict[str, Any]] = []
    for plugin_id in sorted(manifests):
        manifest = manifests[plugin_id]
        for capability in sorted(manifest.provides, key=lambda item: (item.kind.value, item.id)):
            capabilities.append(
                {
                    "id": f"platform-plugin-{plugin_id}-{capability.kind.value}-{capability.id}",
                    "kind": "platform_plugin_capability",
                    "plugin_id": plugin_id,
                    "plugin_version": manifest.version,
                    "capability_kind": capability.kind.value,
                    "capability_id": capability.id,
                    "contract": capability.contract,
                    "permissions": sorted(capability.permissions),
                    "surfaces": ["desktop_cloud", "local_online", "local_offline"],
                }
            )
    return {
        "schema_version": "1.0.0",
        "source": "src/infrastructure/plugins/builtin_manifests.py",
        "capabilities": capabilities,
    }


def main() -> None:
    """Write the canonical inventory artifact."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "agi-stack/apps/desktop/contracts/desktop-web-parity/"
            "platform-plugin-capability-inventory.v1.json"
        ),
    )
    args = parser.parse_args()
    payload = build_inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
