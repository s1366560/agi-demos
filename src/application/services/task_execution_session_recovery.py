"""Retirement marker for platform-owned Workspace task recovery.

Workspace task recovery, retry receipts, and replay are owned by Avernet Core.
The former platform worker intentionally has no runtime implementation.
"""

from __future__ import annotations

RETIRED_REASON = "workspace_core_authoritative"

__all__ = ["RETIRED_REASON"]
