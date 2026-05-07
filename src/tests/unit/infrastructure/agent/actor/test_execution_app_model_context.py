"""Unit tests for app model context system-message injection."""

from __future__ import annotations

import pytest

from src.infrastructure.agent.actor.execution import (
    _inject_app_model_context,
    _inject_preferred_language_context,
)


@pytest.mark.unit
class TestInjectAppModelContext:
    def test_workspace_runtime_context_uses_workspace_system_header(self) -> None:
        messages = [{"role": "user", "content": "hello"}]

        injected = _inject_app_model_context(
            messages,
            {
                "context_type": "workspace_worker_runtime",
                "workspace_binding": {"workspace_task_id": "task-1"},
            },
        )

        assert injected[0]["role"] == "system"
        assert "[Workspace Runtime Context]" in injected[0]["content"]
        assert "Never print textual tool-call markup" in injected[0]["content"]
        assert "[MCP App Context]" not in injected[0]["content"]
        assert injected[1:] == messages

    def test_mcp_context_keeps_mcp_header(self) -> None:
        messages = [{"role": "user", "content": "hello"}]

        injected = _inject_app_model_context(messages, {"pane": "chart"})

        assert injected[0]["role"] == "system"
        assert "[MCP App Context]" in injected[0]["content"]
        assert injected[1:] == messages

    @pytest.mark.parametrize(
        ("preferred_language", "expected_phrase"),
        [
            ("zh-CN", "Simplified Chinese"),
            ("en-US", "English"),
        ],
    )
    def test_preferred_language_context_instructs_reply_language(
        self,
        preferred_language: str,
        expected_phrase: str,
    ) -> None:
        messages = [{"role": "user", "content": "hello"}]

        injected = _inject_preferred_language_context(messages, preferred_language)

        assert injected[0]["role"] == "system"
        assert "[Response Language]" in injected[0]["content"]
        assert expected_phrase in injected[0]["content"]
        assert "Do not translate quoted user content" in injected[0]["content"]
        assert injected[1:] == messages

    def test_preferred_language_context_ignores_unknown_language(self) -> None:
        messages = [{"role": "user", "content": "hello"}]

        injected = _inject_preferred_language_context(messages, "fr-FR")

        assert injected is messages
