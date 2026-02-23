"""Unit tests for CardKit streaming orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.adapters.secondary.channels.feishu.cardkit_streaming import (
    CONTENT_ELEMENT_ID,
    CardKitSequence,
    CardKitStreamingManager,
    CardStreamState,
    build_initial_card_data,
    build_streaming_settings,
)

# ------------------------------------------------------------------
# CardKitSequence
# ------------------------------------------------------------------


@pytest.mark.unit
class TestCardKitSequence:
    def test_next_starts_at_one(self) -> None:
        seq = CardKitSequence()
        assert seq.next("card_1") == 1

    def test_next_increments(self) -> None:
        seq = CardKitSequence()
        assert seq.next("card_1") == 1
        assert seq.next("card_1") == 2
        assert seq.next("card_1") == 3

    def test_separate_cards(self) -> None:
        seq = CardKitSequence()
        assert seq.next("card_a") == 1
        assert seq.next("card_b") == 1
        assert seq.next("card_a") == 2

    def test_current(self) -> None:
        seq = CardKitSequence()
        assert seq.current("card_1") == 0
        seq.next("card_1")
        assert seq.current("card_1") == 1

    def test_remove(self) -> None:
        seq = CardKitSequence()
        seq.next("card_1")
        seq.remove("card_1")
        assert seq.current("card_1") == 0
        assert seq.next("card_1") == 1


# ------------------------------------------------------------------
# build helpers
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildHelpers:
    def test_build_initial_card_data(self) -> None:
        card = build_initial_card_data("Test Bot")
        assert card["schema"] == "2.0"
        assert card["config"]["update_multi"] is True
        assert card["header"]["title"]["content"] == "Test Bot"
        elements = card["body"]["elements"]
        assert len(elements) == 1
        assert elements[0]["tag"] == "markdown"
        assert elements[0]["element_id"] == CONTENT_ELEMENT_ID

    def test_build_streaming_settings_enable(self) -> None:
        settings = build_streaming_settings(enabled=True)
        assert settings["config"]["streaming_mode"] is True
        assert "streaming_config" in settings["config"]

    def test_build_streaming_settings_disable(self) -> None:
        settings = build_streaming_settings(enabled=False)
        assert settings["config"]["streaming_mode"] is False
        assert "streaming_config" not in settings["config"]


# ------------------------------------------------------------------
# CardStreamState
# ------------------------------------------------------------------


@pytest.mark.unit
class TestCardStreamState:
    def test_next_seq(self) -> None:
        state = CardStreamState(card_id="card_x")
        assert state.next_seq() == 1
        assert state.next_seq() == 2

    def test_defaults(self) -> None:
        state = CardStreamState(card_id="card_x")
        assert state.message_id is None
        assert state.streaming_active is False
        assert state.last_content == ""


# ------------------------------------------------------------------
# CardKitStreamingManager
# ------------------------------------------------------------------


def _make_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.create_card_entity = AsyncMock(return_value="card_123")
    adapter.update_card_settings = AsyncMock(return_value=True)
    adapter.send_card_entity_message = AsyncMock(return_value="msg_456")
    adapter.stream_text_content = AsyncMock(return_value=True)
    adapter.add_card_elements = AsyncMock(return_value=True)
    return adapter


@pytest.mark.unit
class TestCardKitStreamingManager:
    async def test_start_streaming_success(self) -> None:
        adapter = _make_adapter()
        mgr = CardKitStreamingManager(adapter)

        state = await mgr.start_streaming("oc_chat1", reply_to="msg_orig")
        assert state is not None
        assert state.card_id == "card_123"
        assert state.message_id == "msg_456"
        assert state.streaming_active is True

        adapter.create_card_entity.assert_awaited_once()
        adapter.update_card_settings.assert_awaited_once()
        adapter.send_card_entity_message.assert_awaited_once_with(
            "oc_chat1", "card_123", "msg_orig"
        )

    async def test_start_streaming_entity_fails(self) -> None:
        adapter = _make_adapter()
        adapter.create_card_entity = AsyncMock(return_value=None)
        mgr = CardKitStreamingManager(adapter)

        state = await mgr.start_streaming("oc_chat1")
        assert state is None

    async def test_update_text_sends_content(self) -> None:
        adapter = _make_adapter()
        mgr = CardKitStreamingManager(adapter)
        state = CardStreamState(card_id="card_1", streaming_active=True)

        result = await mgr.update_text(state, "Hello", force=True)
        assert result is True
        adapter.stream_text_content.assert_awaited_once_with(
            "card_1", CONTENT_ELEMENT_ID, "Hello", 1
        )
        assert state.last_content == "Hello"

    async def test_update_text_skips_same_content(self) -> None:
        adapter = _make_adapter()
        mgr = CardKitStreamingManager(adapter)
        state = CardStreamState(card_id="card_1", streaming_active=True)
        state.last_content = "Hello"

        result = await mgr.update_text(state, "Hello", force=True)
        assert result is False
        adapter.stream_text_content.assert_not_awaited()

    async def test_update_text_not_active(self) -> None:
        adapter = _make_adapter()
        mgr = CardKitStreamingManager(adapter)
        state = CardStreamState(card_id="card_1", streaming_active=False)

        result = await mgr.update_text(state, "Hello", force=True)
        assert result is False

    async def test_finish_streaming(self) -> None:
        adapter = _make_adapter()
        mgr = CardKitStreamingManager(adapter)
        state = CardStreamState(card_id="card_1", streaming_active=True)

        result = await mgr.finish_streaming(state, "Final answer")
        assert result is True
        assert state.streaming_active is False

        # Should have called stream_text_content for final text
        adapter.stream_text_content.assert_awaited_once()
        # And update_card_settings to disable streaming
        adapter.update_card_settings.assert_awaited_once()

    async def test_add_hitl_buttons(self) -> None:
        adapter = _make_adapter()
        mgr = CardKitStreamingManager(adapter)
        state = CardStreamState(card_id="card_1", streaming_active=False)

        buttons = [{"tag": "button", "text": {"tag": "plain_text", "content": "OK"}}]
        result = await mgr.add_hitl_buttons(state, buttons)
        assert result is True
        adapter.add_card_elements.assert_awaited_once()

    async def test_add_hitl_buttons_closes_streaming_first(self) -> None:
        adapter = _make_adapter()
        mgr = CardKitStreamingManager(adapter)
        state = CardStreamState(card_id="card_1", streaming_active=True)
        state.last_content = "Some text"

        buttons = [{"tag": "button", "text": {"tag": "plain_text", "content": "OK"}}]
        await mgr.add_hitl_buttons(state, buttons)

        # Should have disabled streaming first
        assert state.streaming_active is False
        adapter.update_card_settings.assert_awaited()
        adapter.add_card_elements.assert_awaited()
