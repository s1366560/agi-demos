#!/usr/bin/env python3
"""Thin shim — delegates to the installed `memstack_cli` package.

The canonical CLI now lives under `sdk/memstack_cli/`. This script
preserves the `scripts/memstack-cli.py` entry point for anyone who was
invoking it directly (make targets, CI scripts, muscle memory).

Install the package to get the much shorter `memstack` command:

    uv pip install -e sdk/memstack_cli
"""
from __future__ import annotations

import sys
from pathlib import Path


def _ensure_importable() -> None:
    """Make `memstack_cli` importable without installation.

    Falls back to PYTHONPATH manipulation so the script works in a fresh
    checkout before `uv pip install -e sdk/memstack_cli` has run.
    """
    try:
        import memstack_cli  # noqa: F401
        return
    except ImportError:
        pass

    pkg_root = Path(__file__).resolve().parent.parent / "sdk" / "memstack_cli"
    if (pkg_root / "memstack_cli" / "__init__.py").exists():
        sys.path.insert(0, str(pkg_root))


def main() -> None:
    _ensure_importable()
    try:
        from memstack_cli.cli import main as _main
    except ImportError as e:
        print(
            "error: memstack_cli is not installed. Run "
            "`uv pip install -e sdk/memstack_cli` or see docs/CLI.md.",
            file=sys.stderr,
        )
        print(f"(detail: {e})", file=sys.stderr)
        sys.exit(2)
    _main()


if __name__ == "__main__":
    main()
