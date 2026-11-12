"""Locate the in-repo plugin SDK without publishing it."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_plugin_sdk_path() -> None:
    sdk = Path(__file__).resolve().parents[3] / "sdk" / "memstack-plugin-sdk" / "src"
    entry = str(sdk)
    if entry not in sys.path:
        sys.path.insert(0, entry)


def invoke_memory_offsets() -> tuple[int, int]:
    ensure_plugin_sdk_path()
    from memstack_plugin_sdk.contract import INVOKE_INPUT_OFFSET, INVOKE_OUTPUT_OFFSET

    return INVOKE_INPUT_OFFSET, INVOKE_OUTPUT_OFFSET
