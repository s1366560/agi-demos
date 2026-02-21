"""Tests for ChannelEventBridge."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.application.services.channels.event_bridge import (
    ChannelEventBridge,
    get_channel_event_bridge,
)


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
) -> SimpleNamespace:
    return SimpleNamespace(
        channel_config_id=channel_config_id,
        chat_id=chat_id,
        channel_type=channel_type,
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

    await bridge.on_agent_event("conv-1", {
        "type": "error",
        "data": {"message": "Something broke", "code": "INTERNAL"},
    })

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    assert card["header"]["template"] == "red"
    assert "Something broke" in card["elements"][0]["content"]
    assert "INTERNAL" in card["elements"][0]["content"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hitl_event_sends_card_with_options() -> None:
    adapter = _make_adapter()
    binding = _make_binding()
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=adapter)

    await bridge.on_agent_event("conv-1", {
        "type": "clarification_asked",
        "data": {
            "question": "Which database?",
            "options": ["PostgreSQL", "MySQL"],
            "request_id": "hitl-123",
        },
    })

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    assert card["header"]["title"]["content"] == "Agent needs clarification"
    # Should have markdown element + action element
    assert len(card["elements"]) == 2
    actions = card["elements"][1]["actions"]
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

    await bridge.on_agent_event("conv-1", {
        "type": "decision_asked",
        "data": {
            "question": "Which approach?",
            "options": ["A", "B", "C"],
            "risk_level": "high",
            "request_id": "hitl-456",
        },
    })

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    assert card["header"]["title"]["content"] == "Agent needs a decision"
    assert card["header"]["template"] == "orange"
    assert card["config"] == {"wide_screen_mode": True}
    assert "[!]" in card["elements"][0]["content"]
    actions = card["elements"][1]["actions"]
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

    await bridge.on_agent_event("conv-1", {
        "type": "clarification_asked",
        "data": {"question": "", "options": [], "request_id": "hitl-x"},
    })

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

    await bridge.on_agent_event("conv-1", {
        "type": "task_list_updated",
        "data": {
            "tasks": [
                {"title": "Setup DB", "status": "completed"},
                {"title": "Write tests", "status": "in_progress"},
            ],
        },
    })

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    task_text = card["elements"][2]["content"]
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

    await bridge.on_agent_event("conv-1", {
        "type": "artifact_ready",
        "data": {"name": "report.pdf", "url": "https://example.com/dl"},
    })

    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.call_args[0][1]
    assert card["header"]["template"] == "green"
    assert "report.pdf" in card["elements"][0]["content"]
    # Download button present
    assert card["elements"][1]["actions"][0]["url"] == "https://example.com/dl"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_adapter_skips_silently() -> None:
    binding = _make_binding()
    bridge = ChannelEventBridge()
    bridge._lookup_binding = AsyncMock(return_value=binding)
    bridge._get_adapter = MagicMock(return_value=None)

    # Should not raise
    await bridge.on_agent_event("conv-1", {
        "type": "error",
        "data": {"message": "fail"},
    })


@pytest.mark.unit
def test_build_hitl_card_structure() -> None:
    bridge = ChannelEventBridge()
    card = bridge._build_hitl_card({
        "question": "Pick a color",
        "options": ["Red", "Blue", "Green"],
        "request_id": "req-42",
    })

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
    assert actions[0]["value"]["response_data"]["answer"] == "Red"


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
