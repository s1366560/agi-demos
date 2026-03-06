"""Unit tests for Canvas/A2UI system.

Covers: models, manager, events, and tools with 80%+ coverage target.
"""

from __future__ import annotations

import json

import pytest

from src.domain.events.agent_events import AgentCanvasUpdatedEvent
from src.domain.events.types import AgentEventType
from src.infrastructure.agent.canvas.events import build_canvas_event_dict
from src.infrastructure.agent.canvas.manager import CanvasManager
from src.infrastructure.agent.canvas.models import (
    CanvasBlock,
    CanvasBlockType,
    CanvasState,
)
from src.infrastructure.agent.canvas.tools import (
    canvas_create,
    canvas_delete,
    canvas_update,
    configure_canvas,
    get_canvas_manager,
)
from src.infrastructure.agent.tools.context import ToolContext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager() -> CanvasManager:
    return CanvasManager()


@pytest.fixture()
def ctx() -> ToolContext:
    """Minimal ToolContext for tool tests."""
    return ToolContext(
        session_id="sess-1",
        message_id="msg-1",
        call_id="call-1",
        agent_name="test-agent",
        conversation_id="conv-123",
    )


# ===========================================================================
# Models
# ===========================================================================


@pytest.mark.unit
class TestCanvasBlockType:
    """Test CanvasBlockType enum."""

    def test_all_values(self) -> None:
        expected = {"code", "table", "chart", "form", "image", "markdown", "widget", "a2ui_surface"}
        assert {t.value for t in CanvasBlockType} == expected

    def test_str_enum(self) -> None:
        assert CanvasBlockType.CODE == "code"
        assert isinstance(CanvasBlockType.TABLE, str)


@pytest.mark.unit
class TestCanvasBlock:
    """Test CanvasBlock frozen dataclass."""

    def test_defaults(self) -> None:
        block = CanvasBlock()
        assert block.block_type == CanvasBlockType.MARKDOWN
        assert block.title == ""
        assert block.content == ""
        assert block.metadata == {}
        assert block.version == 1
        assert len(block.id) == 36  # UUID4

    def test_custom_fields(self) -> None:
        block = CanvasBlock(
            id="b-1",
            block_type=CanvasBlockType.CODE,
            title="Hello",
            content="print('hi')",
            metadata={"language": "python"},
            version=3,
        )
        assert block.id == "b-1"
        assert block.block_type == CanvasBlockType.CODE
        assert block.title == "Hello"
        assert block.content == "print('hi')"
        assert block.metadata == {"language": "python"}
        assert block.version == 3

    def test_frozen(self) -> None:
        block = CanvasBlock(id="b-1")
        with pytest.raises(AttributeError):
            block.title = "new"

    def test_to_dict(self) -> None:
        block = CanvasBlock(
            id="b-1",
            block_type=CanvasBlockType.TABLE,
            title="Data",
            content='[{"a": 1}]',
            metadata={"cols": "a"},
            version=2,
        )
        d = block.to_dict()
        assert d == {
            "id": "b-1",
            "block_type": "table",
            "title": "Data",
            "content": '[{"a": 1}]',
            "metadata": {"cols": "a"},
            "version": 2,
        }

    def test_with_content(self) -> None:
        block = CanvasBlock(id="b-1", content="old", version=1)
        updated = block.with_content("new")
        assert updated.content == "new"
        assert updated.version == 2
        assert updated.id == "b-1"
        # Original unchanged
        assert block.content == "old"
        assert block.version == 1

    def test_with_title(self) -> None:
        block = CanvasBlock(id="b-1", title="old", version=1)
        updated = block.with_title("new")
        assert updated.title == "new"
        assert updated.version == 2
        assert block.title == "old"


@pytest.mark.unit
class TestCanvasState:
    """Test CanvasState container."""

    def test_empty(self) -> None:
        state = CanvasState()
        assert state.block_count == 0
        assert state.all_blocks() == []

    def test_add_and_get(self) -> None:
        state = CanvasState()
        block = CanvasBlock(id="b-1", title="A")
        state.add(block)
        assert state.block_count == 1
        assert state.get("b-1") is block

    def test_get_nonexistent(self) -> None:
        state = CanvasState()
        assert state.get("nope") is None

    def test_remove(self) -> None:
        state = CanvasState()
        block = CanvasBlock(id="b-1")
        state.add(block)
        removed = state.remove("b-1")
        assert removed is block
        assert state.block_count == 0

    def test_remove_nonexistent(self) -> None:
        state = CanvasState()
        assert state.remove("nope") is None

    def test_all_blocks_returns_snapshot(self) -> None:
        state = CanvasState()
        state.add(CanvasBlock(id="b-1"))
        state.add(CanvasBlock(id="b-2"))
        blocks = state.all_blocks()
        assert len(blocks) == 2
        assert blocks[0].id == "b-1"
        assert blocks[1].id == "b-2"

    def test_clear(self) -> None:
        state = CanvasState()
        state.add(CanvasBlock(id="b-1"))
        state.clear()
        assert state.block_count == 0

    def test_add_replaces(self) -> None:
        state = CanvasState()
        state.add(CanvasBlock(id="b-1", title="old"))
        state.add(CanvasBlock(id="b-1", title="new"))
        assert state.block_count == 1
        assert state.get("b-1") is not None
        fetched = state.get("b-1")
        assert fetched is not None
        assert fetched.title == "new"


# ===========================================================================
# Manager
# ===========================================================================


@pytest.mark.unit
class TestCanvasManager:
    """Test CanvasManager CRUD."""

    def test_create_block(self, manager: CanvasManager) -> None:
        block = manager.create_block("conv-1", "code", "Script", "print(1)")
        assert block.block_type == CanvasBlockType.CODE
        assert block.title == "Script"
        assert block.content == "print(1)"
        assert block.version == 1

    def test_create_block_with_metadata(self, manager: CanvasManager) -> None:
        block = manager.create_block(
            "conv-1", "code", "Script", "x=1", metadata={"language": "python"}
        )
        assert block.metadata == {"language": "python"}

    def test_create_invalid_type(self, manager: CanvasManager) -> None:
        with pytest.raises(ValueError, match="Invalid block_type 'unknown'"):
            manager.create_block("conv-1", "unknown", "Bad", "")

    def test_get_blocks_empty(self, manager: CanvasManager) -> None:
        assert manager.get_blocks("conv-1") == []

    def test_get_blocks(self, manager: CanvasManager) -> None:
        manager.create_block("conv-1", "markdown", "A", "a")
        manager.create_block("conv-1", "code", "B", "b")
        blocks = manager.get_blocks("conv-1")
        assert len(blocks) == 2

    def test_get_block(self, manager: CanvasManager) -> None:
        block = manager.create_block("conv-1", "markdown", "A", "a")
        found = manager.get_block("conv-1", block.id)
        assert found is not None
        assert found.id == block.id

    def test_get_block_none(self, manager: CanvasManager) -> None:
        assert manager.get_block("conv-1", "nope") is None

    def test_update_content(self, manager: CanvasManager) -> None:
        block = manager.create_block("conv-1", "markdown", "A", "old")
        updated = manager.update_block("conv-1", block.id, content="new")
        assert updated.content == "new"
        assert updated.version == 2

    def test_update_title(self, manager: CanvasManager) -> None:
        block = manager.create_block("conv-1", "markdown", "A", "x")
        updated = manager.update_block("conv-1", block.id, title="B")
        assert updated.title == "B"
        assert updated.version == 2

    def test_update_metadata_merge(self, manager: CanvasManager) -> None:
        block = manager.create_block("conv-1", "code", "S", "x", metadata={"lang": "py"})
        updated = manager.update_block("conv-1", block.id, metadata={"theme": "dark"})
        assert updated.metadata == {"lang": "py", "theme": "dark"}

    def test_update_nonexistent(self, manager: CanvasManager) -> None:
        with pytest.raises(KeyError, match="not found"):
            manager.update_block("conv-1", "nope", content="x")

    def test_delete_block(self, manager: CanvasManager) -> None:
        block = manager.create_block("conv-1", "markdown", "A", "a")
        manager.delete_block("conv-1", block.id)
        assert manager.get_blocks("conv-1") == []

    def test_delete_nonexistent(self, manager: CanvasManager) -> None:
        with pytest.raises(KeyError, match="not found"):
            manager.delete_block("conv-1", "nope")

    def test_clear_conversation(self, manager: CanvasManager) -> None:
        manager.create_block("conv-1", "markdown", "A", "a")
        manager.clear_conversation("conv-1")
        assert manager.get_blocks("conv-1") == []

    def test_clear_nonexistent_conversation(self, manager: CanvasManager) -> None:
        # Should not raise
        manager.clear_conversation("nope")

    def test_to_snapshot(self, manager: CanvasManager) -> None:
        manager.create_block("conv-1", "markdown", "A", "a")
        snap = manager.to_snapshot("conv-1")
        assert len(snap) == 1
        assert snap[0]["title"] == "A"

    def test_to_snapshot_empty(self, manager: CanvasManager) -> None:
        assert manager.to_snapshot("conv-1") == []

    def test_isolation(self, manager: CanvasManager) -> None:
        """Different conversations are fully isolated."""
        manager.create_block("conv-1", "markdown", "A", "a")
        manager.create_block("conv-2", "code", "B", "b")
        assert len(manager.get_blocks("conv-1")) == 1
        assert len(manager.get_blocks("conv-2")) == 1
        assert manager.get_blocks("conv-1")[0].title == "A"
        assert manager.get_blocks("conv-2")[0].title == "B"


# ===========================================================================
# Events
# ===========================================================================


@pytest.mark.unit
class TestCanvasEvents:
    """Test event helpers and domain event."""

    def test_build_canvas_event_dict_created(self) -> None:
        block = CanvasBlock(id="b-1", block_type=CanvasBlockType.CODE, title="T")
        event = build_canvas_event_dict("conv-1", "b-1", "created", block)
        assert event["type"] == "canvas_updated"
        assert event["data"]["conversation_id"] == "conv-1"
        assert event["data"]["block_id"] == "b-1"
        assert event["data"]["action"] == "created"
        assert event["data"]["block"]["id"] == "b-1"

    def test_build_canvas_event_dict_deleted(self) -> None:
        event = build_canvas_event_dict("conv-1", "b-1", "deleted", None)
        assert event["type"] == "canvas_updated"
        assert event["data"]["block"] is None
        assert event["data"]["action"] == "deleted"

    def test_domain_event_class(self) -> None:
        evt = AgentCanvasUpdatedEvent(
            conversation_id="conv-1",
            block_id="b-1",
            action="created",
            block={"id": "b-1", "block_type": "code"},
        )
        assert evt.event_type == AgentEventType.CANVAS_UPDATED
        assert evt.conversation_id == "conv-1"
        assert evt.block_id == "b-1"
        assert evt.action == "created"
        assert evt.block is not None

    def test_domain_event_to_event_dict(self) -> None:
        evt = AgentCanvasUpdatedEvent(
            conversation_id="conv-1",
            block_id="b-1",
            action="updated",
            block={"id": "b-1"},
        )
        d = evt.to_event_dict()
        assert d["type"] == "canvas_updated"
        assert d["data"]["conversation_id"] == "conv-1"
        assert d["data"]["block_id"] == "b-1"

    def test_domain_event_frozen(self) -> None:
        evt = AgentCanvasUpdatedEvent(
            conversation_id="conv-1",
            block_id="b-1",
            action="deleted",
        )
        with pytest.raises(Exception):
            evt.action = "created"


# ===========================================================================
# Tools
# ===========================================================================


@pytest.mark.unit
class TestCanvasTools:
    """Test canvas tool functions."""

    def test_configure_and_get_manager(self) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)
        assert get_canvas_manager() is mgr
        # Reset to avoid pollution
        configure_canvas(None)  # reset global

    def test_get_manager_unconfigured(self) -> None:
        configure_canvas(None)  # reset global
        with pytest.raises(RuntimeError, match="Canvas not configured"):
            get_canvas_manager()

    async def test_canvas_create_success(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        result = await canvas_create.execute(
            ctx, block_type="code", title="Script", content="print(1)"
        )
        assert not result.is_error
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["block_type"] == "code"
        assert data["title"] == "Script"
        assert data["version"] == 1

        # Event was emitted
        events = ctx.consume_pending_events()
        assert len(events) == 1
        assert events[0]["type"] == "canvas_updated"
        assert events[0]["data"]["action"] == "created"

        configure_canvas(None)  # reset global

    async def test_canvas_create_invalid_type(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        result = await canvas_create.execute(ctx, block_type="invalid", title="Bad", content="")
        assert result.is_error
        data = json.loads(result.output)
        assert "error" in data

        configure_canvas(None)  # reset global

    async def test_canvas_update_success(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        # Create first
        create_result = await canvas_create.execute(
            ctx, block_type="markdown", title="A", content="old"
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()  # Reset events

        # Update
        result = await canvas_update.execute(ctx, block_id=block_id, content="new")
        assert not result.is_error
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["version"] == 2

        events = ctx.consume_pending_events()
        assert len(events) == 1
        assert events[0]["data"]["action"] == "updated"

        configure_canvas(None)  # reset global

    async def test_canvas_update_not_found(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        result = await canvas_update.execute(ctx, block_id="nonexistent", content="x")
        assert result.is_error

        configure_canvas(None)  # reset global

    async def test_canvas_delete_success(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        create_result = await canvas_create.execute(
            ctx, block_type="table", title="Data", content="[]"
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()  # Reset events

        result = await canvas_delete.execute(ctx, block_id=block_id)
        assert not result.is_error
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["deleted"] is True

        events = ctx.consume_pending_events()
        assert len(events) == 1
        assert events[0]["data"]["action"] == "deleted"
        assert events[0]["data"]["block"] is None

        configure_canvas(None)  # reset global

    async def test_canvas_delete_not_found(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        result = await canvas_delete.execute(ctx, block_id="nonexistent")
        assert result.is_error

        configure_canvas(None)  # reset global

    async def test_canvas_create_with_metadata(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        result = await canvas_create.execute(
            ctx,
            block_type="code",
            title="Script",
            content="x = 1",
            metadata={"language": "python"},
        )
        assert not result.is_error
        data = json.loads(result.output)
        assert data["success"] is True

        # Verify metadata in emitted event
        events = ctx.consume_pending_events()
        event_block = events[0]["data"]["block"]
        assert event_block["metadata"] == {"language": "python"}

        configure_canvas(None)  # reset global
