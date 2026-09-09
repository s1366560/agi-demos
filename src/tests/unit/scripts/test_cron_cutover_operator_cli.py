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


@pytest.mark.parametrize("command", ["prepare-reverse", "observe-reverse", "complete-reverse"])
def test_cli_reverse_commands_require_an_explicit_expected_revision(command):
    args = cli.parse_args([command, "--expected-revision", "7"])
    assert args.command == command and args.expected_revision == 7
    with pytest.raises(SystemExit):
        cli.parse_args([command])


def test_cli_reverse_conflict_is_redacted_without_leaking_details(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "execute_command", AsyncMock(side_effect=CronCutoverConflictError("private blocker"))
    )
    assert cli.main(["complete-reverse", "--expected-revision", "3"]) == 2
    output = capsys.readouterr()
    assert "private blocker" not in output.err
    assert not output.out
