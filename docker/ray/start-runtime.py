#!/usr/bin/env python3
"""Start a container command only with its image's installed dependency configuration."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def dependencies_current(project: Path, installed: Path) -> bool:
    """Compare actual build inputs, without resolving or changing dependencies at startup."""
    try:
        return all(
            (project / filename).read_bytes() == (installed / filename).read_bytes()
            for filename in ("pyproject.toml", "uv.lock")
        )
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/app"))
    parser.add_argument(
        "--installed-root", type=Path, default=Path("/opt/memstack-ray-dependencies")
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a container command is required")
    if not dependencies_current(args.project_root, args.installed_root):
        print(
            "Ray dependency configuration changed or is unavailable; rebuild the Ray image "
            "with make dev or make ray-rebuild before starting it.",
            file=sys.stderr,
        )
        return 78
    # Replacing PID 1 preserves signals and the command's exit status.
    os.execvp(command[0], command)  # noqa: S606 - Execute the explicit container command as PID 1.


if __name__ == "__main__":
    raise SystemExit(main())
