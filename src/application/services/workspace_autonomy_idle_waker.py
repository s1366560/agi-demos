"""Retirement marker for the legacy Workspace autonomy idle waker.

Avernet Core owns Workspace task scheduling and recovery. Platform startup must
not scan legacy Workspace tables or schedule authority-side ticks.
"""

from __future__ import annotations

RETIRED_REASON = "workspace_core_authoritative"

__all__ = ["RETIRED_REASON"]
