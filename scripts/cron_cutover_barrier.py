#!/usr/bin/env python3
"""Inspect or prepare a scheduler deployment barrier; never activate an owner."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.domain.model.cron.cutover import CronDeploymentManifest, CronDeploymentReceipt
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
    CronCutoverConflictError,
    SqlCronCutoverRepository,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    _ = commands.add_parser("inspect", help="Read the persisted barrier without changing ownership")
    prepare = commands.add_parser("prepare", help="Close Python admission and record the inventory")
    _ = prepare.add_argument("--manifest-file", type=Path, required=True)
    _ = prepare.add_argument("--expected-revision", type=int, required=True)
    receipt = commands.add_parser("record-receipt", help="Append an unverified deployment receipt")
    _ = receipt.add_argument("--receipt-file", type=Path, required=True)
    _ = receipt.add_argument("--expected-revision", type=int, required=True)
    observe = commands.add_parser("observe", help="Record current database blockers; do not verify")
    _ = observe.add_argument("--expected-revision", type=int, required=True)
    return parser.parse_args(argv)


async def execute_command(args: argparse.Namespace) -> dict[str, object]:
    async with async_session_factory() as session:
        repository = SqlCronCutoverRepository(session)
        if args.command == "inspect":
            return (await repository.read()).to_wire()
        if args.command == "prepare":
            manifest = CronDeploymentManifest.from_wire(
                json.loads(args.manifest_file.read_text(encoding="utf-8"))
            )
            result = await repository.prepare(manifest, args.expected_revision)
        elif args.command == "record-receipt":
            receipt = CronDeploymentReceipt.from_wire(
                json.loads(args.receipt_file.read_text(encoding="utf-8"))
            )
            result = await repository.record_receipt(receipt, args.expected_revision)
        elif args.command == "observe":
            result = await repository.observe(args.expected_revision)
        else:
            raise ValueError("invalid cron cutover command")
        await session.commit()
        return result.to_wire()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = asyncio.run(execute_command(args))
    except (CronCutoverConflictError, ValueError, OSError):
        print(
            "Cron cutover request rejected: check protocol, deployment identity and revision.",
            file=sys.stderr,
        )
        return 2
    except Exception:
        print("Cron cutover storage unavailable; ownership remains unverified.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
