"""Count installable packages and their contents in a signed deployment selection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.infrastructure.plugins.sdk_path import ensure_plugin_sdk_path
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2

if TYPE_CHECKING:
    from collections.abc import Sequence

ensure_plugin_sdk_path()


def release_counts(archives: Sequence[Path], public_keys: tuple[str, ...]) -> dict[str, int]:
    """Count each installable identity once, including modules/artifacts inside device targets."""
    from memstack_plugin_sdk.contract import PERMISSIONS

    counts = {"business": 0, "adapter": 0, "modules": 0, "artifacts": 0}
    seen: set[str] = set()
    for path in archives:
        outer = parse_bundle_archive_v2(
            path.read_bytes(),
            source=str(path),
            trusted_public_keys=public_keys,
            approved_permissions=PERMISSIONS,
            require_signature=True,
        )
        bundle = outer.manifest
        if bundle.bundle_id in seen:
            raise ValueError(f"multiple releases selected for {bundle.bundle_id}")
        seen.add(bundle.bundle_id)
        assets = {a.path: outer.artifacts[a.artifact_id] for a in bundle.artifacts}
        kind = json.loads(assets.get("release-kind.json", b'{"kind":"business"}'))
        if kind not in ({"kind": "adapter"}, {"kind": "business"}):
            raise ValueError("invalid signed release kind")
        counts[kind["kind"]] += 1
        manifests = [bundle]
        child = assets.get("targets/desktop-sidecar.mspkg")
        if child is not None:
            device = parse_bundle_archive_v2(
                child,
                source=str(path),
                trusted_public_keys=public_keys,
                approved_permissions=PERMISSIONS,
                require_signature=True,
            ).manifest
            if (device.bundle_id, device.version) != (bundle.bundle_id, bundle.version):
                raise ValueError("device target identity mismatch")
            manifests.append(device)
        counts["modules"] += sum(
            len(plugin.modules) for release in manifests for plugin in release.manifests
        )
        counts["artifacts"] += sum(len(release.artifacts) for release in manifests)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", type=Path, nargs="+")
    parser.add_argument("--trusted-key", action="append", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            release_counts(args.archives, tuple(key.read_text() for key in args.trusted_key))
        )
    )


if __name__ == "__main__":
    main()
