"""Unit tests for Canvas/A2UI system.

Covers: models, manager, events, and tools with 80%+ coverage target.
"""

from __future__ import annotations

import asyncio
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
    canvas_create_interactive,
    canvas_delete,
    canvas_update,
    configure_canvas,
    get_canvas_manager,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.tests.unit.agent.canvas.a2ui_contract_fixtures import (
    contract_case_jsonl,
    get_a2ui_contract_case,
    iter_backend_contract_cases,
)
from src.tests.unit.agent.canvas.native_block_contract_fixtures import (
    iter_native_block_contract_cases,
    serialize_native_block_content,
)

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

    async def test_bound_canvas_tools_ignore_legacy_manager_changes(self) -> None:
        from src.infrastructure.agent.canvas.tools import make_canvas_tools

        manager_a = CanvasManager()
        manager_b = CanvasManager()
        legacy_manager = CanvasManager()
        tool_a = make_canvas_tools(manager=manager_a)["canvas_create"]
        tool_b = make_canvas_tools(manager=manager_b)["canvas_create"]
        configure_canvas(legacy_manager)

        ctx_a = ToolContext(
            session_id="session-a",
            message_id="message-a",
            call_id="call-a",
            agent_name="agent-a",
            conversation_id="conversation-a",
        )
        ctx_b = ToolContext(
            session_id="session-b",
            message_id="message-b",
            call_id="call-b",
            agent_name="agent-b",
            conversation_id="conversation-b",
        )
        result_a, result_b = await asyncio.gather(
            tool_a.execute(ctx_a, block_type="markdown", title="A", content="alpha"),
            tool_b.execute(ctx_b, block_type="markdown", title="B", content="beta"),
        )

        assert result_a.is_error is False
        assert result_b.is_error is False
        assert [block.title for block in manager_a.get_blocks("conversation-a")] == ["A"]
        assert [block.title for block in manager_b.get_blocks("conversation-b")] == ["B"]
        assert legacy_manager.get_blocks("conversation-a") == []
        assert legacy_manager.get_blocks("conversation-b") == []
        configure_canvas(None)

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

    @pytest.mark.parametrize(
        "case",
        iter_native_block_contract_cases(target="backend"),
        ids=lambda case: str(case["id"]),
    )
    async def test_canvas_native_block_lifecycle_from_shared_contract_cases(
        self, ctx: ToolContext, case: dict[str, object]
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)
        block_type = str(case["blockType"])
        title = str(case["title"])
        updated_title = str(case.get("updatedTitle", f"Updated {title}"))
        initial_content = serialize_native_block_content(case["content"])
        updated_content = serialize_native_block_content(
            case.get("updatedContent", case["content"])
        )

        create_result = await canvas_create.execute(
            ctx,
            block_type=block_type,
            title=title,
            content=initial_content,
        )
        assert not create_result.is_error
        block_id = json.loads(create_result.output)["block_id"]

        create_events = ctx.consume_pending_events()
        assert create_events[0]["data"]["action"] == "created"
        assert create_events[0]["data"]["block"]["block_type"] == block_type

        update_result = await canvas_update.execute(
            ctx,
            block_id=block_id,
            title=updated_title,
            content=updated_content,
        )
        assert not update_result.is_error
        update_data = json.loads(update_result.output)
        assert update_data["version"] == 3

        update_events = ctx.consume_pending_events()
        assert update_events[0]["data"]["action"] == "updated"
        assert update_events[0]["data"]["block"]["title"] == updated_title
        assert update_events[0]["data"]["block"]["content"] == updated_content
        assert update_events[0]["data"]["block"]["version"] == 3

        delete_result = await canvas_delete.execute(ctx, block_id=block_id)
        assert not delete_result.is_error
        delete_data = json.loads(delete_result.output)
        assert delete_data["deleted"] is True

        delete_events = ctx.consume_pending_events()
        assert delete_events[0]["data"]["action"] == "deleted"
        assert delete_events[0]["data"]["block"] is None

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

    async def test_canvas_create_a2ui_infers_surface_id_metadata(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
            ]
        )

        result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=content,
        )
        assert not result.is_error

        events = ctx.consume_pending_events()
        event_block = events[0]["data"]["block"]
        assert event_block["metadata"]["surface_id"] == "surface-42"

        configure_canvas(None)  # reset global

    @pytest.mark.parametrize(
        "case_id",
        [
            case["id"]
            for case in iter_backend_contract_cases()
            if not case.get("shouldReject")
            and isinstance(case.get("identity", {}).get("metadataSurfaceId"), str)
        ],
    )
    async def test_canvas_create_uses_shared_fixture_surface_metadata(
        self,
        ctx: ToolContext,
        case_id: str,
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        case = get_a2ui_contract_case(case_id)
        result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title=case["id"],
            content=contract_case_jsonl(case),
        )

        assert not result.is_error
        events = ctx.consume_pending_events()
        event_block = events[0]["data"]["block"]
        assert event_block["metadata"]["surface_id"] == case["identity"]["metadataSurfaceId"]

        configure_canvas(None)  # reset global

    async def test_canvas_create_rejects_mismatched_a2ui_surface_id_metadata(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
            ]
        )

        result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=content,
            metadata={"surface_id": "wrong-surface"},
        )

        assert result.is_error
        assert "metadata.surface_id must match" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_create_rejects_malformed_a2ui_payload_even_if_partially_parseable(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
                '{"broken":',
                '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literalString":"hello"}}}}]}}',
            ]
        )

        result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=content,
        )

        assert result.is_error
        assert "malformed JSON" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_create_accepts_display_only_card_surface(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-card","root":"card-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-card","components":['
                '{"id":"text-1","component":{"Text":{"text":{"literalString":"Hello"}}}},'
                '{"id":"card-1","component":{"Card":{"title":"Card","children":{"explicitList":["text-1"]}}}}]}}',
            ]
        )

        result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Card Surface",
            content=content,
        )
        assert not result.is_error

        events = ctx.consume_pending_events()
        event_block = events[0]["data"]["block"]
        assert event_block["metadata"]["surface_id"] == "surface-card"
        assert '"Card"' in event_block["content"]

        configure_canvas(None)  # reset global

    async def test_canvas_update_rejects_surface_id_retargeting(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        updated_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-2","root":"root-2"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-2","components":[{"id":"root-2","component":{"Text":{"text":{"literal":"updated"}}}}]}}',
            ]
        )
        result = await canvas_update.execute(ctx, block_id=block_id, content=updated_content)
        assert result.is_error
        assert "must use surfaceId 'surface-1'" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_update_rejects_mismatched_a2ui_surface_id_metadata(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        result = await canvas_update.execute(
            ctx,
            block_id=block_id,
            metadata={"surface_id": "wrong-surface"},
        )

        assert result.is_error
        assert "metadata.surface_id must match" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_update_rejects_malformed_incremental_a2ui_payload(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":[{"id":"root-1","component":{"Text":{"text":{"literalString":"hello"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        invalid_update = "\n".join(
            [
                '{"surfaceUpdate":{"components":[{"id":"root-1","component":{"Text":{"text":{"literalString":"updated"}}}}]}}',
                '{"broken":',
            ]
        )
        result = await canvas_update.execute(ctx, block_id=block_id, content=invalid_update)

        assert result.is_error
        assert "malformed JSON" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_update_a2ui_persists_merged_incremental_snapshot(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        incremental_content = json.dumps(
            {
                "surfaceUpdate": {
                    "surfaceId": "surface-1",
                    "components": [
                        {
                            "id": "root-1",
                            "component": {"Text": {"text": {"literalString": "updated"}}},
                        }
                    ],
                }
            }
        )
        result = await canvas_update.execute(ctx, block_id=block_id, content=incremental_content)
        assert not result.is_error

        events = ctx.consume_pending_events()
        event_block = events[0]["data"]["block"]
        assert '"beginRendering"' in event_block["content"]
        assert '"surfaceId": "surface-1"' in event_block["content"]
        assert '"updated"' in event_block["content"]
        assert event_block["metadata"]["surface_id"] == "surface-1"

        configure_canvas(None)  # reset global

    async def test_canvas_update_accepts_nested_data_model_update_without_explicit_surface_id(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
                '{"id":"label-1","component":{"Text":{"text":{"literalString":"Confirm"}}}},'
                '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"confirm"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        incremental_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"success-card"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","dataModelUpdate":{"path":"/status","value":"success"},"components":['
                '{"id":"success-card","component":{"Text":{"text":{"literalString":"Saved"}}}}]}}',
            ]
        )
        result = await canvas_update.execute(ctx, block_id=block_id, content=incremental_content)

        assert not result.is_error
        events = ctx.consume_pending_events()
        event_block = events[0]["data"]["block"]
        assert '"root": "success-card"' in event_block["content"]
        assert '"path": "/status"' in event_block["content"]
        assert '"value": "success"' in event_block["content"]

        configure_canvas(None)  # reset global

    async def test_canvas_update_rejects_incremental_surface_id_drift(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":[{"id":"root-1","component":{"Text":{"text":{"literalString":"hello"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        drifted_update = json.dumps(
            {
                "surfaceUpdate": {
                    "surfaceId": "surface-2",
                    "components": [
                        {
                            "id": "root-1",
                            "component": {"Text": {"text": {"literalString": "updated"}}},
                        }
                    ],
                }
            }
        )

        result = await canvas_update.execute(ctx, block_id=block_id, content=drifted_update)

        assert result.is_error
        assert "must use surfaceId 'surface-1'" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_update_rejects_incremental_surface_id_drift_before_multi_surface_merge(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        invalid_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-a","root":"root-1"}}',
                '{"beginRendering":{"surfaceId":"surface-b","root":"root-2"}}',
            ]
        )
        result = await canvas_update.execute(ctx, block_id=block_id, content=invalid_content)
        assert result.is_error
        assert "must use surfaceId 'surface-1'" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_reuses_existing_block(self, ctx: ToolContext) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
                '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
                '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        updated_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"button-2"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
                '{"id":"label-2","component":{"Text":{"text":{"literalString":"Updated"}}}},'
                '{"id":"button-2","component":{"Button":{"child":"label-2","action":{"name":"submit"}}}}]}}',
            ]
        )
        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Surface",
            components=updated_content,
            block_id=block_id,
        )
        assert not result.is_error
        assert json.loads(result.output)["block_id"] == block_id

        events = ctx.consume_pending_events()
        assert events[0]["data"]["action"] == "updated"
        assert events[0]["data"]["block_id"] == block_id
        assert [
            json.loads(line) for line in events[0]["data"]["block"]["content"].splitlines()
        ] == [json.loads(line) for line in updated_content.splitlines()]

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_rejects_malformed_payload_even_if_partially_parseable(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}',
                '{"broken":',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
                '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
                '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}',
            ]
        )

        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Surface",
            components=content,
        )

        assert result.is_error
        assert "malformed JSON" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_accepts_card_when_button_is_reachable(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-card","root":"card-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-card","components":['
                '{"id":"title-1","component":{"Text":{"text":{"literalString":"Card title"}}}},'
                '{"id":"button-label","component":{"Text":{"text":{"literalString":"Confirm"}}}},'
                '{"id":"button-1","component":{"Button":{"child":"button-label","action":{"name":"confirm"}}}},'
                '{"id":"card-1","component":{"Card":{"title":"Card","children":{"explicitList":["title-1","button-1","button-label"]}}}}]}}',
            ]
        )

        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Card",
            components=content,
        )

        assert not result.is_error
        events = ctx.consume_pending_events()
        assert events[0]["data"]["action"] == "created"
        assert '"Card"' in events[0]["data"]["block"]["content"]

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_promotes_leaf_root_to_container_root(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-card","root":"confirm-btn"}}',
                '{"dataModelUpdate":{"surfaceId":"surface-card","data":{"form":{"alertsEnabled":false,"priority":"medium"}}}}',
                '{"surfaceUpdate":{"surfaceId":"surface-card","components":['
                '{"id":"card","component":{"Card":{"children":["title","checkbox","priority-select","confirm-btn"]}}},'
                '{"id":"title","component":{"Text":{"text":{"literalString":"Alert Settings"}}}},'
                '{"id":"checkbox","component":{"CheckBox":{"label":{"literalString":"Enable alerts"},"value":{"path":"/form/alertsEnabled"}}}},'
                '{"id":"priority-select","component":{"Select":{"label":{"literalString":"Priority"},"options":[{"label":{"literalString":"High"},"value":"high"},{"label":{"literalString":"Medium"},"value":"medium"},{"label":{"literalString":"Low"},"value":"low"}],"selections":{"path":"/form/priority"}}}},'
                '{"id":"confirm-btn","component":{"Button":{"label":{"literalString":"Confirm"},"action":{"name":"confirm"}}}}]}}',
            ]
        )

        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Card",
            components=content,
        )

        assert not result.is_error
        events = ctx.consume_pending_events()
        stored_content = events[0]["data"]["block"]["content"]
        assert '"root": "card"' in stored_content
        assert '"MultipleChoice"' in stored_content
        assert '"confirm-btn__label"' in stored_content

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_wraps_flat_button_root_in_synthetic_column(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"alert-settings","root":"confirm-btn"}}',
                '{"dataModelUpdate":{"path":"/form/enableAlerts","kind":{"BooleanValue":false}}}',
                '{"dataModelUpdate":{"path":"/form/priority","kind":{"StringValue":"medium"}}}',
                '{"surfaceUpdate":{"surfaceId":"alert-settings","components":['
                '{"id":"title-text","component":{"Text":{"text":{"literalString":"Alert Settings"}}}},'
                '{"id":"enable-checkbox","component":{"CheckBox":{"label":{"literalString":"Enable alerts"},"value":{"path":"/form/enableAlerts"}}}},'
                '{"id":"priority-select","component":{"MultipleChoice":{"description":{"literalString":"Priority"},"options":[{"label":{"literalString":"High"},"value":"high"},{"label":{"literalString":"Medium"},"value":"medium"},{"label":{"literalString":"Low"},"value":"low"}],"selections":{"path":"/form/priority"}}}},'
                '{"id":"confirm-btn","component":{"Button":{"label":{"literalString":"Confirm"},"action":{"name":"confirm"}}}}]}}',
            ]
        )

        result = await canvas_create_interactive.execute(
            ctx,
            title="Alert Settings",
            components=content,
        )

        assert not result.is_error
        events = ctx.consume_pending_events()
        stored_content = events[0]["data"]["block"]["content"]
        assert '"root": "alert-settings__root"' in stored_content
        assert '"id": "alert-settings__root"' in stored_content
        assert '"Column"' in stored_content
        assert (
            '"explicitList": ["title-text", "enable-checkbox", "priority-select", "confirm-btn"]'
            in stored_content
        )

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_normalizes_phase3_syntax_sugar(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-sugar","root":"root-1"}}',
                json.dumps(
                    {
                        "surfaceUpdate": {
                            "surfaceId": "surface-sugar",
                            "components": [
                                {
                                    "id": "root-1",
                                    "component": {
                                        "Column": {
                                            "gap": 16,
                                            "children": {"explicitList": ["card-1", "button-1"]},
                                        }
                                    },
                                },
                                {
                                    "id": "card-1",
                                    "component": {
                                        "Card": {
                                            "title": {
                                                "Text": {
                                                    "text": {"literal": "Card title"},
                                                    "style": {"fontWeight": "700"},
                                                }
                                            },
                                            "children": {"explicitList": ["body-1"]},
                                        }
                                    },
                                },
                                {
                                    "id": "body-1",
                                    "component": {"Text": {"text": {"literalString": "Body copy"}}},
                                },
                                {
                                    "id": "button-1",
                                    "component": {
                                        "Button": {
                                            "label": {"literalString": "Submit"},
                                            "action": {"name": "submit"},
                                        }
                                    },
                                },
                            ],
                        }
                    }
                ),
            ]
        )

        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Sugar Surface",
            components=content,
        )

        assert not result.is_error
        events = ctx.consume_pending_events()
        event_block = events[0]["data"]["block"]
        records = [json.loads(line) for line in event_block["content"].splitlines()]
        surface_update = records[1]["surfaceUpdate"]
        components = {
            component["id"]: component["component"] for component in surface_update["components"]
        }

        assert event_block["metadata"]["surface_id"] == "surface-sugar"
        assert components["root-1"]["Column"]["gap"] == "16px"
        assert components["button-1"]["Button"]["child"] == "button-1__label"
        assert "label" not in components["button-1"]["Button"]
        assert components["button-1__label"]["Text"]["text"]["literalString"] == "Submit"
        assert "title" not in components["card-1"]["Card"]
        assert components["card-1"]["Card"]["children"]["explicitList"] == [
            "card-1__title",
            "body-1",
        ]
        assert components["card-1__title"]["Text"]["text"]["literalString"] == "Card title"
        assert components["card-1__title"]["Text"]["style"]["fontWeight"] == "700"

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_accepts_compound_record_payload(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = json.dumps(
            {
                "beginRendering": {
                    "surfaceId": "surface-compound",
                    "root": "button-1",
                },
                "surfaceUpdate": {
                    "surfaceId": "surface-compound",
                    "dataModelUpdate": {
                        "surfaceId": "surface-compound",
                        "path": "/",
                        "contents": [{"key": "status", "valueString": "pending"}],
                    },
                    "components": [
                        {
                            "id": "label-1",
                            "component": {"Text": {"text": {"literal": "Approve"}}},
                        },
                        {
                            "id": "button-1",
                            "component": {
                                "Button": {
                                    "label": {"literalString": "Approve"},
                                    "action": {"name": "submit"},
                                }
                            },
                        },
                    ],
                },
            }
        )

        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Compound Surface",
            components=content,
        )

        assert not result.is_error
        events = ctx.consume_pending_events()
        records = [json.loads(line) for line in events[0]["data"]["block"]["content"].splitlines()]
        assert [next(iter(record)) for record in records] == [
            "beginRendering",
            "surfaceUpdate",
            "dataModelUpdate",
        ]

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_accepts_python_bool_json_like_payload(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = """
        {
          "beginRendering": {"surfaceId": "surface-python-bool", "root": "button-1"},
          "surfaceUpdate": {
            "surfaceId": "surface-python-bool",
            "dataModelUpdate": {"surfaceId": "surface-python-bool", "path": "/form", "data": {"alerts": False}},
            "components": [
              {"id": "label-1", "component": {"Text": {"text": {"literalString": "Approve"}}}},
              {"id": "button-1", "component": {"Button": {"label": {"literalString": "Approve"}, "action": {"name": "submit"}}}}
            ]
          }
        }
        """

        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Python Bool Surface",
            components=content,
        )

        assert not result.is_error
        events = ctx.consume_pending_events()
        assert events[0]["data"]["action"] == "created"

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_accepts_prose_wrapped_jsonl_payload(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        content = "\n".join(
            [
                "Here is the A2UI surface you requested:",
                '{"beginRendering":{"surfaceId":"surface-prose","root":"button-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-prose","components":['
                '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
                '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}',
                "Please wait for user interaction.",
            ]
        )

        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Prose Surface",
            components=content,
        )

        assert not result.is_error
        events = ctx.consume_pending_events()
        assert events[0]["data"]["block"]["metadata"]["surface_id"] == "surface-prose"

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_rejects_non_actionable_existing_update(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
                '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
                '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        invalid_update = json.dumps(
            {
                "surfaceUpdate": {
                    "surfaceId": "surface-1",
                    "components": [
                        {
                            "id": "button-1",
                            "component": {"Text": {"text": {"literalString": "Updated"}}},
                        }
                    ],
                }
            }
        )
        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Surface",
            components=invalid_update,
            block_id=block_id,
        )

        assert result.is_error
        assert "interactive updates must still resolve" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_rejects_existing_update_with_drifted_surface_id(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
                '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
                '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        drifted_update = json.dumps(
            {
                "surfaceUpdate": {
                    "surfaceId": "surface-2",
                    "components": [
                        {
                            "id": "label-2",
                            "component": {"Text": {"text": {"literalString": "Updated"}}},
                        },
                        {
                            "id": "button-2",
                            "component": {
                                "Button": {"child": "label-2", "action": {"name": "submit"}}
                            },
                        },
                    ],
                }
            }
        )
        result = await canvas_create_interactive.execute(
            ctx,
            title="Interactive Surface",
            components=drifted_update,
            block_id=block_id,
        )

        assert result.is_error
        assert "must use surfaceId 'surface-1'" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_create_interactive_rejects_flat_surface_object(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        result = await canvas_create_interactive.execute(
            ctx,
            title="Invalid Surface",
            components=json.dumps(
                {
                    "surfaceId": "surface-1",
                    "components": [
                        {
                            "id": "root-1",
                            "component": {"Text": {"text": {"literal": "hello"}}},
                        }
                    ],
                }
            ),
        )

        assert result.is_error
        assert "beginRendering/surfaceUpdate envelopes" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global

    async def test_canvas_update_invalid_a2ui_payload_returns_tool_error(
        self, ctx: ToolContext
    ) -> None:
        mgr = CanvasManager()
        configure_canvas(mgr)

        initial_content = "\n".join(
            [
                '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
                '{"surfaceUpdate":{"surfaceId":"surface-1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
            ]
        )
        create_result = await canvas_create.execute(
            ctx,
            block_type="a2ui_surface",
            title="Interactive Surface",
            content=initial_content,
        )
        block_id = json.loads(create_result.output)["block_id"]
        ctx.consume_pending_events()

        result = await canvas_update.execute(
            ctx,
            block_id=block_id,
            content=json.dumps(
                {
                    "surfaceId": "surface-1",
                    "components": [
                        {
                            "id": "root-1",
                            "component": {"Text": {"text": {"literal": "hello"}}},
                        }
                    ],
                }
            ),
        )

        assert result.is_error
        assert "beginRendering/surfaceUpdate envelopes" in result.output
        assert ctx.consume_pending_events() == []

        configure_canvas(None)  # reset global
