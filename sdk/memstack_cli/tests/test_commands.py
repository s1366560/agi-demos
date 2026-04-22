"""Tests for command wiring, output formatting, and auth precedence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from memstack_cli.auth import save_api_key
from memstack_cli.cli import cli
from memstack_cli.client import ApiError

from .conftest import FakeRequest


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestTopLevel:
    def test_help_lists_all_commands(self, runner: CliRunner) -> None:
        res = runner.invoke(cli, ["--help"])
        assert res.exit_code == 0
        for name in (
            "login",
            "logout",
            "whoami",
            "projects",
            "conversations",
            "chat",
            "logs",
            "artifacts",
        ):
            assert name in res.output

    def test_version_flag(self, runner: CliRunner) -> None:
        res = runner.invoke(cli, ["--version"])
        assert res.exit_code == 0
        assert "memstack" in res.output.lower()

    def test_missing_api_key_exits_2(
        self, runner: CliRunner, fake_request: FakeRequest
    ) -> None:
        res = runner.invoke(cli, ["whoami"])
        assert res.exit_code == 2


class TestWhoami:
    def test_human_output(self, runner: CliRunner, fake_request: FakeRequest) -> None:
        fake_request.responses[("GET", "/auth/me")] = {
            "id": "u1",
            "email": "a@b.com",
            "tenant_id": "t1",
            "is_superuser": True,
        }
        res = runner.invoke(cli, ["--api-key", "ms_sk_x", "whoami"])
        assert res.exit_code == 0, res.output + res.stderr
        assert "u1" in res.output
        assert "a@b.com" in res.output
        assert "t1" in res.output

    def test_json_output(self, runner: CliRunner, fake_request: FakeRequest) -> None:
        fake_request.responses[("GET", "/auth/me")] = {"id": "u1", "email": "a@b.com"}
        res = runner.invoke(cli, ["--api-key", "k", "--json", "whoami"])
        assert res.exit_code == 0
        payload = json.loads(res.output.strip().splitlines()[-1])
        assert payload["id"] == "u1"

    def test_file_credential_used_when_no_flag(
        self, runner: CliRunner, fake_request: FakeRequest, isolated_home: Path
    ) -> None:
        save_api_key("ms_sk_from_file")
        fake_request.responses[("GET", "/auth/me")] = {"id": "u1"}
        res = runner.invoke(cli, ["whoami"])
        assert res.exit_code == 0
        assert fake_request.calls[0]["api_key"] == "ms_sk_from_file"

    def test_api_error_exits_1(self, runner: CliRunner, fake_request: FakeRequest) -> None:
        fake_request.error = ApiError(401, "unauthorized")
        res = runner.invoke(cli, ["--api-key", "k", "whoami"])
        assert res.exit_code == 1
        assert "401" in res.stderr


class TestProjects:
    def test_uses_tenant_from_me_when_not_given(
        self, runner: CliRunner, fake_request: FakeRequest
    ) -> None:
        fake_request.responses[("GET", "/auth/me")] = {"tenant_id": "t99"}
        fake_request.responses[("GET", "/projects/")] = {
            "items": [{"id": "p1", "name": "Alpha"}]
        }
        res = runner.invoke(cli, ["--api-key", "k", "projects"])
        assert res.exit_code == 0, res.stderr
        assert "p1" in res.output
        assert "Alpha" in res.output
        proj_call = fake_request.calls[1]
        assert proj_call["path"] == "/projects/"
        assert proj_call["params"] == {"tenant_id": "t99"}

    def test_tenant_override(self, runner: CliRunner, fake_request: FakeRequest) -> None:
        fake_request.responses[("GET", "/projects/")] = []
        res = runner.invoke(
            cli, ["--api-key", "k", "projects", "--tenant", "t42"]
        )
        assert res.exit_code == 0
        assert len(fake_request.calls) == 1
        assert fake_request.calls[0]["params"] == {"tenant_id": "t42"}

    def test_empty_list(self, runner: CliRunner, fake_request: FakeRequest) -> None:
        fake_request.responses[("GET", "/projects/")] = {"items": []}
        res = runner.invoke(
            cli, ["--api-key", "k", "projects", "--tenant", "t1"]
        )
        assert res.exit_code == 0
        assert "(no projects)" in res.output


class TestConversations:
    def test_project_filter(self, runner: CliRunner, fake_request: FakeRequest) -> None:
        fake_request.responses[("GET", "/agent/conversations")] = {
            "items": [{"id": "c1", "title": "hello"}]
        }
        res = runner.invoke(
            cli, ["--api-key", "k", "conversations", "--project", "p1"]
        )
        assert res.exit_code == 0
        assert "c1" in res.output
        assert fake_request.calls[0]["params"]["project_id"] == "p1"


class TestLogs:
    def test_human_output(self, runner: CliRunner, fake_request: FakeRequest) -> None:
        fake_request.responses[("GET", "/agent/conversations/c1/events")] = {
            "events": [
                {
                    "sequence_number": 1,
                    "event_type": "assistant_message",
                    "created_at": "2026-01-01T00:00:00Z",
                    "data": {"content": "hello world"},
                },
                {
                    "sequence_number": 2,
                    "event_type": "tool_call",
                    "created_at": "2026-01-01T00:00:01Z",
                    "data": {"tool_name": "shell"},
                },
            ],
            "has_more": False,
        }
        res = runner.invoke(cli, ["--api-key", "k", "logs", "c1"])
        assert res.exit_code == 0, res.stderr
        assert "assistant_message" in res.output
        assert "hello world" in res.output
        assert "tool_call" in res.output
        assert "shell" in res.output

    def test_type_filter(self, runner: CliRunner, fake_request: FakeRequest) -> None:
        fake_request.responses[("GET", "/agent/conversations/c1/events")] = {
            "events": [
                {"sequence_number": 1, "event_type": "assistant_message", "data": {}},
                {"sequence_number": 2, "event_type": "tool_call", "data": {}},
            ],
        }
        res = runner.invoke(
            cli, ["--api-key", "k", "logs", "c1", "--type", "tool_call"]
        )
        assert res.exit_code == 0
        assert "tool_call" in res.output
        assert "assistant_message" not in res.output

    def test_empty(self, runner: CliRunner, fake_request: FakeRequest) -> None:
        fake_request.responses[("GET", "/agent/conversations/c1/events")] = {
            "events": []
        }
        res = runner.invoke(cli, ["--api-key", "k", "logs", "c1"])
        assert res.exit_code == 0
        assert "(no events)" in res.output


class TestLogout:
    def test_removes_file_when_present(
        self, runner: CliRunner, isolated_home: Path
    ) -> None:
        save_api_key("k")
        res = runner.invoke(cli, ["logout"])
        assert res.exit_code == 0
        assert "Removed" in res.output
