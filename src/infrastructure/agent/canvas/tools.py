"""Canvas tools for the ReAct agent.

Provides @tool_define-based tools that let the agent create, update,
and delete canvas blocks during conversation. Events are emitted via
ctx.emit() following the standard pending-events pattern.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

from src.infrastructure.agent.canvas.a2ui_builder import (
    canonicalize_a2ui_messages,
    extract_surface_id,
    merge_a2ui_message_stream,
    validate_a2ui_incremental_surface_id,
    validate_a2ui_message_syntax,
    validate_a2ui_messages,
)
from src.infrastructure.agent.canvas.events import build_canvas_event_dict
from src.infrastructure.agent.canvas.manager import CanvasManager
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

_canvas_runtime: ContextVar[CanvasManager | None] = ContextVar(
    f"{__name__}.canvas_runtime",
    default=None,
)


def _prepare_canvas_metadata(
    block_type: str,
    content: str,
    metadata: dict[str, str] | None,
) -> dict[str, str] | None:
    """Attach canonical A2UI metadata and reject drift from the payload."""
    prepared = dict(metadata or {})
    if block_type == "a2ui_surface":
        surface_id = extract_surface_id(content)
        provided_surface_id = prepared.get("surface_id")
        if (
            isinstance(provided_surface_id, str)
            and provided_surface_id.strip()
            and surface_id
            and provided_surface_id != surface_id
        ):
            msg = "metadata.surface_id must match the A2UI content surfaceId"
            raise ValueError(msg)
        if surface_id:
            prepared["surface_id"] = surface_id
    return prepared or None


def _validate_a2ui_content(content: str, *, require_initial_render: bool) -> str:
    """Return canonical A2UI content or raise when it cannot render safely."""
    validation_error = validate_a2ui_messages(
        content, require_initial_render=require_initial_render
    )
    if validation_error is not None:
        raise ValueError(validation_error)
    return canonicalize_a2ui_messages(content)


def _validate_a2ui_syntax(content: str) -> None:
    """Raise when raw A2UI input contains malformed JSON or missing envelopes."""
    validation_error = validate_a2ui_message_syntax(content)
    if validation_error is not None:
        raise ValueError(validation_error)


def _validate_interactive_a2ui_content(
    content: str,
    *,
    require_initial_render: bool,
    previous_content: str | None = None,
) -> str:
    """Return merged content or raise when an interactive surface cannot accept user action."""
    _validate_a2ui_syntax(content)
    previous_surface_id = extract_surface_id(previous_content) if previous_content else None
    if previous_surface_id is not None:
        validation_error = validate_a2ui_incremental_surface_id(
            content,
            expected_surface_id=previous_surface_id,
        )
        if validation_error is not None:
            raise ValueError(validation_error)
    merged_content = merge_a2ui_message_stream(previous_content, content)
    validation_error = validate_a2ui_messages(
        merged_content,
        require_initial_render=require_initial_render,
        require_user_action=True,
    )
    if validation_error is not None:
        raise ValueError(validation_error)
    return merged_content


def get_canvas_manager() -> CanvasManager:
    """Resolve Canvas state from the bound executor or pinned V2 generation."""
    runtime_manager = _canvas_runtime.get()
    if runtime_manager is not None:
        return runtime_manager

    from src.infrastructure.plugins.v2.agent_worker_runtime import (
        current_agent_canvas_manager_v2,
    )

    return current_agent_canvas_manager_v2()


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
                    '3) Optional canonical data binding as its own JSON line: {"dataModelUpdate":{"surfaceId":"<id>","path":"/","contents":[...]}} '
                    'Each component entry MUST use {"id":"<component-id>","component":{"Text|Button|Card|Column|Row|TextField|Divider|Image|CheckBox|MultipleChoice|Radio|Badge|Tabs|Modal|Table|Progress":{...}}} '
                    '— do not emit legacy {"id":"...","type":"Text",...} objects. '
                    "Available canonical components: Text, Button, Card, Column, Row, TextField, Divider, Image, CheckBox, MultipleChoice, Radio, Badge, Tabs, Modal, Table, Progress. "
                    'CRITICAL format: Text text MUST be wrapped: {"Text":{"text":{"literalString":"hello"}}}. '
                    'Button uses child (Text component ID ref) + action: {"Button":{"child":"<text-id>","action":{"name":"..."}}}. '
                    'Authoring sugar: Button may use label instead of child, e.g. {"Button":{"label":{"literalString":"Continue"},"action":{"name":"continue"}}}; it will be hoisted into a synthetic Text child automatically. '
                    'TextField uses data binding: {"TextField":{"label":{"literalString":"Name"},"text":{"path":"/form/name"}}}. '
                    'Image uses a wrapped URL: {"Image":{"url":{"literalString":"https://..."}}}. '
                    'CheckBox uses BooleanValue binding: {"CheckBox":{"label":{"literalString":"Email updates"},"value":{"path":"/form/updates"}}}. '
                    'MultipleChoice uses options + selections.path: {"MultipleChoice":{"description":{"literalString":"Priority"},"options":[{"label":{"literalString":"High"},"value":"high"}],"selections":{"path":"/form/priority"}}}. '
                    'Radio uses scalar value binding: {"Radio":{"description":{"literalString":"Plan"},"options":[{"label":{"literalString":"Starter"},"value":"starter"}],"value":{"path":"/form/plan"}}}. '
                    'Badge uses wrapped text and optional tone: {"Badge":{"text":{"literalString":"Active"},"tone":"success"}}. '
                    'Tabs uses tabItems with title + child ids: {"Tabs":{"tabItems":[{"title":{"literalString":"Overview"},"child":"tab-overview"}]}}. '
                    'Modal uses entryPointChild + contentChild ids: {"Modal":{"entryPointChild":"open-modal","contentChild":"modal-body"}}. '
                    'Table uses columns + rows: {"Table":{"columns":[{"header":{"literalString":"Name"}}],"rows":[{"cells":[{"literalString":"Alice"}]}]}}. '
                    'Progress uses NumberValue bindings: {"Progress":{"label":{"literalString":"Completion"},"value":{"path":"/progress/current"},"max":{"literalNumber":100}}}. '
                    "Tabs.tabItems[].child and Modal.entryPointChild/contentChild must reference component ids defined in the same surface. "
                    "Accepted compatibility aliases: Checkbox -> CheckBox and Select -> MultipleChoice. "
                    "Nested surfaceUpdate.dataModelUpdate is accepted and canonicalized for compatibility, but it is not canonical authoring; emit dataModelUpdate as its own JSON line instead. "
                    "Renderer-only backward-compat payloads such as List may render in history/replay paths but must not be authored. "
                    "Column/Row gap may be a number (treated as px). Card.title may be a string or an inline Text component, which will be hoisted into Card.children. "
                    "TextField default input values can be seeded with a matching dataModelUpdate message. "
                    "MultipleChoice writes an array of selected values to selections.path and does not yet hydrate preselected UI state. "
                    "Radio writes a single selected string to value.path and does hydrate preselected data values. "
                    "Modal open/close and Tabs switching are client-side interactions; interactive surfaces still need at least one reachable Button action. "
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
        if block_type == "a2ui_surface":
            content = _validate_a2ui_content(content, require_initial_render=True)
        prepared_metadata = _prepare_canvas_metadata(block_type, content, metadata)
        block = manager.create_block(
            conversation_id=ctx.conversation_id,
            block_type=block_type,
            title=title,
            content=content,
            metadata=prepared_metadata,
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
    resolved_block_id = block_id
    existing = manager.get_block(ctx.conversation_id, resolved_block_id)

    if existing is None:
        # Fallback: try to find block by surface_id metadata
        resolved_id = _resolve_block_id(manager, ctx.conversation_id, block_id)
        if resolved_id is None:
            return ToolResult(
                output=json.dumps(
                    {"error": f"Canvas block '{block_id}' not found in conversation"}
                ),
                is_error=True,
            )
        resolved_block_id = resolved_id
        existing = manager.get_block(ctx.conversation_id, resolved_block_id)

    if existing is None:
        return ToolResult(
            output=json.dumps({"error": f"Canvas block '{block_id}' not found in conversation"}),
            is_error=True,
        )

    try:
        prepared_metadata = metadata
        if content is not None:
            if existing.block_type.value == "a2ui_surface":
                _validate_a2ui_syntax(content)
                existing_surface_id = existing.metadata.get("surface_id") or extract_surface_id(
                    existing.content
                )
                if isinstance(existing_surface_id, str) and existing_surface_id:
                    validation_error = validate_a2ui_incremental_surface_id(
                        content,
                        expected_surface_id=existing_surface_id,
                    )
                    if validation_error is not None:
                        raise ValueError(validation_error)
                content = merge_a2ui_message_stream(existing.content, content)
                content = _validate_a2ui_content(content, require_initial_render=False)
        if existing.block_type.value == "a2ui_surface":
            effective_content = content if content is not None else existing.content
            prepared_metadata = _prepare_canvas_metadata(
                existing.block_type.value,
                effective_content,
                metadata,
            )

        block = manager.update_block(
            conversation_id=ctx.conversation_id,
            block_id=resolved_block_id,
            content=content,
            title=title,
            metadata=prepared_metadata,
        )
    except (KeyError, ValueError) as exc:
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
        "After the tool resumes with the user's action, update the same surface "
        "to reflect the completed/confirmed state instead of leaving the stale "
        "pre-submit form visible to the user. "
        "After the tool resumes with the user's action, you MUST call "
        "`canvas_update` on the same block_id before sending a final assistant "
        "message, unless you intentionally need to keep the interaction open. "
        "Replace the form with a completed/confirmed state instead of relying "
        "on chat-only narration. "
        "Use this when you need to collect user input or confirmation via a rich UI. "
        "The rendered surface must include at least one reachable Button; "
        "display-only Card/Text layouts should use canvas_create instead. "
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
                    "Same format as canvas_create a2ui_surface content. "
                    "For a new surface, emit JSONL with one envelope per line, in order: "
                    '1) {"beginRendering":{"surfaceId":"<id>","root":"<root-id>"}} '
                    '2) {"surfaceUpdate":{"surfaceId":"<id>","components":[...]}}. '
                    "Do not wrap both envelopes in one markdown block or prose response. "
                    "Canonical authoring emits dataModelUpdate as its own JSON line. Nested surfaceUpdate.dataModelUpdate is accepted and canonicalized for compatibility, but it is not canonical authoring. "
                    'Minimal interactive example: {"beginRendering":{"surfaceId":"confirm-surface","root":"button-1"}}\n'
                    '{"surfaceUpdate":{"surfaceId":"confirm-surface","components":[{"id":"label-1","component":{"Text":{"text":{"literalString":"Confirm"}}}},{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"confirm"}}}}]}} '
                    'Every component entry must use {"id":"...","component":{"Text|Button|Card|Column|Row|TextField|Divider|Image|CheckBox|MultipleChoice|Radio|Badge|Tabs|Modal|Table|Progress":{...}}}. '
                    'Do not use legacy {"type":"Text",...} component objects. '
                    "Compatibility aliases Checkbox -> CheckBox and Select -> MultipleChoice are accepted and canonicalized automatically, but do not author them by default. "
                    "Tabs.tabItems[].child and Modal.entryPointChild/contentChild must reference component ids defined in the same surface. "
                    "Button.label, numeric gap, and inline Card title Text sugar are accepted and canonicalized automatically. "
                    "Interactive surfaces must include at least one reachable Button with action.name."
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
    resolved_block_id = block_id or ""
    existing_block = manager.get_block(ctx.conversation_id, resolved_block_id) if block_id else None
    if existing_block is None and block_id:
        resolved_id = _resolve_block_id(manager, ctx.conversation_id, block_id)
        if resolved_id is not None:
            resolved_block_id = resolved_id
            existing_block = manager.get_block(ctx.conversation_id, resolved_block_id)

    if existing_block is not None and existing_block.block_type.value != "a2ui_surface":
        return ToolResult(
            output=json.dumps(
                {"error": f"Canvas block '{resolved_block_id}' is not an A2UI surface"}
            ),
            is_error=True,
        )

    try:
        persisted_content = _validate_interactive_a2ui_content(
            components,
            require_initial_render=existing_block is None,
            previous_content=existing_block.content if existing_block is not None else None,
        )
        prepared_metadata = _prepare_canvas_metadata(
            "a2ui_surface",
            persisted_content,
            existing_block.metadata if existing_block is not None else None,
        )
        action = "created"
        if existing_block is not None:
            block = manager.update_block(
                conversation_id=ctx.conversation_id,
                block_id=resolved_block_id,
                title=title,
                content=persisted_content,
                metadata=prepared_metadata,
            )
            action = "updated"
        else:
            block = manager.create_block(
                conversation_id=ctx.conversation_id,
                block_type="a2ui_surface",
                title=title,
                content=persisted_content,
                metadata=prepared_metadata,
            )
    except ValueError as exc:
        return ToolResult(output=json.dumps({"error": str(exc)}), is_error=True)
    except KeyError as exc:
        return ToolResult(output=json.dumps({"error": str(exc)}), is_error=True)

    event_dict = build_canvas_event_dict(
        conversation_id=ctx.conversation_id,
        block_id=block.id,
        action=action,
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


@dataclass(frozen=True, kw_only=True, slots=True)
class _BoundCanvasExecutor:
    template: ToolInfo
    manager: CanvasManager

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:  # noqa: ANN401
        token = _canvas_runtime.set(self.manager)
        try:
            return await self.template.execute(ctx, **kwargs)
        finally:
            _canvas_runtime.reset(token)


def make_canvas_tools(*, manager: CanvasManager) -> dict[str, ToolInfo]:
    """Return Canvas ToolInfos bound to one runtime host's shared manager."""
    templates = (
        canvas_create,
        canvas_create_interactive,
        canvas_update,
        canvas_delete,
    )
    return {
        template.name: replace(
            template,
            execute=_BoundCanvasExecutor(template=template, manager=manager),
        )
        for template in templates
    }
