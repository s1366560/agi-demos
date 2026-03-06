"""Canvas tools for the ReAct agent.

Provides @tool_define-based tools that let the agent create, update,
and delete canvas blocks during conversation. Events are emitted via
ctx.emit() following the standard pending-events pattern.
"""

from __future__ import annotations

import json
import logging

from src.infrastructure.agent.canvas.events import build_canvas_event_dict
from src.infrastructure.agent.canvas.manager import CanvasManager
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level DI (same pattern as todo_tools.py)
# ---------------------------------------------------------------------------

_canvas_manager: CanvasManager | None = None


def configure_canvas(manager: CanvasManager) -> None:
    """Inject the shared CanvasManager instance.

    Called during agent initialisation.
    """
    global _canvas_manager
    _canvas_manager = manager


def get_canvas_manager() -> CanvasManager:
    if _canvas_manager is None:
        msg = "Canvas not configured. Call configure_canvas() first."
        raise RuntimeError(msg)
    return _canvas_manager


# ---------------------------------------------------------------------------
# canvas_create
# ---------------------------------------------------------------------------


@tool_define(
    name="canvas_create",
    description=(
        "Create a new canvas block to display rich content in the UI. "
        "PREFERRED: For rich, interactive, or structured content (tables, cards, forms, dashboards, "
        "summaries, lists, data displays), use block_type='a2ui_surface' with A2UI JSONL content. "
        "Other block types: code (syntax-highlighted source code), markdown (formatted text), "
        "table (simple tabular data), chart (data visualisation), form (user input), "
        "image (media), widget (custom component). "
        "Returns the block ID for future updates."
    ),
    parameters={
        "type": "object",
        "properties": {
            "block_type": {
                "type": "string",
                "description": "Type of canvas block. Use 'a2ui_surface' (preferred) for rich interactive content.",
                "enum": [
                    "a2ui_surface",
                    "code",
                    "table",
                    "chart",
                    "form",
                    "image",
                    "markdown",
                    "widget",
                ],
            },
            "title": {
                "type": "string",
                "description": "Title displayed above the block.",
            },
            "content": {
                "type": "string",
                "description": (
                    "Block content. "
                    "For a2ui_surface: A2UI JSONL messages — one JSON object per line. Required messages: "
                    '1) {"beginRendering":{"surfaceId":"<id>","root":"<root-component-id>"}} '
                    '2) {"surfaceUpdate":{"surfaceId":"<id>","components":[...]}} '
                    "Available components: Text, Button, Card, Column, Row, TextField, Divider. "
                    'CRITICAL format: Text text MUST be wrapped: {"Text":{"text":{"literal":"hello"}}}. '
                    'Button uses child (Text component ID ref) + action: {"Button":{"child":"<text-id>","action":{"name":"..."}}}. '
                    'TextField label MUST be wrapped: {"TextField":{"label":{"literal":"Name"},...}}. '
                    "Card title and Column/Row gap are plain strings (not wrapped). "
                    "For code: the source code. For table: JSON array of rows. "
                    "For markdown: the markdown text. For chart: JSON chart specification."
                ),
            },
            "metadata": {
                "type": "object",
                "description": (
                    "Optional metadata (e.g. language for code blocks, column headers for tables)."
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["block_type", "title", "content"],
    },
    permission=None,
    category="canvas",
)
async def canvas_create(
    ctx: ToolContext,
    *,
    block_type: str,
    title: str,
    content: str,
    metadata: dict[str, str] | None = None,
) -> ToolResult:
    """Create a new canvas block."""
    manager = get_canvas_manager()

    try:
        block = manager.create_block(
            conversation_id=ctx.conversation_id,
            block_type=block_type,
            title=title,
            content=content,
            metadata=metadata,
        )
    except ValueError as exc:
        return ToolResult(output=json.dumps({"error": str(exc)}), is_error=True)

    event_dict = build_canvas_event_dict(
        conversation_id=ctx.conversation_id,
        block_id=block.id,
        action="created",
        block=block,
    )
    await ctx.emit(event_dict)

    return ToolResult(
        output=json.dumps(
            {
                "success": True,
                "block_id": block.id,
                "block_type": block.block_type.value,
                "title": block.title,
                "version": block.version,
            }
        ),
        title=f"Canvas: {title}",
    )


def _resolve_block_id(
    manager: CanvasManager,
    conversation_id: str,
    block_id: str,
) -> str | None:
    """Resolve a block_id that may be a surface_id or agent-provided alias.

    The agent may use the surface_id (e.g. 'lunch-vote') passed to
    canvas_create_interactive, rather than the UUID auto-generated by
    CanvasManager.  This helper searches existing blocks by surface_id
    metadata to find the real block UUID.
    """
    blocks = manager.get_blocks(conversation_id)
    logger.debug(
        "_resolve_block_id: searching %d blocks in conv=%s for surface_id=%s",
        len(blocks),
        conversation_id,
        block_id,
    )
    for block in blocks:
        sid = block.metadata.get("surface_id")
        if sid == block_id:
            logger.info(
                "_resolve_block_id: resolved surface_id=%s -> block_id=%s",
                block_id,
                block.id,
            )
            return block.id
    logger.warning(
        "_resolve_block_id: surface_id=%s not found among %d blocks (conv=%s)",
        block_id,
        len(blocks),
        conversation_id,
    )
    return None


# ---------------------------------------------------------------------------
# canvas_update
# ---------------------------------------------------------------------------


@tool_define(
    name="canvas_update",
    description=(
        "Update an existing canvas block's content, title, or metadata. "
        "Provide the block_id returned by canvas_create. "
        "Only the fields you provide will be changed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "block_id": {
                "type": "string",
                "description": "ID of the canvas block to update.",
            },
            "content": {
                "type": "string",
                "description": "New content for the block.",
            },
            "title": {
                "type": "string",
                "description": "New title for the block.",
            },
            "metadata": {
                "type": "object",
                "description": "Metadata fields to merge.",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["block_id"],
    },
    permission=None,
    category="canvas",
)
async def canvas_update(
    ctx: ToolContext,
    *,
    block_id: str,
    content: str | None = None,
    title: str | None = None,
    metadata: dict[str, str] | None = None,
) -> ToolResult:
    """Update an existing canvas block."""
    manager = get_canvas_manager()

    try:
        block = manager.update_block(
            conversation_id=ctx.conversation_id,
            block_id=block_id,
            content=content,
            title=title,
            metadata=metadata,
        )
    except KeyError:
        # Fallback: try to find block by surface_id metadata
        resolved_id = _resolve_block_id(manager, ctx.conversation_id, block_id)
        if resolved_id is None:
            return ToolResult(
                output=json.dumps(
                    {"error": f"Canvas block '{block_id}' not found in conversation"}
                ),
                is_error=True,
            )
        try:
            block = manager.update_block(
                conversation_id=ctx.conversation_id,
                block_id=resolved_id,
                content=content,
                title=title,
                metadata=metadata,
            )
        except KeyError as exc:
            return ToolResult(output=json.dumps({"error": str(exc)}), is_error=True)

    await ctx.emit(
        build_canvas_event_dict(
            conversation_id=ctx.conversation_id,
            block_id=block.id,
            action="updated",
            block=block,
        )
    )

    return ToolResult(
        output=json.dumps(
            {
                "success": True,
                "block_id": block.id,
                "version": block.version,
            }
        ),
        title=f"Canvas updated: {block.title}",
    )


# ---------------------------------------------------------------------------
# canvas_delete
# ---------------------------------------------------------------------------


@tool_define(
    name="canvas_delete",
    description=(
        "Delete a canvas block from the UI. Provide the block_id returned by canvas_create."
    ),
    parameters={
        "type": "object",
        "properties": {
            "block_id": {
                "type": "string",
                "description": "ID of the canvas block to delete.",
            },
        },
        "required": ["block_id"],
    },
    permission=None,
    category="canvas",
)
async def canvas_delete(
    ctx: ToolContext,
    *,
    block_id: str,
) -> ToolResult:
    """Delete a canvas block."""
    manager = get_canvas_manager()

    try:
        manager.delete_block(
            conversation_id=ctx.conversation_id,
            block_id=block_id,
        )
    except KeyError:
        # Fallback: try to find block by surface_id metadata
        resolved_id = _resolve_block_id(manager, ctx.conversation_id, block_id)
        if resolved_id is None:
            return ToolResult(
                output=json.dumps(
                    {"error": f"Canvas block '{block_id}' not found in conversation"}
                ),
                is_error=True,
            )
        try:
            manager.delete_block(
                conversation_id=ctx.conversation_id,
                block_id=resolved_id,
            )
            block_id = resolved_id  # Use resolved ID for event emission
        except KeyError as exc:
            return ToolResult(output=json.dumps({"error": str(exc)}), is_error=True)

    await ctx.emit(
        build_canvas_event_dict(
            conversation_id=ctx.conversation_id,
            block_id=block_id,
            action="deleted",
            block=None,
        )
    )

    return ToolResult(
        output=json.dumps(
            {
                "success": True,
                "block_id": block_id,
                "deleted": True,
            }
        ),
        title="Canvas block deleted",
    )


# ---------------------------------------------------------------------------
# canvas_create_interactive  (HITL tool -- dispatched via processor)
# ---------------------------------------------------------------------------


@tool_define(
    name="canvas_create_interactive",
    description=(
        "Create an interactive A2UI canvas surface and wait for user interaction. "
        "Unlike canvas_create, this tool PAUSES the agent until the user clicks "
        "a button, submits a form, or otherwise interacts with the surface. "
        "Returns the user's action (action_name, source_component_id, context). "
        "Use this when you need to collect user input or confirmation via a rich UI. "
        "Content format: A2UI JSONL — same format as canvas_create with block_type='a2ui_surface'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Title for the interactive surface.",
            },
            "components": {
                "type": "string",
                "description": (
                    "A2UI JSONL messages describing the interactive surface. "
                    "Same format as canvas_create a2ui_surface content."
                ),
            },
            "block_id": {
                "type": "string",
                "description": "Optional block ID to associate with an existing canvas block.",
            },
        },
        "required": ["title", "components"],
    },
    permission=None,
    category="canvas",
)
async def canvas_create_interactive(
    ctx: ToolContext,
    *,
    title: str,
    components: str,
    block_id: str | None = None,
) -> ToolResult:
    """Create an interactive A2UI surface and wait for user action.

    NOTE: This tool is a HITL tool.  The processor intercepts it in
    ``_check_hitl_dispatch`` and delegates to ``handle_a2ui_action_tool``
    before this body executes.  This body only runs if the HITL dispatch
    path is bypassed (e.g. in tests).
    """
    # Create the canvas block so the surface is visible in the UI.
    manager = get_canvas_manager()

    try:
        block = manager.create_block(
            conversation_id=ctx.conversation_id,
            block_type="a2ui_surface",
            title=title,
            content=components,
        )
    except ValueError as exc:
        return ToolResult(output=json.dumps({"error": str(exc)}), is_error=True)

    event_dict = build_canvas_event_dict(
        conversation_id=ctx.conversation_id,
        block_id=block.id,
        action="created",
        block=block,
    )
    await ctx.emit(event_dict)

    return ToolResult(
        output=json.dumps(
            {
                "success": True,
                "block_id": block.id,
                "message": "Interactive surface created. Waiting for user action.",
            }
        ),
        title=f"Interactive Canvas: {title}",
    )
