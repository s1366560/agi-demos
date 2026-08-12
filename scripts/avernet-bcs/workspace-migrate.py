#!/usr/bin/env python3
"""Repository entrypoint for Avernet Workspace data migration."""

from __future__ import annotations

import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from src.infrastructure.workspace_core.migration.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
