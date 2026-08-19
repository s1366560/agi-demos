#!/usr/bin/env python3
"""Regenerate the builtin route inventory baseline (P1 route migration)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.infrastructure.plugins.route_inventory import (  # noqa: E402
    INVENTORY_PATH,
    generate_route_inventory,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=INVENTORY_PATH,
        help="baseline path (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the baseline drifts from main.py",
    )
    args = parser.parse_args(argv)

    inventory = generate_route_inventory()
    payload = json.dumps(inventory.to_payload(), indent=2, sort_keys=True) + "\n"

    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != payload:
            print(
                f"route inventory drifted from {args.output}; regenerate with "
                "`uv run python scripts/generate_route_inventory.py`",
                file=sys.stderr,
            )
            return 1
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(f"wrote {args.output}: {len(inventory.entries)} entries, digest {inventory.digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
