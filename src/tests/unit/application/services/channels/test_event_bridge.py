"""Tests for ChannelEventBridge."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.channels import event_bridge as event_bridge_module
from src.application.services.channels.event_bridge import ChannelEventBridge


def _make_adapter(**overrides) -> MagicMock:
    adapter = MagicMock()
    adapter.send_card = AsyncMock(return_value="card_msg_1")
    adapter.send_text = AsyncMock(return_value="text_msg_1")
    adapter.send_markdown_card = AsyncMock(return_value="md_msg_1")
    # CardKit flow returns None by default (falls back to static card)
    adapter.send_hitl_card_via_cardkit = AsyncMock(return_value=None)
    for k, v in overrides.items():
        setattr(adapter, k, v)
    return adapter


def _make_binding(
    channel_config_id: str = "cfg-1",
    chat_id: str = "chat-abc",
    channel_type: str = "feishu",
    thread_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        channel_config_id=channel_config_id,
        chat_id=chat_id,
        channel_type=channel_type,
        thread_id=thread_id,
    )


def _make_conn(adapter: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(adapter=adapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_agent_event_ignores_non_forwarded_types() -> None:
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock()  # Should NOT be called
    await bridge.on_agent_event("conv-1", {"type": "text_delta", "data": {}})
    bridge._lookup_binding.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_agent_event_skips_when_no_binding() -> None:
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=None)
    await bridge.on_agent_event("conv-1", {"type": "error", "data": {"message": "fail"}})
    bridge._lookup_binding.assert_awaited_once_with("conv-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_event_sends_card() -> None:
    adapter = _make_adapter()
    binding = _make_binding()
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-1",
        {
            "type": "error",
            "data": {"message": "Something broke", "code": "INTERNAL"},
        },
    )

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "red"
    assert "Something broke" in card["body"]["elements"][0]["content"]
    assert "INTERNAL" in card["body"]["elements"][0]["content"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hitl_event_sends_card_with_options() -> None:
    adapter = _make_adapter()
    binding = _make_binding()
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-1",
        {
            "type": "clarification_asked",
            "data": {
                "question": "Which database?",
                "options": ["PostgreSQL", "MySQL"],
                "request_id": "hitl-123",
            },
        },
    )

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    assert card["schema"] == "2.0"
    assert card["header"]["title"]["content"] == "Agent needs clarification"
    # Should have markdown element + action element
    assert len(card["body"]["elements"]) == 2
    actions = card["body"]["elements"][1]["actions"]
    assert len(actions) == 2
    assert actions[0]["value"]["hitl_request_id"] == "hitl-123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decision_event_sends_decision_card() -> None:
    """Verify _event_type injection routes decision_asked to decision card."""
    adapter = _make_adapter()
    binding = _make_binding()
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-1",
        {
            "type": "decision_asked",
            "data": {
                "question": "Which approach?",
                "options": ["A", "B", "C"],
                "risk_level": "high",
                "request_id": "hitl-456",
            },
        },
    )

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    assert card["schema"] == "2.0"
    assert card["header"]["title"]["content"] == "Agent needs a decision"
    assert card["header"]["template"] == "orange"
    assert card["config"] == {"wide_screen_mode": True}
    assert "[!]" in card["body"]["elements"][0]["content"]
    actions = card["body"]["elements"][1]["actions"]
    assert len(actions) == 3
    assert actions[0]["value"]["hitl_request_id"] == "hitl-456"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hitl_event_falls_back_to_text_when_no_question() -> None:
    adapter = _make_adapter()
    binding = _make_binding()
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-1",
        {
            "type": "clarification_asked",
            "data": {"question": "", "options": [], "request_id": "hitl-x"},
        },
    )

    # No card or text sent for empty question
    adapter.send_card.assert_not_awaited()
    adapter.send_text.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_task_update_sends_rich_card() -> None:
    adapter = _make_adapter()
    binding = _make_binding()
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-1",
        {
            "type": "task_list_updated",
            "data": {
                "tasks": [
                    {"title": "Setup DB", "status": "completed"},
                    {"title": "Write tests", "status": "in_progress"},
                ],
            },
        },
    )

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    assert card["schema"] == "2.0"
    task_text = card["body"]["elements"][2]["content"]
    assert "Setup DB" in task_text
    assert "Write tests" in task_text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_artifact_ready_sends_rich_card() -> None:
    adapter = _make_adapter()
    binding = _make_binding()
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-1",
        {
            "type": "artifact_ready",
            "data": {"name": "report.pdf", "url": "https://example.com/dl"},
        },
    )

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "green"
    assert "report.pdf" in card["body"]["elements"][0]["content"]
    # Download button present
    assert card["body"]["elements"][1]["actions"][0]["url"] == "https://example.com/dl"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_adapter_skips_silently() -> None:
    binding = _make_binding()
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=None)

    # Should not raise
    await bridge.on_agent_event(
        "conv-1",
        {
            "type": "error",
            "data": {"message": "fail"},
        },
    )


@pytest.mark.unit
def test_build_hitl_card_structure() -> None:
    bridge = ChannelEventBridge()
    card = bridge._build_hitl_card(
        {
            "question": "Pick a color",
            "options": ["Red", "Blue", "Green"],
            "request_id": "req-42",
        }
    )

    assert card is not None
    assert card["config"]["wide_screen_mode"] is True
    assert card["header"]["template"] == "blue"

    elements = card["elements"]
    assert elements[0]["tag"] == "markdown"
    assert "Pick a color" in elements[0]["content"]

    actions = elements[1]["actions"]
    assert len(actions) == 3
    assert actions[0]["type"] == "primary"  # First button is primary
    assert actions[1]["type"] == "default"
    assert actions[0]["value"]["hitl_request_id"] == "req-42"
    assert actions[0]["value"]["response_data"] == json.dumps({"answer": "Red"})


@pytest.mark.unit
def test_format_hitl_text_with_options() -> None:
    bridge = ChannelEventBridge()
    text = bridge._format_hitl_text("Which DB?", ["Postgres", "MySQL"])
    assert "[Agent Question] Which DB?" in text
    assert "1. Postgres" in text
    assert "2. MySQL" in text


@pytest.mark.unit
def test_format_hitl_text_empty_question() -> None:
    bridge = ChannelEventBridge()
    assert bridge._format_hitl_text("", []) == ""


@pytest.mark.unit
async def test_hitl_event_tries_cardkit_first() -> None:
    """Event bridge should try CardKit flow before falling back to static card."""
    adapter = _make_adapter(
        send_hitl_card_via_cardkit=AsyncMock(return_value="ck_msg_1"),
    )
    bridge = ChannelEventBridge()

    with patch.object(bridge, "_lookup_binding", new_callable=AsyncMock) as mock_bind:
        mock_bind.return_value = _make_binding()
        with patch.object(bridge, "_get_adapter", return_value=adapter):
            await bridge.on_agent_event(
                "conv-ck1",
                {
                    "type": "decision_asked",
                    "data": {
                        "request_id": "req-ck1",
                        "question": "Which?",
                        "options": ["A", "B"],
                    },
                },
            )

    adapter.send_hitl_card_via_cardkit.assert_called_once()
    adapter.send_card.assert_not_called()


@pytest.mark.unit
async def test_hitl_event_falls_back_when_cardkit_fails() -> None:
    """Event bridge should fall back to static card if CardKit returns None."""
    adapter = _make_adapter(
        send_hitl_card_via_cardkit=AsyncMock(return_value=None),
    )
    bridge = ChannelEventBridge()

    with patch.object(bridge, "_lookup_binding", new_callable=AsyncMock) as mock_bind:
        mock_bind.return_value = _make_binding()
        with patch.object(bridge, "_get_adapter", return_value=adapter):
            await bridge.on_agent_event(
                "conv-ck2",
                {
                    "type": "clarification_asked",
                    "data": {
                        "request_id": "req-ck2",
                        "question": "What DB?",
                        "options": ["PG", "MySQL"],
                    },
                },
            )

    adapter.send_hitl_card_via_cardkit.assert_called_once()
    adapter.send_card.assert_called_once()  # Fallback to static card


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unified_hitl_adds_buttons_to_streaming_card() -> None:
    """When card_state is registered, HITL buttons go onto the streaming card."""
    adapter = _make_adapter(
        add_card_elements=AsyncMock(return_value=True),
        update_card_settings=AsyncMock(return_value=True),
    )
    bridge = ChannelEventBridge()

    # Simulate a CardStreamState
    card_state = SimpleNamespace(
        card_id="card_unified",
        message_id="msg_unified",
        streaming_active=False,
        last_content="Some response",
    )
    card_state.next_seq = MagicMock(side_effect=[1, 2, 3, 4])

    bridge.register_card_state("conv-unified", card_state)

    with (
        patch.object(bridge, "_lookup_binding", new_callable=AsyncMock) as mock_bind,
        patch.object(bridge, "_get_adapter", return_value=adapter),
    ):
        mock_bind.return_value = _make_binding()
        await bridge.on_agent_event(
            "conv-unified",
            {
                "type": "decision_asked",
                "data": {
                    "request_id": "req-unified",
                    "question": "Pick one",
                    "options": ["A", "B"],
                },
            },
        )

    # Should have added elements to existing card, NOT created standalone
    adapter.add_card_elements.assert_called_once()
    adapter.send_hitl_card_via_cardkit.assert_not_called()
    adapter.send_card.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_card_state_lifecycle() -> None:
    """register/unregister/get card state methods work correctly."""
    bridge = ChannelEventBridge()
    assert bridge.get_card_state("conv-1") is None

    state = SimpleNamespace(card_id="card_1")
    bridge.register_card_state("conv-1", state)
    assert bridge.get_card_state("conv-1") is state

    bridge.unregister_card_state("conv-1")
    assert bridge.get_card_state("conv-1") is None


@pytest.mark.unit
def test_channel_event_bridge_accepts_configured_focus_ttl() -> None:
    bridge = ChannelEventBridge(subagent_focus_ttl_seconds=42.5)
    assert bridge._subagent_focus_ttl_seconds == 42.5


@pytest.mark.unit
def test_get_channel_event_bridge_uses_settings_focus_ttl() -> None:
    event_bridge_module._bridge = None
    with patch.object(
        event_bridge_module,
        "get_settings",
        return_value=SimpleNamespace(agent_subagent_focus_ttl_seconds=12.0),
    ):
        bridge = event_bridge_module.get_channel_event_bridge()
        assert bridge._subagent_focus_ttl_seconds == 12.0
    event_bridge_module._bridge = None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subagent_spawned_binds_to_thread_and_tracks_focus() -> None:
    adapter = _make_adapter()
    binding = _make_binding(thread_id="root-msg-1")
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-sub-1",
        {
            "type": "subagent_session_spawned",
            "data": {
                "run_id": "run-sub-1",
                "conversation_id": "conv-sub-1",
                "subagent_name": "researcher",
            },
        },
    )

    adapter.send_markdown_card.assert_awaited_once()
    assert adapter.send_markdown_card.await_args.kwargs["reply_to"] == "root-msg-1"
    assert bridge._subagent_focus["conv-sub-1"]["run_id"] == "run-sub-1"
    bridge._clear_subagent_focus(conversation_id="conv-sub-1", run_id="run-sub-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subagent_completion_clears_focus_and_replies_in_thread() -> None:
    adapter = _make_adapter()
    binding = _make_binding(thread_id="root-msg-2")
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-sub-2",
        {
            "type": "subagent_session_spawned",
            "data": {
                "run_id": "run-sub-2",
                "conversation_id": "conv-sub-2",
                "subagent_name": "coder",
            },
        },
    )
    adapter.send_markdown_card.reset_mock()

    await bridge.on_agent_event(
        "conv-sub-2",
        {
            "type": "subagent_run_completed",
            "data": {
                "run_id": "run-sub-2",
                "conversation_id": "conv-sub-2",
                "subagent_name": "coder",
                "summary": "done",
            },
        },
    )

    adapter.send_markdown_card.assert_awaited_once()
    sent_markdown = adapter.send_markdown_card.await_args.args[1]
    assert "completed" in sent_markdown.lower()
    assert "done" in sent_markdown
    assert adapter.send_markdown_card.await_args.kwargs["reply_to"] == "root-msg-2"
    assert "conv-sub-2" not in bridge._subagent_focus


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subagent_focus_timeout_auto_unfocuses() -> None:
    adapter = _make_adapter()
    binding = _make_binding(thread_id="root-msg-3")
    bridge = ChannelEventBridge()
    bridge._subagent_focus_ttl_seconds = 0.01
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-sub-3",
        {
            "type": "subagent_session_spawned",
            "data": {
                "run_id": "run-sub-3",
                "conversation_id": "conv-sub-3",
                "subagent_name": "planner",
            },
        },
    )

    timeout_task = bridge._subagent_focus_timeout_tasks["conv-sub-3"]
    await timeout_task
    await asyncio.sleep(0)

    assert adapter.send_markdown_card.await_count == 2
    timeout_markdown = adapter.send_markdown_card.await_args_list[-1].args[1]
    assert "auto-cleared" in timeout_markdown
    assert "conv-sub-3" not in bridge._subagent_focus


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subagent_retry_refreshes_focus_timeout() -> None:
    adapter = _make_adapter()
    binding = _make_binding(thread_id="root-msg-4")
    bridge = ChannelEventBridge()
    bridge._subagent_focus_ttl_seconds = 0.2
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event(
        "conv-sub-4",
        {
            "type": "subagent_session_spawned",
            "data": {
                "run_id": "run-sub-4",
                "conversation_id": "conv-sub-4",
                "subagent_name": "worker",
            },
        },
    )
    original_task = bridge._subagent_focus_timeout_tasks["conv-sub-4"]

    await bridge.on_agent_event(
        "conv-sub-4",
        {
            "type": "subagent_announce_retry",
            "data": {
                "run_id": "run-sub-4",
                "conversation_id": "conv-sub-4",
                "subagent_name": "worker",
            },
        },
    )

    refreshed_task = bridge._subagent_focus_timeout_tasks["conv-sub-4"]
    await asyncio.sleep(0)
    assert refreshed_task is not original_task
    assert original_task.cancelled()
    bridge._clear_subagent_focus(conversation_id="conv-sub-4", run_id="run-sub-4")
