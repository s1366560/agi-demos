"""Contracts for canonical Workspace migration values and CLI arguments."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.infrastructure.workspace_core.migration.cli import build_parser
from src.infrastructure.workspace_core.migration.model import (
    MigrationCommand,
    canonical_hash,
    canonical_json,
)

pytestmark = pytest.mark.unit


def test_canonical_json_normalizes_key_order_and_utc_timestamps() -> None:
    left = {"b": [2, {"z": True, "a": None}], "a": datetime(2026, 8, 10, tzinfo=UTC)}
    right = {"a": datetime(2026, 8, 10), "b": [2, {"a": None, "z": True}]}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_hash(left) == canonical_hash(right)


@pytest.mark.parametrize("command", list(MigrationCommand))
def test_cli_requires_a_versioned_run_id(command: MigrationCommand) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([command.value])


def test_reverse_export_requires_output_path() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([MigrationCommand.REVERSE_EXPORT.value, "--run-id", "cutover-1"])
