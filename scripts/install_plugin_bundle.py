#!/usr/bin/env python3
"""Install a .mspkg bundle's profile layer into a profile document."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.infrastructure.plugins.bundle import (  # noqa: E402
    BundleError,
    install_bundle_into_profile,
    read_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="path to the .mspkg bundle")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("config/plugin-profiles/memstack-default.yaml"),
        help="profile document to extend (default: %(default)s)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing layer with the same id",
    )
    args = parser.parse_args(argv)

    try:
        bundle = read_bundle(args.bundle)
        payload = install_bundle_into_profile(args.profile, bundle, replace=args.replace)
    except BundleError as exc:
        print(f"install-bundle: {exc}", file=sys.stderr)
        return 1

    layer_ids = [layer.get("id") for layer in payload["profile"]["layers"]]
    print(
        f"installed bundle {bundle.bundle_id} {bundle.version} into {args.profile}; "
        f"layers: {layer_ids}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
