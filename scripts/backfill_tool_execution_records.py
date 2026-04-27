#!/usr/bin/env python3
"""Backfill tool_execution_records from historical agent_execution_events.

Usage:
    uv run python scripts/backfill_tool_execution_records.py --dry-run
    uv run python scripts/backfill_tool_execution_records.py --apply
    uv run python scripts/backfill_tool_execution_records.py --conversation-id <id> --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    project_root = Path(__file__).parent.parent
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill tool execution records from historical act/observe events.",
    )
    parser.add_argument("--conversation-id", help="Only scan a single conversation.")
    parser.add_argument("--limit", type=int, help="Limit scanned act/observe events.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist missing and incomplete tool execution records.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying rows (default).",
    )
    return parser


async def _run() -> int:
    _ensure_project_root_on_path()

    from src.application.services.tool_execution_backfill_service import (
        ToolExecutionBackfillService,
    )
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

    args = _build_parser().parse_args()
    apply_changes = args.apply and not args.dry_run

    async with async_session_factory() as session:
        async with session.begin():
            service = ToolExecutionBackfillService(session)
            stats = await service.backfill(
                conversation_id=args.conversation_id,
                limit=args.limit,
                apply_changes=apply_changes,
            )

    mode = "apply" if apply_changes else "dry-run"
    print(f"[tool-execution-backfill] mode={mode}")
    if args.conversation_id:
        print(f"[tool-execution-backfill] conversation_id={args.conversation_id}")
    if args.limit:
        print(f"[tool-execution-backfill] limit={args.limit}")
    print(f"[tool-execution-backfill] events_scanned={stats.events_scanned}")
    print(f"[tool-execution-backfill] events_skipped={stats.events_skipped}")
    print(f"[tool-execution-backfill] records_seen={stats.records_seen}")
    print(f"[tool-execution-backfill] records_inserted={stats.records_inserted}")
    print(f"[tool-execution-backfill] records_updated={stats.records_updated}")
    print(f"[tool-execution-backfill] records_unchanged={stats.records_unchanged}")

    if not apply_changes:
        print("[tool-execution-backfill] No rows updated. Re-run with --apply to persist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
