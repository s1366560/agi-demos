"""A2UI JSONL message builder.

Constructs native A2UI ServerToClientMessage envelopes for the CopilotKit
``@copilotkit/a2ui-renderer`` frontend.  The backend agent emits these messages
as the ``content`` field of an ``a2ui_surface`` CanvasBlock, so the frontend
can call ``processMessages()`` directly.

A2UI message format reference (Google A2UI v0.8):
- ``surfaceUpdate``: ``{"surfaceUpdate":{"surfaceId":"...","components":[...]}}``
- ``dataModelUpdate``: ``{"dataModelUpdate":{"surfaceId":"...","path":"...","contents":[...]}}``
- ``beginRendering``: ``{"beginRendering":{"surfaceId":"...","root":"...","styles":{...}}}``
- ``deleteSurface``: ``{"deleteSurface":{"surfaceId":"..."}}``
"""

from __future__ import annotations

import json
import uuid
from typing import Any


def _new_id() -> str:
    """Generate a compact component ID."""
    return uuid.uuid4().hex[:12]


def _str_val(s: str) -> dict[str, str]:
    """Wrap a string as an A2UI StringValue literal."""
    return {"literal": s}

# ---------------------------------------------------------------------------
# Component helpers
# ---------------------------------------------------------------------------


def text_component(text: str, *, style: dict[str, str] | None = None) -> dict[str, Any]:
    """Build an A2UI ``Text`` component."""
    comp: dict[str, Any] = {
        "id": _new_id(),
        "component": {
            "Text": {"text": _str_val(text), **(({"style": style}) if style else {})},
        },
    }
    return comp


def button_component(
    label: str,
    action_id: str,
    *,
    style: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build an A2UI ``Button`` component with a user-action binding.

    Returns a ``(button, label_text)`` tuple.  The caller **must** include
    both the button dict *and* the label-text dict in the ``surfaceUpdate``
    components list so that the renderer can resolve the child reference.
    """
    label_text = text_component(label)
    props: dict[str, Any] = {
        "child": label_text["id"],
        "action": {"name": action_id},
    }
    if style:
        props["style"] = style
    button = {
        "id": _new_id(),
        "component": {"Button": props},
    }
    return (button, label_text)


def card_component(
    children: list[dict[str, Any]],
    *,
    title: str | None = None,
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build an A2UI ``Card`` wrapper component."""
    child_ids = [c["id"] for c in children]
    props: dict[str, Any] = {}
    if title:
        props["title"] = title
    if style:
        props["style"] = style
    props["children"] = {"explicitList": child_ids}
    return {
        "id": _new_id(),
        "component": {"Card": props},
    }


def column_component(
    children: list[dict[str, Any]],
    *,
    gap: str = "8px",
) -> dict[str, Any]:
    """Build an A2UI ``Column`` layout component."""
    child_ids = [c["id"] for c in children]
    return {
        "id": _new_id(),
        "component": {"Column": {"gap": gap, "children": {"explicitList": child_ids}}},
    }


def row_component(
    children: list[dict[str, Any]],
    *,
    gap: str = "8px",
) -> dict[str, Any]:
    """Build an A2UI ``Row`` layout component."""
    child_ids = [c["id"] for c in children]
    return {
        "id": _new_id(),
        "component": {"Row": {"gap": gap, "children": {"explicitList": child_ids}}},
    }


def text_field_component(
    label: str,
    action_id: str,
    *,
    placeholder: str = "",
    value: str = "",
) -> dict[str, Any]:
    """Build an A2UI ``TextField`` input component."""
    return {
        "id": _new_id(),
        "component": {
            "TextField": {
                "label": _str_val(label),
                "placeholder": placeholder,
                "value": value,
                "onChange": {"name": action_id},
            },
        },
    }


def divider_component() -> dict[str, Any]:
    """Build an A2UI ``Divider`` component."""
    return {
        "id": _new_id(),
        "component": {"Divider": {}},
    }


# ---------------------------------------------------------------------------
# Envelope constructors
# ---------------------------------------------------------------------------


def surface_update(
    surface_id: str,
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a ``surfaceUpdate`` JSONL envelope."""
    return {
        "surfaceUpdate": {
            "surfaceId": surface_id,
            "components": components,
        },
    }


def data_model_update(
    surface_id: str,
    contents: list[dict[str, Any]],
    *,
    path: str = "/",
) -> dict[str, Any]:
    """Build a ``dataModelUpdate`` JSONL envelope."""
    return {
        "dataModelUpdate": {
            "surfaceId": surface_id,
            "path": path,
            "contents": contents,
        },
    }


def begin_rendering(
    surface_id: str,
    root: str,
    *,
    styles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``beginRendering`` JSONL envelope."""
    envelope: dict[str, Any] = {
        "beginRendering": {
            "surfaceId": surface_id,
            "root": root,
        },
    }
    if styles:
        envelope["beginRendering"]["styles"] = styles
    return envelope


def delete_surface(surface_id: str) -> dict[str, Any]:
    """Build a ``deleteSurface`` JSONL envelope."""
    return {
        "deleteSurface": {
            "surfaceId": surface_id,
        },
    }


# ---------------------------------------------------------------------------
# Convenience: pack multiple envelopes into JSONL string
# ---------------------------------------------------------------------------


def pack_messages(messages: list[dict[str, Any]]) -> str:
    """Serialize a list of A2UI message envelopes to a JSONL string.

    Each line is a JSON object. This is the format expected by the
    CopilotKit ``processMessages()`` API.
    """
    return "\n".join(json.dumps(msg, separators=(",", ":")) for msg in messages)
