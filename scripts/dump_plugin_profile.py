#!/usr/bin/env python3
"""Print the effective platform plugin profile (dsh --dump-config equivalent)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.infrastructure.plugins.dump_config import (  # noqa: E402
    DEFAULT_PROFILE_PATH,
    DumpConfigError,
    dump_profile,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE_PATH,
        help="base profile document (default: %(default)s)",
    )
    parser.add_argument(
        "--patch",
        type=Path,
        action="append",
        default=[],
        help="ordered patch overlay applied after the profile patches (repeatable)",
    )
    parser.add_argument(
        "--format",
        choices=("yaml", "json"),
        default="yaml",
        help="yaml renders provenance comments; json is the canonical digest form",
    )
    args = parser.parse_args(argv)

    try:
        output = dump_profile(args.profile, tuple(args.patch), fmt=args.format)
    except DumpConfigError as exc:
        print(f"dump-config: {exc}", file=sys.stderr)
        return 1
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
