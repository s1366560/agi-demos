"""Cutover CLI output contains status codes, never errors or receipt contents."""

from unittest.mock import AsyncMock

import pytest

from scripts import cron_cutover_barrier as cli
from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
    CronCutoverConflictError,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "error,code",
    [(CronCutoverConflictError("private receipt"), 2), (RuntimeError("database secret"), 1)],
)
def test_cli_errors_are_redacted(monkeypatch, capsys, error, code):
    monkeypatch.setattr(cli, "execute_command", AsyncMock(side_effect=error))
    assert cli.main(["inspect"]) == code
    output = capsys.readouterr()
    assert str(error) not in output.err
    assert not output.out


def test_cli_inspect_prints_structured_persisted_status(monkeypatch, capsys):
    monkeypatch.setattr(cli, "execute_command", AsyncMock(return_value={"phase": "unverified"}))
    assert cli.main(["inspect"]) == 0
    assert '"phase": "unverified"' in capsys.readouterr().out
