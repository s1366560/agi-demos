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

import ast
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, TypeGuard


def _new_id() -> str:
    """Generate a compact component ID."""
    return uuid.uuid4().hex[:12]


def _str_val(s: str) -> dict[str, str]:
    """Wrap a string as an A2UI StringValue literal."""
    return {"literalString": s}


SURFACE_KEYS = (
    "beginRendering",
    "begin_rendering",
    "surfaceUpdate",
    "surface_update",
    "dataModelUpdate",
    "data_model_update",
    "deleteSurface",
    "delete_surface",
)
TYPED_SURFACE_TYPES = set(SURFACE_KEYS)
SUPPORTED_A2UI_COMPONENT_KEYS = frozenset(
    {
        "Text",
        "Button",
        "Card",
        "Column",
        "Row",
        "TextField",
        "Divider",
        "Image",
        "CheckBox",
        "Checkbox",
        "MultipleChoice",
        "Select",
        "Radio",
        "Badge",
        "Tabs",
        "Modal",
        "Table",
        "Progress",
    }
)
COMPONENT_KEY_ALIASES = {
    "Checkbox": "CheckBox",
    "Select": "MultipleChoice",
}
INITIAL_A2UI_SURFACE_EXAMPLE = (
    '{"beginRendering":{"surfaceId":"<id>","root":"<root-component-id>"}}\n'
    '{"surfaceUpdate":{"surfaceId":"<id>","components":[{"id":"<root-component-id>",'
    '"component":{"Text":{"text":{"literalString":"hello"}}}}]}}'
)


@dataclass
class _A2UIMessageStreamState:
    """Normalized surface state for replay-safe incremental merges."""

    surface_id: str | None = None
    root: str | None = None
    styles: dict[str, object] | None = None
    components_by_id: dict[str, dict[str, object]] = field(default_factory=dict)
    data_records: list[dict[str, object]] = field(default_factory=list)


def _is_non_empty_string(value: object) -> bool:
    """Return True when value is a non-empty string."""
    return isinstance(value, str) and bool(value.strip())


def _is_string_literal(value: object) -> bool:
    """Return True when value is a string literal, including empty strings."""
    return isinstance(value, str)


JSONObject = dict[str, object]


def _is_plain_object(value: object) -> TypeGuard[JSONObject]:
    """Return True when value is a JSON-like object."""
    return isinstance(value, dict)


def _validate_string_value(
    value: object,
    *,
    field_path: str,
    allow_path: bool = True,
) -> str | None:
    """Validate an A2UI StringValue object with legacy literal compatibility."""
    if not _is_plain_object(value):
        allowed = "literalString or literal"
        if allow_path:
            allowed = f"{allowed} or path"
        return _invalid_a2ui_payload(f"{field_path} must be an object containing {allowed}.")

    if _is_string_literal(value.get("literalString")):
        return None
    if _is_string_literal(value.get("literal")):
        return None
    if allow_path and _is_non_empty_string(value.get("path")):
        return None

    allowed = "literalString or literal"
    if allow_path:
        allowed = f"{allowed} or path"
    return _invalid_a2ui_payload(f"{field_path} must contain {allowed}.")


def _validate_boolean_value(
    value: object,
    *,
    field_path: str,
    allow_path: bool = True,
) -> str | None:
    """Validate an A2UI BooleanValue object with legacy literal compatibility."""
    if not _is_plain_object(value):
        allowed = "literalBoolean or literal"
        if allow_path:
            allowed = f"{allowed} or path"
        return _invalid_a2ui_payload(f"{field_path} must be an object containing {allowed}.")

    if isinstance(value.get("literalBoolean"), bool):
        return None
    if isinstance(value.get("literal"), bool):
        return None
    if allow_path and _is_non_empty_string(value.get("path")):
        return None

    allowed = "literalBoolean or literal"
    if allow_path:
        allowed = f"{allowed} or path"
    return _invalid_a2ui_payload(f"{field_path} must contain {allowed}.")


def _validate_number_value(
    value: object,
    *,
    field_path: str,
    allow_path: bool = True,
) -> str | None:
    """Validate an A2UI NumberValue object with legacy literal compatibility."""
    if not _is_plain_object(value):
        allowed = "literalNumber or literal"
        if allow_path:
            allowed = f"{allowed} or path"
        return _invalid_a2ui_payload(f"{field_path} must be an object containing {allowed}.")

    literal_number = value.get("literalNumber")
    if isinstance(literal_number, (int, float)) and not isinstance(literal_number, bool):
        return None
    literal = value.get("literal")
    if isinstance(literal, (int, float)) and not isinstance(literal, bool):
        return None
    if allow_path and _is_non_empty_string(value.get("path")):
        return None

    allowed = "literalNumber or literal"
    if allow_path:
        allowed = f"{allowed} or path"
    return _invalid_a2ui_payload(f"{field_path} must contain {allowed}.")


def _validate_children_ref(
    value: object,
    *,
    field_path: str,
) -> str | None:
    """Validate explicit child reference lists."""
    if isinstance(value, list):
        if all(_is_non_empty_string(item) for item in value):
            return None
        return _invalid_a2ui_payload(f"{field_path} must only contain non-empty string ids.")

    if not _is_plain_object(value):
        return _invalid_a2ui_payload(
            f"{field_path} must be an object with explicitList or a list of component ids."
        )

    explicit_list = value.get("explicitList")
    if not isinstance(explicit_list, list):
        return _invalid_a2ui_payload(f"{field_path}.explicitList must be an array.")
    if not all(_is_non_empty_string(item) for item in explicit_list):
        return _invalid_a2ui_payload(f"{field_path}.explicitList must only contain component ids.")
    return None


def _validate_text_component_payload(
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a Text component payload."""
    return _validate_inline_string_value(payload.get("text"), field_path=f"{field_path}.text")


def _validate_button_component_payload(
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a Button component payload."""
    if not _is_non_empty_string(payload.get("child")):
        return _invalid_a2ui_payload(f"{field_path}.child must be a non-empty string id.")

    action = payload.get("action")
    if isinstance(action, str) and action.strip():
        return None
    if not _is_plain_object(action):
        return _invalid_a2ui_payload(
            f"{field_path}.action must be a non-empty string or an object with name/actionId."
        )
    if _is_non_empty_string(action.get("name")) or _is_non_empty_string(action.get("actionId")):
        return None
    return _invalid_a2ui_payload(f"{field_path}.action must contain a non-empty name or actionId.")


def _button_action_name(payload: dict[str, object]) -> str | None:
    """Return the normalized action name for a Button payload."""
    action = payload.get("action")
    if isinstance(action, str) and action.strip():
        return action.strip()
    if not isinstance(action, dict):
        return None

    name = action.get("name")
    if _is_non_empty_string(name):
        return str(name).strip()
    action_id = action.get("actionId")
    if _is_non_empty_string(action_id):
        return str(action_id).strip()
    return None


def _validate_layout_component_payload(
    payload: dict[str, object],
    *,
    component_key: str,
    field_path: str,
) -> str | None:
    """Validate Card/Column/Row component payloads."""
    if error := _validate_children_ref(
        payload.get("children"), field_path=f"{field_path}.children"
    ):
        return error

    gap = payload.get("gap")
    if gap is not None and _normalize_gap_payload(gap) is None:
        return _invalid_a2ui_payload(
            f"{field_path}.gap must be a non-empty string or number when provided."
        )

    if component_key == "Card":
        title = payload.get("title")
        if title is not None and not _is_non_empty_string(title):
            normalized_title_payload = _normalize_inline_text_component_payload(title)
            if normalized_title_payload is None:
                return _invalid_a2ui_payload(
                    f"{field_path}.title must be a non-empty string or an inline Text component."
                )
            if error := _validate_text_component_payload(
                normalized_title_payload,
                field_path=f"{field_path}.title",
            ):
                return error
    return None


def _validate_text_field_component_payload(
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a TextField component payload."""
    if error := _validate_inline_string_value(
        payload.get("label"), field_path=f"{field_path}.label"
    ):
        return error
    if error := _validate_inline_string_value(payload.get("text"), field_path=f"{field_path}.text"):
        return error
    return None


def _validate_image_component_payload(
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate an Image component payload."""
    if error := _validate_inline_string_value(payload.get("url"), field_path=f"{field_path}.url"):
        return error
    fit = payload.get("fit")
    if fit is not None and not _is_non_empty_string(fit):
        return _invalid_a2ui_payload(f"{field_path}.fit must be a non-empty string when provided.")
    usage_hint = payload.get("usageHint")
    if usage_hint is not None and not _is_non_empty_string(usage_hint):
        return _invalid_a2ui_payload(
            f"{field_path}.usageHint must be a non-empty string when provided."
        )
    return None


def _validate_checkbox_component_payload(
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a CheckBox component payload."""
    if error := _validate_inline_string_value(
        payload.get("label"), field_path=f"{field_path}.label"
    ):
        return error
    if error := _validate_inline_boolean_value(
        payload.get("value"), field_path=f"{field_path}.value"
    ):
        return error
    return None


def _validate_multiple_choice_component_payload(  # noqa: PLR0911
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a MultipleChoice component payload."""
    description = payload.get("description")
    if description is not None and (
        error := _validate_inline_string_value(description, field_path=f"{field_path}.description")
    ):
        return error

    options = payload.get("options")
    if not isinstance(options, list) or not options:
        return _invalid_a2ui_payload(f"{field_path}.options must be a non-empty array.")

    for option_index, option in enumerate(options):
        if not _is_plain_object(option):
            return _invalid_a2ui_payload(
                f"{field_path}.options[{option_index}] must be an object with label and value."
            )
        if error := _validate_inline_string_value(
            option.get("label"),
            field_path=f"{field_path}.options[{option_index}].label",
        ):
            return error
        if not _is_non_empty_string(option.get("value")):
            return _invalid_a2ui_payload(
                f"{field_path}.options[{option_index}].value must be a non-empty string."
            )

    selections = payload.get("selections")
    if not _is_plain_object(selections) or not _is_non_empty_string(selections.get("path")):
        return _invalid_a2ui_payload(f"{field_path}.selections.path must be a non-empty string.")
    return None


def _validate_radio_component_payload(  # noqa: PLR0911
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a Radio component payload."""
    description = payload.get("description")
    if description is not None and (
        error := _validate_inline_string_value(description, field_path=f"{field_path}.description")
    ):
        return error

    options = payload.get("options")
    if not isinstance(options, list) or not options:
        return _invalid_a2ui_payload(f"{field_path}.options must be a non-empty array.")

    for option_index, option in enumerate(options):
        if not _is_plain_object(option):
            return _invalid_a2ui_payload(
                f"{field_path}.options[{option_index}] must be an object with label and value."
            )
        if error := _validate_inline_string_value(
            option.get("label"),
            field_path=f"{field_path}.options[{option_index}].label",
        ):
            return error
        if not _is_non_empty_string(option.get("value")):
            return _invalid_a2ui_payload(
                f"{field_path}.options[{option_index}].value must be a non-empty string."
            )

    value = payload.get("value")
    selection = payload.get("selection")
    selections = payload.get("selections")
    if value is not None:
        return _validate_inline_string_value(value, field_path=f"{field_path}.value")
    if selection is not None:
        return _validate_inline_string_value(selection, field_path=f"{field_path}.selection")
    if _is_plain_object(selections) and _is_non_empty_string(selections.get("path")):
        return None
    return _invalid_a2ui_payload(
        f"{field_path}.value must contain literalString or path, or selections.path must be set."
    )


def _validate_badge_component_payload(
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a Badge component payload."""
    if error := _validate_inline_string_value(payload.get("text"), field_path=f"{field_path}.text"):
        return error
    tone = payload.get("tone")
    if tone is not None and not _is_non_empty_string(tone):
        return _invalid_a2ui_payload(f"{field_path}.tone must be a non-empty string when provided.")
    return None


def _validate_component_ref(value: object, *, field_path: str) -> str | None:
    """Validate a single component-id reference."""
    if _is_non_empty_string(value):
        return None
    return _invalid_a2ui_payload(f"{field_path} must be a non-empty string component id.")


def _validate_inline_string_value(value: object, *, field_path: str) -> str | None:
    """Validate a raw string or A2UI StringValue."""
    if _is_string_literal(value):
        return None
    return _validate_string_value(value, field_path=field_path)


def _validate_inline_number_value(value: object, *, field_path: str) -> str | None:
    """Validate a raw number or A2UI NumberValue."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None
    return _validate_number_value(value, field_path=field_path)


def _validate_inline_boolean_value(value: object, *, field_path: str) -> str | None:
    """Validate a raw boolean or A2UI BooleanValue."""
    if isinstance(value, bool):
        return None
    return _validate_boolean_value(value, field_path=field_path)


def _validate_scalar_or_path_value(value: object, *, field_path: str) -> str | None:  # noqa: PLR0911
    """Validate a table cell value."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None
    if _is_non_empty_string(value):
        return None
    if not _is_plain_object(value):
        return _invalid_a2ui_payload(
            f"{field_path} must be a string, number, boolean, or object with a literal/path."
        )

    if _is_non_empty_string(value.get("path")):
        return None
    if _is_non_empty_string(value.get("literalString")):
        return None
    literal_number = value.get("literalNumber")
    if isinstance(literal_number, (int, float)) and not isinstance(literal_number, bool):
        return None
    if isinstance(value.get("literalBoolean"), bool):
        return None
    literal = value.get("literal")
    if isinstance(literal, bool):
        return None
    if isinstance(literal, (int, float)) and not isinstance(literal, bool):
        return None
    if _is_non_empty_string(literal):
        return None
    return _invalid_a2ui_payload(
        f"{field_path} must be a string, number, boolean, or object with a literal/path."
    )


def _validate_tabs_component_payload(
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a Tabs component payload."""
    tab_items = payload.get("tabItems")
    if not isinstance(tab_items, list) or not tab_items:
        return _invalid_a2ui_payload(f"{field_path}.tabItems must be a non-empty array.")

    for item_index, item in enumerate(tab_items):
        if not _is_plain_object(item):
            return _invalid_a2ui_payload(
                f"{field_path}.tabItems[{item_index}] must be an object with title and child."
            )
        if error := _validate_inline_string_value(
            item.get("title"),
            field_path=f"{field_path}.tabItems[{item_index}].title",
        ):
            return error
        if error := _validate_component_ref(
            item.get("child"),
            field_path=f"{field_path}.tabItems[{item_index}].child",
        ):
            return error
    return None


def _validate_modal_component_payload(
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a Modal component payload."""
    if error := _validate_component_ref(
        payload.get("entryPointChild"),
        field_path=f"{field_path}.entryPointChild",
    ):
        return error
    return _validate_component_ref(
        payload.get("contentChild"),
        field_path=f"{field_path}.contentChild",
    )


def _validate_table_component_payload(  # noqa: C901, PLR0911, PLR0912
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a Table component payload."""
    columns = payload.get("columns")
    if not isinstance(columns, list) or not columns:
        return _invalid_a2ui_payload(f"{field_path}.columns must be a non-empty array.")
    for column_index, column in enumerate(columns):
        if _is_non_empty_string(column):
            continue
        if not _is_plain_object(column):
            return _invalid_a2ui_payload(
                f"{field_path}.columns[{column_index}] must be a string or object."
            )
        if error := _validate_inline_string_value(
            column.get("header"),
            field_path=f"{field_path}.columns[{column_index}].header",
        ):
            return error
        align = column.get("align")
        if align is not None and align not in {"left", "center", "right"}:
            return _invalid_a2ui_payload(
                f"{field_path}.columns[{column_index}].align must be left, center, or right."
            )

    rows = payload.get("rows")
    if not isinstance(rows, list):
        return _invalid_a2ui_payload(f"{field_path}.rows must be an array.")
    for row_index, row in enumerate(rows):
        cells = row
        if _is_plain_object(row):
            cells = row.get("cells")
        if not isinstance(cells, list):
            return _invalid_a2ui_payload(
                f"{field_path}.rows[{row_index}] must be an array or object with cells."
            )
        for cell_index, cell in enumerate(cells):
            if error := _validate_scalar_or_path_value(
                cell,
                field_path=f"{field_path}.rows[{row_index}].cells[{cell_index}]",
            ):
                return error

    caption = payload.get("caption")
    if caption is not None and (
        error := _validate_inline_string_value(caption, field_path=f"{field_path}.caption")
    ):
        return error
    empty_text = payload.get("emptyText")
    if empty_text is not None and (
        error := _validate_inline_string_value(empty_text, field_path=f"{field_path}.emptyText")
    ):
        return error
    return None


def _validate_progress_component_payload(
    payload: dict[str, object],
    *,
    field_path: str,
) -> str | None:
    """Validate a Progress component payload."""
    if error := _validate_inline_number_value(
        payload.get("value"), field_path=f"{field_path}.value"
    ):
        return error
    max_value = payload.get("max")
    if max_value is not None and (
        error := _validate_inline_number_value(max_value, field_path=f"{field_path}.max")
    ):
        return error
    label = payload.get("label")
    if label is not None and (
        error := _validate_inline_string_value(label, field_path=f"{field_path}.label")
    ):
        return error
    tone = payload.get("tone")
    if tone is not None and not _is_non_empty_string(tone):
        return _invalid_a2ui_payload(f"{field_path}.tone must be a non-empty string when provided.")
    show_value = payload.get("showValue")
    if show_value is not None and not isinstance(show_value, bool):
        return _invalid_a2ui_payload(f"{field_path}.showValue must be a boolean when provided.")
    return None


def _canonicalize_component_key(component_key: str) -> str:
    """Map supported aliases onto the renderer's canonical component keys."""
    return COMPONENT_KEY_ALIASES.get(component_key, component_key)


def _component_payload_from_entry(
    component: dict[str, object],
    *,
    index: int,
) -> tuple[str, dict[str, object], str | None]:
    """Extract the supported component key and payload from an entry."""
    component_payload = component.get("component")
    if not isinstance(component_payload, dict):
        return (
            "",
            {},
            _invalid_a2ui_payload(
                f"surfaceUpdate.components[{index}] must include a supported 'component' object."
            ),
        )

    component_keys = [key for key in component_payload if key in SUPPORTED_A2UI_COMPONENT_KEYS]
    allowed_keys = SUPPORTED_A2UI_COMPONENT_KEYS | {"style"}
    extra_keys = [key for key in component_payload if key not in allowed_keys]
    if extra_keys:
        return (
            "",
            {},
            _invalid_a2ui_payload(
                f"surfaceUpdate.components[{index}] contains unsupported component keys: "
                f"{sorted(extra_keys)}."
            ),
        )
    if len(component_keys) != 1:
        return (
            "",
            {},
            _invalid_a2ui_payload(
                f"surfaceUpdate.components[{index}] must contain exactly one supported "
                f"component key: {sorted(SUPPORTED_A2UI_COMPONENT_KEYS)}."
            ),
        )

    component_key = _canonicalize_component_key(component_keys[0])
    payload = component_payload.get(component_key)
    if not isinstance(payload, dict):
        original_key = component_keys[0]
        payload = component_payload.get(original_key)
    if not isinstance(payload, dict):
        return (
            "",
            {},
            _invalid_a2ui_payload(
                f"surfaceUpdate.components[{index}].component.{component_key} must be an object."
            ),
        )
    return component_key, payload, None


def _is_actionable_button(component: object) -> bool:
    """Return True when a component represents a dispatchable Button."""
    if not isinstance(component, dict):
        return False
    _component_key, payload, error = _component_payload_from_entry(component, index=-1)
    if error is not None:
        return False
    if _component_key != "Button":
        return False

    return _is_non_empty_string(payload.get("child")) and _button_action_name(payload) is not None


def _is_renderable_button(
    component: dict[str, object],
    components_by_id: dict[str, dict[str, object]],
) -> bool:
    """Return True when a Button points at an existing Text child."""
    component_key, payload, error = _component_payload_from_entry(component, index=-1)
    if error is not None or component_key != "Button":
        return False
    if not _is_non_empty_string(payload.get("child")) or _button_action_name(payload) is None:
        return False

    child_component = components_by_id.get(str(payload["child"]))
    if child_component is None:
        return False
    child_key, _child_payload, child_error = _component_payload_from_entry(
        child_component, index=-1
    )
    return child_error is None and child_key == "Text"


def _normalize_data_path(path_or_alias: str) -> str:
    """Normalize an A2UI data binding path."""
    stripped = path_or_alias.strip()
    if not stripped:
        return "/"
    if stripped.startswith("/"):
        return stripped
    return f"/{stripped.lstrip('/')}"


def _is_value_map(entry: object) -> bool:
    """Return True when an entry already matches A2UI ValueMap shape."""
    if not isinstance(entry, dict):
        return False
    return isinstance(entry.get("key"), str) and (
        len(entry) == 1
        or any(name in entry for name in ("valueString", "valueNumber", "valueBoolean", "valueMap"))
    )


def _to_value_map(key: str, value: object) -> dict[str, object]:
    """Convert a Python value into an A2UI ValueMap entry."""
    if value is None:
        return {"key": key}
    if isinstance(value, bool):
        return {"key": key, "valueBoolean": value}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"key": key, "valueNumber": value}
    if isinstance(value, dict):
        return {
            "key": key,
            "valueMap": [
                _to_value_map(child_key, child_value) for child_key, child_value in value.items()
            ],
        }
    if isinstance(value, list):
        return {
            "key": key,
            "valueMap": [_to_value_map(str(index), item) for index, item in enumerate(value)],
        }
    return {"key": key, "valueString": str(value)}


def _normalize_data_model_contents(contents: object) -> list[dict[str, object]]:
    """Normalize plain objects into A2UI ValueMap entries."""
    if isinstance(contents, dict):
        return [_to_value_map(key, value) for key, value in contents.items()]
    if isinstance(contents, list):
        return [
            entry if _is_value_map(entry) else _to_value_map(str(index), entry)
            for index, entry in enumerate(contents)
        ]
    return [_to_value_map(".", contents)]


def _normalize_inline_string_payload(value: object) -> dict[str, object] | None:
    """Normalize a raw string or StringValue-like object into canonical StringValue."""
    if _is_string_literal(value):
        return {"literalString": str(value)}
    if not isinstance(value, dict):
        return None

    normalized: dict[str, object] = {}
    literal_string = value.get("literalString")
    if _is_string_literal(literal_string):
        normalized["literalString"] = str(literal_string)
    else:
        literal = value.get("literal")
        if _is_string_literal(literal):
            normalized["literalString"] = str(literal)

    path = value.get("path")
    if _is_non_empty_string(path):
        normalized["path"] = _normalize_data_path(str(path))
    return normalized or None


def _normalize_boolean_value_payload(value: object) -> dict[str, object] | None:
    """Normalize a BooleanValue-like object into canonical literalBoolean/path form."""
    if isinstance(value, bool):
        return {"literalBoolean": value}
    if not isinstance(value, dict):
        return None

    normalized: dict[str, object] = {}
    literal_boolean = value.get("literalBoolean")
    if isinstance(literal_boolean, bool):
        normalized["literalBoolean"] = literal_boolean
    else:
        literal = value.get("literal")
        if isinstance(literal, bool):
            normalized["literalBoolean"] = literal

    path = value.get("path")
    if _is_non_empty_string(path):
        normalized["path"] = _normalize_data_path(str(path))
    return normalized or None


def _normalize_number_value_payload(value: object) -> dict[str, object] | None:
    """Normalize a NumberValue-like object into canonical literalNumber/path form."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"literalNumber": value}
    if not isinstance(value, dict):
        return None

    normalized: dict[str, object] = {}
    literal_number = value.get("literalNumber")
    if isinstance(literal_number, (int, float)) and not isinstance(literal_number, bool):
        normalized["literalNumber"] = literal_number
    else:
        literal = value.get("literal")
        if isinstance(literal, (int, float)) and not isinstance(literal, bool):
            normalized["literalNumber"] = literal

    path = value.get("path")
    if _is_non_empty_string(path):
        normalized["path"] = _normalize_data_path(str(path))
    return normalized or None


def _normalize_component_options(options: object) -> object:
    """Normalize MultipleChoice/Radio option labels onto canonical StringValues."""
    if not isinstance(options, list):
        return options

    normalized_options: list[object] = []
    for option in options:
        if not isinstance(option, dict):
            normalized_options.append(option)
            continue
        normalized_option = dict(option)
        label = _normalize_inline_string_payload(option.get("label"))
        if label is not None:
            normalized_option["label"] = label
        normalized_options.append(normalized_option)
    return normalized_options


def _canonicalize_component_payload_values(  # noqa: C901, PLR0911, PLR0912, PLR0915
    component_key: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Normalize component payload leaves onto canonical value shapes."""
    normalized_payload = dict(payload)

    if component_key == "Text":
        text = _normalize_inline_string_payload(normalized_payload.get("text"))
        if text is not None:
            normalized_payload["text"] = text
        return normalized_payload

    if component_key == "TextField":
        label = _normalize_inline_string_payload(normalized_payload.get("label"))
        if label is not None:
            normalized_payload["label"] = label
        text = _normalize_inline_string_payload(normalized_payload.get("text"))
        if text is not None:
            normalized_payload["text"] = text
        return normalized_payload

    if component_key == "Image":
        url = _normalize_inline_string_payload(normalized_payload.get("url"))
        if url is not None:
            normalized_payload["url"] = url
        return normalized_payload

    if component_key == "CheckBox":
        label = _normalize_inline_string_payload(normalized_payload.get("label"))
        if label is not None:
            normalized_payload["label"] = label
        value = _normalize_boolean_value_payload(normalized_payload.get("value"))
        if value is not None:
            normalized_payload["value"] = value
        return normalized_payload

    if component_key == "MultipleChoice":
        description = _normalize_inline_string_payload(normalized_payload.get("description"))
        if description is not None:
            normalized_payload["description"] = description
        normalized_payload["options"] = _normalize_component_options(
            normalized_payload.get("options")
        )
        selections = normalized_payload.get("selections")
        if isinstance(selections, dict) and _is_non_empty_string(selections.get("path")):
            normalized_payload["selections"] = {
                **selections,
                "path": _normalize_data_path(str(selections["path"])),
            }
        return normalized_payload

    if component_key == "Radio":
        description = _normalize_inline_string_payload(normalized_payload.get("description"))
        if description is not None:
            normalized_payload["description"] = description
        normalized_payload["options"] = _normalize_component_options(
            normalized_payload.get("options")
        )
        value = _normalize_inline_string_payload(normalized_payload.get("value"))
        if value is not None:
            normalized_payload["value"] = value
        selection = _normalize_inline_string_payload(normalized_payload.get("selection"))
        if selection is not None:
            normalized_payload["selection"] = selection
        selections = normalized_payload.get("selections")
        if isinstance(selections, dict) and _is_non_empty_string(selections.get("path")):
            normalized_payload["selections"] = {
                **selections,
                "path": _normalize_data_path(str(selections["path"])),
            }
        return normalized_payload

    if component_key == "Badge":
        text = _normalize_inline_string_payload(normalized_payload.get("text"))
        if text is not None:
            normalized_payload["text"] = text
        return normalized_payload

    if component_key == "Tabs":
        tab_items = normalized_payload.get("tabItems")
        if not isinstance(tab_items, list):
            return normalized_payload
        normalized_items: list[object] = []
        for item in tab_items:
            if not isinstance(item, dict):
                normalized_items.append(item)
                continue
            normalized_item = dict(item)
            title = _normalize_inline_string_payload(item.get("title"))
            if title is not None:
                normalized_item["title"] = title
            normalized_items.append(normalized_item)
        normalized_payload["tabItems"] = normalized_items
        return normalized_payload

    if component_key == "Table":
        columns = normalized_payload.get("columns")
        if isinstance(columns, list):
            normalized_columns: list[object] = []
            for column in columns:
                if not isinstance(column, dict):
                    normalized_columns.append(column)
                    continue
                normalized_column = dict(column)
                header = _normalize_inline_string_payload(column.get("header"))
                if header is not None:
                    normalized_column["header"] = header
                normalized_columns.append(normalized_column)
            normalized_payload["columns"] = normalized_columns
        rows = normalized_payload.get("rows")
        if isinstance(rows, list):
            normalized_rows: list[object] = []
            for row in rows:
                if not isinstance(row, dict):
                    normalized_rows.append(row)
                    continue
                normalized_row = dict(row)
                cells = row.get("cells")
                if isinstance(cells, list):
                    normalized_cells: list[object] = []
                    for cell in cells:
                        string_cell = _normalize_inline_string_payload(cell)
                        if string_cell is not None:
                            normalized_cells.append(string_cell)
                            continue
                        number_cell = _normalize_number_value_payload(cell)
                        if number_cell is not None:
                            normalized_cells.append(number_cell)
                            continue
                        boolean_cell = _normalize_boolean_value_payload(cell)
                        if boolean_cell is not None:
                            normalized_cells.append(boolean_cell)
                            continue
                        normalized_cells.append(cell)
                    normalized_row["cells"] = normalized_cells
                normalized_rows.append(normalized_row)
            normalized_payload["rows"] = normalized_rows
        return normalized_payload

    if component_key == "Progress":
        label = _normalize_inline_string_payload(normalized_payload.get("label"))
        if label is not None:
            normalized_payload["label"] = label
        value = _normalize_number_value_payload(normalized_payload.get("value"))
        if value is not None:
            normalized_payload["value"] = value
        max_value = _normalize_number_value_payload(normalized_payload.get("max"))
        if max_value is not None:
            normalized_payload["max"] = max_value
        return normalized_payload

    return normalized_payload


def _normalize_children_ref_payload(value: object) -> dict[str, list[str]] | None:
    """Normalize child-id arrays into canonical explicitList refs."""
    if isinstance(value, list):
        if not all(_is_non_empty_string(child) for child in value):
            return None
        return {"explicitList": [str(child) for child in value]}
    if not isinstance(value, dict):
        return None

    explicit_list = value.get("explicitList")
    if not isinstance(explicit_list, list) or not all(
        _is_non_empty_string(child) for child in explicit_list
    ):
        return None
    return {"explicitList": [str(child) for child in explicit_list]}


def _normalize_gap_payload(value: object) -> str | None:
    """Normalize numeric layout gap values into CSS px strings."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:g}px"
    if _is_non_empty_string(value):
        return str(value)
    return None


def _normalize_inline_text_component_payload(value: object) -> dict[str, object] | None:  # noqa: PLR0912
    """Normalize a title/label sugar value into a Text component payload."""
    normalized_text = _normalize_inline_string_payload(value)
    if normalized_text is not None:
        return {"text": normalized_text}
    if not isinstance(value, dict):
        return None

    nested_component = value.get("component")
    if isinstance(nested_component, dict):
        nested_text = nested_component.get("Text")
        if isinstance(nested_text, dict):
            payload = dict(nested_text)
        else:
            payload = None
    else:
        nested_text = value.get("Text")
        payload = dict(nested_text) if isinstance(nested_text, dict) else None

    if payload is None and any(
        key in value for key in ("text", "style", "usageHint", "literalString", "literal", "path")
    ):
        payload = {}
        normalized_text = _normalize_inline_string_payload(
            value.get("text") if "text" in value else value
        )
        if normalized_text is not None:
            payload["text"] = normalized_text
        style = value.get("style")
        if isinstance(style, dict):
            payload["style"] = dict(style)
        usage_hint = value.get("usageHint")
        if _is_non_empty_string(usage_hint):
            payload["usageHint"] = str(usage_hint)

    if payload is None:
        return None

    normalized_payload = dict(payload)
    if "text" in normalized_payload:
        normalized_text = _normalize_inline_string_payload(normalized_payload.get("text"))
        if normalized_text is not None:
            normalized_payload["text"] = normalized_text
    return normalized_payload


def _reserve_component_id(base_id: str, used_ids: set[str]) -> str:
    """Reserve a deterministic synthetic component id without collisions."""
    candidate = base_id
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base_id}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _make_synthetic_text_component(
    owner_id: str,
    suffix: str,
    source: object,
    *,
    used_ids: set[str],
) -> dict[str, object] | None:
    """Build a synthetic Text component for label/title sugar."""
    payload = _normalize_inline_text_component_payload(source)
    if payload is None:
        return None
    component_id = _reserve_component_id(f"{owner_id}__{suffix}", used_ids)
    return {
        "id": component_id,
        "component": {"Text": payload},
    }


def _canonicalize_surface_components(  # noqa: C901, PLR0912, PLR0915
    components: object,
    *,
    used_ids: set[str] | None = None,
) -> object:
    """Canonicalize authoring sugar inside surfaceUpdate component arrays."""
    if not isinstance(components, list):
        return components

    mutable_used_ids = used_ids if used_ids is not None else set()
    mutable_used_ids.update(
        str(component_id)
        for component in components
        if isinstance(component, dict)
        and isinstance((component_id := component.get("id")), str)
        and component_id.strip()
    )
    normalized_components: list[object] = []
    for raw_component in components:
        if not isinstance(raw_component, dict):
            normalized_components.append(raw_component)
            continue

        component_id = raw_component.get("id")
        component_payload = raw_component.get("component")
        if (
            not isinstance(component_id, str)
            or not component_id.strip()
            or not isinstance(component_payload, dict)
        ):
            normalized_components.append(dict(raw_component))
            continue

        allowed_keys = SUPPORTED_A2UI_COMPONENT_KEYS | {"style"}
        extra_keys = [key for key in component_payload if key not in allowed_keys]
        if extra_keys:
            normalized_components.append(dict(raw_component))
            continue

        component_keys = [key for key in component_payload if key in SUPPORTED_A2UI_COMPONENT_KEYS]
        if len(component_keys) != 1:
            normalized_components.append(dict(raw_component))
            continue

        original_key = component_keys[0]
        canonical_key = _canonicalize_component_key(original_key)
        payload = component_payload.get(original_key)
        if not isinstance(payload, dict):
            payload = component_payload.get(canonical_key)
        if not isinstance(payload, dict):
            normalized_components.append(dict(raw_component))
            continue

        normalized_payload = _canonicalize_component_payload_values(canonical_key, payload)
        synthetic_components: list[dict[str, object]] = []

        if canonical_key == "Button":
            if not _is_non_empty_string(normalized_payload.get("child")):
                synthetic_label = _make_synthetic_text_component(
                    component_id,
                    "label",
                    normalized_payload.get("label"),
                    used_ids=mutable_used_ids,
                )
                if synthetic_label is not None:
                    synthetic_components.append(synthetic_label)
                    normalized_payload["child"] = synthetic_label["id"]
            normalized_payload.pop("label", None)

        if canonical_key in {"Card", "Column", "Row"}:
            normalized_children = _normalize_children_ref_payload(
                normalized_payload.get("children")
            )
            if normalized_children is not None:
                normalized_payload["children"] = normalized_children

            normalized_gap = _normalize_gap_payload(normalized_payload.get("gap"))
            if normalized_gap is not None:
                normalized_payload["gap"] = normalized_gap

            if canonical_key == "Card":
                title_value = normalized_payload.get("title")
                if title_value is not None and not isinstance(title_value, str):
                    synthetic_title = _make_synthetic_text_component(
                        component_id,
                        "title",
                        title_value,
                        used_ids=mutable_used_ids,
                    )
                    if synthetic_title is not None:
                        normalized_children = _normalize_children_ref_payload(
                            normalized_payload.get("children")
                        ) or {"explicitList": []}
                        normalized_payload["children"] = {
                            "explicitList": [
                                synthetic_title["id"],
                                *normalized_children["explicitList"],
                            ]
                        }
                        synthetic_components.append(synthetic_title)
                        normalized_payload.pop("title", None)

        normalized_component_payload: dict[str, object] = {canonical_key: normalized_payload}
        sibling_style = component_payload.get("style")
        if isinstance(sibling_style, dict):
            normalized_component_payload["style"] = dict(sibling_style)

        normalized_components.extend(synthetic_components)
        normalized_components.append(
            {
                "id": component_id,
                "component": normalized_component_payload,
            }
        )

    return normalized_components


def _canonicalize_envelope_payload(payload: dict[str, object]) -> dict[str, object]:
    """Normalize envelope metadata onto the canonical camelCase payload shape."""
    normalized = dict(payload)
    surface_id = payload.get("surfaceId") or payload.get("surface_id")
    if _is_non_empty_string(surface_id):
        normalized["surfaceId"] = str(surface_id)
        normalized.pop("surface_id", None)
    return normalized


def _canonicalize_message_record(
    record: dict[str, object],
    *,
    used_ids: set[str] | None = None,
) -> dict[str, object]:
    """Normalize one parsed A2UI record into canonical envelope form."""
    normalized_record: dict[str, object] = {}

    begin_rendering = _extract_envelope_payload(record, "beginRendering", "begin_rendering")
    if begin_rendering is not None:
        normalized_record["beginRendering"] = _canonicalize_envelope_payload(begin_rendering)

    surface_update = _extract_envelope_payload(record, "surfaceUpdate", "surface_update")
    if surface_update is not None:
        normalized_surface_update = _canonicalize_envelope_payload(surface_update)
        normalized_surface_update["components"] = _canonicalize_surface_components(
            normalized_surface_update.get("components"),
            used_ids=used_ids,
        )
        normalized_record["surfaceUpdate"] = normalized_surface_update

    data_model_update = _extract_envelope_payload(record, "dataModelUpdate", "data_model_update")
    if data_model_update is not None:
        normalized_record["dataModelUpdate"] = _canonicalize_envelope_payload(data_model_update)

    delete_surface = _extract_envelope_payload(record, "deleteSurface", "delete_surface")
    if delete_surface is not None:
        normalized_record["deleteSurface"] = _canonicalize_envelope_payload(delete_surface)

    return normalized_record or dict(record)


def canonicalize_a2ui_messages(
    messages: str,
    *,
    reserved_component_ids: set[str] | None = None,
) -> str:
    """Normalize supported authoring sugar into canonical A2UI JSONL."""
    records = _iter_message_dicts(messages)
    if not records:
        return messages
    used_ids = set(reserved_component_ids or set())
    normalized_records = [
        _canonicalize_message_record(record, used_ids=used_ids) for record in records
    ]
    normalized_records = _canonicalize_begin_rendering_roots(normalized_records)
    serialized = "\n".join(json.dumps(record) for record in normalized_records)
    return serialized or messages


def _strip_markdown_code_fence(messages: str) -> str:
    """Strip a surrounding markdown code fence from a JSONL payload."""
    stripped = messages.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 3 or not lines[-1].strip().startswith("```"):
        return stripped
    return "\n".join(lines[1:-1]).strip()


def _dict_payload_for(
    record: dict[str, object],
    canonical: str,
    alias: str,
) -> dict[str, object] | None:
    """Return a shallow-copied direct envelope payload when present."""
    payload = record.get(canonical)
    if isinstance(payload, dict):
        return dict(payload)
    payload = record.get(alias)
    if isinstance(payload, dict):
        return dict(payload)
    return None


def _split_compound_a2ui_record(record: dict[str, object]) -> list[dict[str, object]]:
    """Split multi-envelope objects into separate JSONL-style records."""
    begin_rendering = _dict_payload_for(record, "beginRendering", "begin_rendering")
    surface_update = _dict_payload_for(record, "surfaceUpdate", "surface_update")
    data_model_update = _dict_payload_for(record, "dataModelUpdate", "data_model_update")
    delete_surface = _dict_payload_for(record, "deleteSurface", "delete_surface")

    nested_data_model_update: dict[str, object] | None = None
    if surface_update is not None:
        nested_data_model_update = _dict_payload_for(
            surface_update,
            "dataModelUpdate",
            "data_model_update",
        )
        if nested_data_model_update is not None:
            inherited_surface_id = surface_update.get("surfaceId")
            if (
                isinstance(inherited_surface_id, str)
                and inherited_surface_id.strip()
                and not _is_non_empty_string(nested_data_model_update.get("surfaceId"))
            ):
                nested_data_model_update["surfaceId"] = inherited_surface_id
            surface_update.pop("dataModelUpdate", None)
            surface_update.pop("data_model_update", None)

    direct_envelope_count = sum(
        payload is not None
        for payload in (
            begin_rendering,
            surface_update,
            data_model_update,
            delete_surface,
        )
    )
    if direct_envelope_count == 0:
        return [record]
    if direct_envelope_count == 1 and nested_data_model_update is None:
        return [record]

    split_records: list[dict[str, object]] = []
    if begin_rendering is not None:
        split_records.append({"beginRendering": begin_rendering})
    if surface_update is not None:
        split_records.append({"surfaceUpdate": surface_update})
    if data_model_update is not None:
        split_records.append({"dataModelUpdate": data_model_update})
    if nested_data_model_update is not None:
        split_records.append({"dataModelUpdate": nested_data_model_update})
    if delete_surface is not None:
        split_records.append({"deleteSurface": delete_surface})
    return split_records or [record]


def _coerce_message_dicts(raw: object) -> list[dict[str, object]]:
    """Coerce parsed JSON payloads into a list of envelope dictionaries."""
    if isinstance(raw, dict):
        messages = raw.get("messages")
        if isinstance(messages, list):
            parsed_messages: list[dict[str, object]] = []
            for entry in messages:
                if not isinstance(entry, dict):
                    continue
                parsed_messages.extend(_split_compound_a2ui_record(entry))
            return parsed_messages
        return _split_compound_a2ui_record(raw)
    if isinstance(raw, list):
        parsed_list_messages: list[dict[str, object]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            parsed_list_messages.extend(_split_compound_a2ui_record(entry))
        return parsed_list_messages
    return []


def _extract_json_object_spans(raw: str) -> list[tuple[int, int]]:
    """Extract brace-balanced JSON object spans from a string."""
    spans: list[tuple[int, int]] = []
    start_index: int | None = None
    depth = 0
    in_string = False
    escape_next = False

    for index, char in enumerate(raw):
        if in_string:
            if escape_next:
                escape_next = False
            elif char == "\\":
                escape_next = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start_index = index
            depth += 1
            continue
        if char != "}":
            continue
        depth -= 1
        if depth == 0 and start_index is not None:
            spans.append((start_index, index + 1))
            start_index = None

    return spans


def _contains_json_delimiters(raw: str) -> bool:
    """Return True when a gap contains JSON-like structural delimiters."""
    return any(char in raw for char in "{}[]")


def _extract_json_objects(raw: str) -> list[str]:
    """Extract brace-balanced JSON objects from a string."""
    return [raw[start:end] for start, end in _extract_json_object_spans(raw)]


def _repair_json_bracket_balance(raw: str) -> str | None:  # noqa: C901, PLR0912
    """Repair simple missing JSON bracket/brace closers in LLM-authored payloads."""
    repaired: list[str] = []
    stack: list[str] = []
    in_string = False
    escape_next = False
    changed = False

    for char in raw:
        repaired.append(char)
        if in_string:
            if escape_next:
                escape_next = False
            elif char == "\\":
                escape_next = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char in "{[":
            stack.append(char)
            continue
        if char not in "}]":
            continue

        expected_open = "{" if char == "}" else "["
        if not stack:
            return None

        while stack and stack[-1] != expected_open:
            repaired.insert(len(repaired) - 1, "}" if stack[-1] == "{" else "]")
            stack.pop()
            changed = True

        if not stack:
            return None
        stack.pop()

    if in_string:
        return None

    while stack:
        repaired.append("}" if stack.pop() == "{" else "]")
        changed = True

    if not changed:
        return None
    return "".join(repaired)


def _parse_json_like(raw: str) -> object | None:
    """Parse JSON, then fall back to safe Python literal syntax for common LLM slips."""
    try:
        parsed: object = json.loads(raw)
        return parsed
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(raw)
            return parsed
        except (ValueError, SyntaxError):
            repaired = _repair_json_bracket_balance(raw)
            if repaired is None:
                return None
            try:
                parsed = json.loads(repaired)
                return parsed
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(repaired)
                    return parsed
                except (ValueError, SyntaxError):
                    return None


def _iter_message_dicts(messages: str) -> list[dict[str, object]]:
    """Parse A2UI message payloads into top-level envelope dictionaries."""
    stripped = _strip_markdown_code_fence(messages)
    if not stripped:
        return []

    parsed_whole = _parse_json_like(stripped)
    if parsed_whole is not None:
        return _coerce_message_dicts(parsed_whole)

    parsed_lines: list[dict[str, object]] = []
    for line in stripped.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("```"):
            continue
        if not (candidate.startswith("{") and candidate.endswith("}")):
            continue
        parsed = _parse_json_like(candidate)
        if parsed is None:
            continue
        parsed_lines.extend(_coerce_message_dicts(parsed))
    if parsed_lines:
        return parsed_lines

    parsed_objects: list[dict[str, object]] = []
    for chunk in _extract_json_objects(stripped):
        parsed = _parse_json_like(chunk)
        if parsed is None:
            continue
        parsed_objects.extend(_coerce_message_dicts(parsed))
    return parsed_objects


def _surface_id_from_record(record: dict[str, object]) -> str | None:
    """Extract a surface ID from supported top-level A2UI envelope shapes."""
    for key in SURFACE_KEYS:
        payload = record.get(key)
        if isinstance(payload, dict):
            surface_id = payload.get("surfaceId") or payload.get("surface_id")
            if isinstance(surface_id, str) and surface_id:
                return surface_id

    envelope_type = record.get("type")
    payload = record.get("payload")
    if (
        isinstance(envelope_type, str)
        and envelope_type in TYPED_SURFACE_TYPES
        and isinstance(payload, dict)
    ):
        surface_id = payload.get("surfaceId") or payload.get("surface_id")
        if isinstance(surface_id, str) and surface_id:
            return surface_id

    return None


def _extract_envelope_payload(record: dict[str, object], *keys: str) -> dict[str, object] | None:
    """Return the payload for a direct or typed A2UI envelope."""
    for key in keys:
        payload = record.get(key)
        if isinstance(payload, dict):
            return payload

    envelope_type = record.get("type")
    payload = record.get("payload")
    if isinstance(envelope_type, str) and envelope_type in keys and isinstance(payload, dict):
        return payload
    return None


def _invalid_a2ui_payload(detail: str) -> str:
    """Build a correction-focused A2UI validation error message."""
    return (
        f"Invalid A2UI payload: {detail} "
        "Expected A2UI JSONL with beginRendering/surfaceUpdate envelopes, for example: "
        f"{INITIAL_A2UI_SURFACE_EXAMPLE}"
    )


def _flat_surface_payload_error(parsed_whole: object) -> str | None:
    """Return a targeted error for plain surface objects without A2UI envelopes."""
    if not isinstance(parsed_whole, dict):
        return None
    flat_surface_id = parsed_whole.get("surfaceId") or parsed_whole.get("surface_id")
    if not isinstance(flat_surface_id, str) or "components" not in parsed_whole:
        return None
    return _invalid_a2ui_payload(
        'received a plain {"surfaceId":"...","components":[...]} object. '
        "Wrap it in beginRendering and surfaceUpdate envelopes and include a root id."
    )


def _validate_begin_rendering_payload(payload: dict[str, object]) -> str | None:
    """Validate a beginRendering envelope payload."""
    surface_id = payload.get("surfaceId") or payload.get("surface_id")
    if not isinstance(surface_id, str) or not surface_id.strip():
        return _invalid_a2ui_payload("beginRendering.surfaceId must be a non-empty string.")

    root = payload.get("root")
    if not isinstance(root, str) or not root.strip():
        return _invalid_a2ui_payload("beginRendering.root must be a non-empty string.")
    return None


def _validate_surface_update_component(component: object, index: int) -> str | None:  # noqa: C901, PLR0911, PLR0912
    """Validate a single surfaceUpdate component entry."""
    if not isinstance(component, dict):
        return _invalid_a2ui_payload(f"surfaceUpdate.components[{index}] must be an object.")

    component_id = component.get("id")
    if not isinstance(component_id, str) or not component_id.strip():
        return _invalid_a2ui_payload(
            f"surfaceUpdate.components[{index}].id must be a non-empty string."
        )

    component_key, payload, error = _component_payload_from_entry(component, index=index)
    if error is not None:
        return error

    field_path = f"surfaceUpdate.components[{index}].component.{component_key}"
    if component_key == "Text":
        return _validate_text_component_payload(payload, field_path=field_path)
    if component_key == "Button":
        return _validate_button_component_payload(payload, field_path=field_path)
    if component_key in {"Card", "Column", "Row"}:
        return _validate_layout_component_payload(
            payload,
            component_key=component_key,
            field_path=field_path,
        )
    if component_key == "TextField":
        return _validate_text_field_component_payload(payload, field_path=field_path)
    if component_key == "Divider":
        return None
    if component_key == "Image":
        return _validate_image_component_payload(payload, field_path=field_path)
    if component_key == "CheckBox":
        return _validate_checkbox_component_payload(payload, field_path=field_path)
    if component_key == "MultipleChoice":
        return _validate_multiple_choice_component_payload(payload, field_path=field_path)
    if component_key == "Radio":
        return _validate_radio_component_payload(payload, field_path=field_path)
    if component_key == "Badge":
        return _validate_badge_component_payload(payload, field_path=field_path)
    if component_key == "Tabs":
        return _validate_tabs_component_payload(payload, field_path=field_path)
    if component_key == "Modal":
        return _validate_modal_component_payload(payload, field_path=field_path)
    if component_key == "Table":
        return _validate_table_component_payload(payload, field_path=field_path)
    if component_key == "Progress":
        return _validate_progress_component_payload(payload, field_path=field_path)
    return _invalid_a2ui_payload(
        f"surfaceUpdate.components[{index}] uses unsupported component key {component_key!r}."
    )


def _validate_surface_update_payload(
    payload: dict[str, object],
    *,
    require_initial_render: bool,
) -> str | None:
    """Validate a surfaceUpdate envelope payload."""
    if require_initial_render:
        surface_id = payload.get("surfaceId") or payload.get("surface_id")
        if not isinstance(surface_id, str) or not surface_id.strip():
            return _invalid_a2ui_payload(
                "surfaceUpdate.surfaceId must be a non-empty string for new surfaces."
            )

    components = payload.get("components")
    if not isinstance(components, list):
        return _invalid_a2ui_payload("surfaceUpdate.components must be an array.")

    for index, component in enumerate(components):
        if error := _validate_surface_update_component(component, index):
            return error
    return None


def _validate_a2ui_record(
    record: dict[str, object],
    *,
    require_initial_render: bool,
) -> tuple[bool, bool, bool, str | None]:
    """Validate a single parsed A2UI record and report which envelopes were seen."""
    saw_begin_rendering = False
    saw_surface_update = False
    saw_supported_envelope = False

    begin_rendering = _extract_envelope_payload(record, "beginRendering", "begin_rendering")
    if begin_rendering is not None:
        saw_supported_envelope = True
        saw_begin_rendering = True
        if error := _validate_begin_rendering_payload(begin_rendering):
            return saw_begin_rendering, saw_surface_update, saw_supported_envelope, error

    surface_update = _extract_envelope_payload(record, "surfaceUpdate", "surface_update")
    if surface_update is not None:
        saw_supported_envelope = True
        saw_surface_update = True
        if error := _validate_surface_update_payload(
            surface_update,
            require_initial_render=require_initial_render,
        ):
            return saw_begin_rendering, saw_surface_update, saw_supported_envelope, error

    if _extract_envelope_payload(record, "dataModelUpdate", "data_model_update") is not None:
        saw_supported_envelope = True
    if _extract_envelope_payload(record, "deleteSurface", "delete_surface") is not None:
        saw_supported_envelope = True

    return saw_begin_rendering, saw_surface_update, saw_supported_envelope, None


def _parse_a2ui_validation_records(  # noqa: C901, PLR0911, PLR0912
    messages: str,
) -> tuple[list[dict[str, object]], str | None]:
    """Parse raw A2UI messages for validation and detect flat payload misuse."""
    stripped = _strip_markdown_code_fence(messages)
    if not stripped:
        return [], _invalid_a2ui_payload("payload is empty.")

    parsed_whole = _parse_json_like(stripped)

    if error := _flat_surface_payload_error(parsed_whole):
        return [], error

    if parsed_whole is not None:
        records = _coerce_message_dicts(parsed_whole)
        if records:
            return records, None
        return [], _invalid_a2ui_payload("could not parse any supported A2UI envelopes.")

    parsed_jsonl_lines: list[dict[str, object]] = []
    saw_jsonl_object_line = False
    saw_non_jsonl_structure = False
    for line in stripped.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("```"):
            continue
        if candidate.startswith("{") and candidate.endswith("}"):
            saw_jsonl_object_line = True
            parsed = _parse_json_like(candidate)
            if parsed is None:
                parsed_jsonl_lines = []
                saw_jsonl_object_line = False
                break
            parsed_jsonl_lines.extend(_coerce_message_dicts(parsed))
            continue
        if _contains_json_delimiters(candidate):
            saw_non_jsonl_structure = True
            break
    if saw_jsonl_object_line and parsed_jsonl_lines and not saw_non_jsonl_structure:
        return parsed_jsonl_lines, None

    spans = _extract_json_object_spans(stripped)
    if not spans:
        return [], _invalid_a2ui_payload("could not parse any supported A2UI envelopes.")

    cursor = 0
    parsed_records: list[dict[str, object]] = []
    for start, end in spans:
        gap = stripped[cursor:start].strip()
        if gap and _contains_json_delimiters(gap):
            return [], _invalid_a2ui_payload("payload contains malformed JSON between envelopes.")
        chunk = stripped[start:end]
        parsed = _parse_json_like(chunk)
        if parsed is None:
            return [], _invalid_a2ui_payload("payload contains malformed JSON between envelopes.")
        parsed_records.extend(_coerce_message_dicts(parsed))
        cursor = end

    trailing = stripped[cursor:].strip()
    if trailing and _contains_json_delimiters(trailing):
        return [], _invalid_a2ui_payload("payload contains malformed JSON between envelopes.")
    if not parsed_records:
        return [], _invalid_a2ui_payload("could not parse any supported A2UI envelopes.")
    return parsed_records, None


def _scan_a2ui_validation_records(
    records: list[dict[str, object]],
    *,
    require_initial_render: bool,
) -> tuple[bool, bool, bool, str | None]:
    """Validate parsed A2UI records and report which required envelopes were seen."""
    saw_begin_rendering = False
    saw_surface_update = False
    saw_supported_envelope = False

    for record in records:
        (
            record_saw_begin,
            record_saw_update,
            record_saw_supported,
            record_error,
        ) = _validate_a2ui_record(record, require_initial_render=require_initial_render)
        if record_error is not None:
            return saw_begin_rendering, saw_surface_update, saw_supported_envelope, record_error
        saw_begin_rendering = saw_begin_rendering or record_saw_begin
        saw_surface_update = saw_surface_update or record_saw_update
        saw_supported_envelope = saw_supported_envelope or record_saw_supported

    return saw_begin_rendering, saw_surface_update, saw_supported_envelope, None


def _finalize_a2ui_validation(
    messages: str,
    *,
    require_initial_render: bool,
    saw_begin_rendering: bool,
    saw_surface_update: bool,
    saw_supported_envelope: bool,
    error: str | None,
) -> str | None:
    """Apply final cross-record A2UI validation rules."""
    if error is not None:
        return error
    if not saw_supported_envelope:
        return _invalid_a2ui_payload("no supported A2UI envelopes were found.")

    surface_ids = extract_surface_ids(messages)
    if len(surface_ids) > 1:
        return _invalid_a2ui_payload(
            "all envelopes in one interactive surface payload must use the same surfaceId."
        )
    if not require_initial_render:
        return None
    if not saw_begin_rendering or not saw_surface_update:
        return _invalid_a2ui_payload(
            "new interactive surfaces must include both beginRendering and surfaceUpdate envelopes."
        )
    return None


def _collect_begin_render_roots(records: list[dict[str, object]]) -> set[str]:
    """Collect root ids declared by beginRendering envelopes."""
    roots: set[str] = set()
    for record in records:
        begin_rendering = _extract_envelope_payload(record, "beginRendering", "begin_rendering")
        if begin_rendering is None:
            continue
        root = begin_rendering.get("root")
        if isinstance(root, str) and root.strip():
            roots.add(root)
    return roots


def _collect_surface_component_ids(records: list[dict[str, object]]) -> set[str]:
    """Collect declared component ids from surfaceUpdate envelopes."""
    component_ids: set[str] = set()
    for record in records:
        surface_update = _extract_envelope_payload(record, "surfaceUpdate", "surface_update")
        if surface_update is None:
            continue
        components = surface_update.get("components")
        if not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, dict):
                continue
            component_id = component.get("id")
            if isinstance(component_id, str) and component_id.strip():
                component_ids.add(component_id)
    return component_ids


def _collect_referenced_component_ids(
    components_by_id: dict[str, dict[str, object]],
) -> set[str]:
    """Collect component ids referenced by other components."""
    referenced_ids: set[str] = set()
    for component in components_by_id.values():
        referenced_ids.update(_referenced_component_ids(component))
    return referenced_ids


def _child_component_ids(value: object) -> list[str]:
    """Return referenced child ids from list/explicitList component props."""
    if isinstance(value, list):
        return [item for item in value if _is_non_empty_string(item)]
    if not isinstance(value, dict):
        return []

    explicit_list = value.get("explicitList")
    if not isinstance(explicit_list, list):
        return []
    return [item for item in explicit_list if _is_non_empty_string(item)]


def _referenced_component_ids(component: dict[str, object]) -> list[str]:  # noqa: PLR0911
    """Return child component ids referenced by a component payload."""
    component_key, payload, error = _component_payload_from_entry(component, index=-1)
    if error is not None:
        return []

    if component_key == "Button":
        child = payload.get("child")
        return [str(child)] if _is_non_empty_string(child) else []
    if component_key in {"Card", "Column", "Row"}:
        return _child_component_ids(payload.get("children"))
    if component_key == "Tabs":
        tab_items = payload.get("tabItems")
        if not isinstance(tab_items, list):
            return []
        return [
            str(item["child"])
            for item in tab_items
            if isinstance(item, dict) and _is_non_empty_string(item.get("child"))
        ]
    if component_key == "Modal":
        component_ids: list[str] = []
        entry_point_child = payload.get("entryPointChild")
        if _is_non_empty_string(entry_point_child):
            component_ids.append(str(entry_point_child))
        content_child = payload.get("contentChild")
        if _is_non_empty_string(content_child):
            component_ids.append(str(content_child))
        return component_ids
    return []


def _reachable_component_ids(
    root: str | None,
    components_by_id: dict[str, dict[str, object]],
) -> set[str]:
    """Return component ids reachable from the current render root."""
    if root is None or root not in components_by_id:
        return set()

    reachable: set[str] = set()
    stack = [root]
    while stack:
        component_id = stack.pop()
        component = components_by_id.get(component_id)
        if component is None:
            continue
        if component_id in reachable:
            continue
        reachable.add(component_id)
        for child_id in _referenced_component_ids(component):
            if child_id not in reachable:
                stack.append(child_id)
    return reachable


def _select_best_render_root(
    root: str | None,
    components_by_id: dict[str, dict[str, object]],
) -> str | None:
    """Promote an obviously leaf-like root to the best unreferenced container root."""
    if root is None or root not in components_by_id:
        return root

    referenced_ids = _collect_referenced_component_ids(components_by_id)
    if root not in referenced_ids:
        return root

    current_reachable = _reachable_component_ids(root, components_by_id)
    best_root = root
    best_size = len(current_reachable)

    for candidate_id in components_by_id:
        if candidate_id == root or candidate_id in referenced_ids:
            continue
        candidate_reachable = _reachable_component_ids(candidate_id, components_by_id)
        if len(candidate_reachable) > best_size:
            best_root = candidate_id
            best_size = len(candidate_reachable)

    return best_root


def _canonicalize_begin_rendering_roots(  # noqa: C901, PLR0911
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Retarget beginRendering.root to the top-level container when a leaf root hides siblings."""
    surface_ids = {
        surface_id
        for record in records
        if (surface_id := _surface_id_from_record(record)) is not None
    }
    if len(surface_ids) != 1:
        return records

    state = _rebuild_stream_state(records)
    corrected_root = _select_best_render_root(state.root, state.components_by_id)
    if corrected_root is not None and corrected_root != state.root:
        normalized_records: list[dict[str, object]] = []
        for record in records:
            begin_rendering = _extract_envelope_payload(record, "beginRendering", "begin_rendering")
            if begin_rendering is None:
                normalized_records.append(record)
                continue
            normalized_payload = _canonicalize_envelope_payload(begin_rendering)
            normalized_payload["root"] = corrected_root
            normalized_records.append({"beginRendering": normalized_payload})
        return normalized_records

    if state.root is None or state.root not in state.components_by_id:
        return records

    root_component = state.components_by_id[state.root]
    root_key, _root_payload, root_error = _component_payload_from_entry(root_component, index=-1)
    if root_error is not None or root_key != "Button":
        return records

    referenced_ids = _collect_referenced_component_ids(state.components_by_id)
    top_level_ids = [
        component_id
        for component_id in state.components_by_id
        if component_id not in referenced_ids
    ]
    if len(top_level_ids) <= 1:
        return records

    current_reachable = _reachable_component_ids(state.root, state.components_by_id)
    if set(top_level_ids).issubset(current_reachable):
        return records

    wrapper_id = _reserve_component_id(
        f"{state.surface_id or 'surface'}__root",
        set(state.components_by_id),
    )
    wrapper_component = {
        "id": wrapper_id,
        "component": {
            "Column": {
                "children": {"explicitList": top_level_ids},
            }
        },
    }

    normalized_records = []
    for record in records:
        begin_rendering = _extract_envelope_payload(record, "beginRendering", "begin_rendering")
        if begin_rendering is not None:
            normalized_payload = _canonicalize_envelope_payload(begin_rendering)
            normalized_payload["root"] = wrapper_id
            normalized_records.append({"beginRendering": normalized_payload})
            continue

        surface_update = _extract_envelope_payload(record, "surfaceUpdate", "surface_update")
        if surface_update is not None:
            normalized_surface_update = _canonicalize_envelope_payload(surface_update)
            components = normalized_surface_update.get("components")
            if isinstance(components, list):
                normalized_surface_update["components"] = [wrapper_component, *components]
            normalized_records.append({"surfaceUpdate": normalized_surface_update})
            continue

        normalized_records.append(record)
    return normalized_records


def _rebuild_stream_state(records: list[dict[str, object]]) -> _A2UIMessageStreamState:
    """Reconstruct final surface state from a parsed message stream."""
    state = _A2UIMessageStreamState()
    for record in records:
        _apply_record_to_stream_state(state, record)
    return state


def _validate_component_references(  # noqa: C901, PLR0912
    root: str | None,
    components_by_id: dict[str, dict[str, object]],
) -> str | None:
    """Validate render-tree references after envelopes have been merged."""
    component_ids = (
        _reachable_component_ids(root, components_by_id)
        if root is not None
        else set(components_by_id)
    )
    for component_id in component_ids:
        component = components_by_id.get(component_id)
        if component is None:
            continue
        component_key, payload, error = _component_payload_from_entry(component, index=-1)
        if error is not None:
            continue

        if component_key == "Button":
            child_id = payload.get("child")
            if not _is_non_empty_string(child_id):
                continue
            child_component = components_by_id.get(str(child_id))
            if child_component is None:
                return _invalid_a2ui_payload(
                    "Button.child must reference an existing Text component id. "
                    f"Missing child: {child_id!r}."
                )
            child_key, _child_payload, child_error = _component_payload_from_entry(
                child_component,
                index=-1,
            )
            if child_error is not None or child_key != "Text":
                return _invalid_a2ui_payload(
                    "Button.child must reference a Text component id. "
                    f"Invalid child target: {child_id!r}."
                )
            continue

        if component_key in {"Card", "Column", "Row"}:
            missing_children = [
                child_id
                for child_id in _child_component_ids(payload.get("children"))
                if child_id not in components_by_id
            ]
            if missing_children:
                return _invalid_a2ui_payload(
                    f"{component_key}.children must reference existing component ids. "
                    f"Missing children: {sorted(missing_children)}."
                )
            continue

        if component_key == "Tabs":
            missing_children = [
                child_id
                for child_id in _referenced_component_ids(component)
                if child_id not in components_by_id
            ]
            if missing_children:
                return _invalid_a2ui_payload(
                    "Tabs.tabItems[*].child must reference existing component ids. "
                    f"Missing children: {sorted(missing_children)}."
                )
            continue

        if component_key == "Modal":
            missing_children = [
                child_id
                for child_id in _referenced_component_ids(component)
                if child_id not in components_by_id
            ]
            if missing_children:
                return _invalid_a2ui_payload(
                    "Modal entryPointChild/contentChild must reference existing component ids. "
                    f"Missing children: {sorted(missing_children)}."
                )
    return None


def _contains_actionable_component(records: list[dict[str, object]]) -> bool:
    """Return True when a payload contains at least one dispatchable action control."""
    state = _rebuild_stream_state(records)
    reachable_ids = _reachable_component_ids(state.root, state.components_by_id)
    return any(
        component_id in reachable_ids and _is_renderable_button(component, state.components_by_id)
        for component_id, component in state.components_by_id.items()
    )


def extract_actionable_actions(messages: str) -> list[dict[str, str]]:
    """Return the actionable Button id/name pairs present in a payload."""
    state = _rebuild_stream_state(_iter_message_dicts(canonicalize_a2ui_messages(messages)))
    reachable_ids = _reachable_component_ids(state.root, state.components_by_id)
    action_map: dict[str, dict[str, str]] = {}
    for component_id, component in state.components_by_id.items():
        if component_id not in reachable_ids:
            continue
        component_key, payload, error = _component_payload_from_entry(component, index=-1)
        if error is not None or component_key != "Button":
            continue
        action_name = _button_action_name(payload)
        if (
            not _is_non_empty_string(payload.get("child"))
            or action_name is None
            or not _is_renderable_button(component, state.components_by_id)
        ):
            continue
        action_map[component_id] = {
            "source_component_id": component_id,
            "action_name": action_name,
        }
    return list(action_map.values())


def _get_envelope_component_source(
    record: dict[str, object],
    surface_update: dict[str, object] | None,
) -> list[object] | None:
    """Return the component array carried by an envelope, if present."""
    if surface_update is not None:
        components = surface_update.get("components")
        if isinstance(components, list):
            return components

    components = record.get("components")
    if isinstance(components, list):
        return components
    return None


def _build_data_record(
    record: dict[str, object],
    data_model_update: dict[str, object] | None,
    *,
    surface_id: str | None,
) -> dict[str, object] | None:
    """Normalize data model updates into canonical envelope records."""
    if data_model_update is not None:
        payload = dict(data_model_update)
        if "surfaceId" not in payload and "surface_id" not in payload and surface_id:
            payload["surfaceId"] = surface_id
        return {"dataModelUpdate": payload}

    direct_data_model = record.get("dataModel")
    if not isinstance(direct_data_model, dict):
        direct_data_model = record.get("data_model")
    if not isinstance(direct_data_model, dict):
        return None

    model_payload: dict[str, object] = {
        "path": "/",
        "contents": [direct_data_model],
    }
    if surface_id:
        model_payload["surfaceId"] = surface_id
    return {"dataModelUpdate": model_payload}


def _apply_record_to_stream_state(  # noqa: C901, PLR0912
    state: _A2UIMessageStreamState,
    record: dict[str, object],
) -> None:
    """Apply one parsed envelope to the reconstructed surface state."""
    begin_rendering = _extract_envelope_payload(record, "beginRendering", "begin_rendering")
    surface_update = _extract_envelope_payload(record, "surfaceUpdate", "surface_update")
    data_model_update = _extract_envelope_payload(record, "dataModelUpdate", "data_model_update")
    delete_surface = _extract_envelope_payload(record, "deleteSurface", "delete_surface")

    envelope_surface_id = _surface_id_from_record(record)
    if envelope_surface_id:
        state.surface_id = envelope_surface_id
    else:
        raw_surface_id = record.get("surfaceId")
        if isinstance(raw_surface_id, str) and raw_surface_id.strip():
            state.surface_id = raw_surface_id

    if delete_surface is not None:
        state.root = None
        state.styles = None
        state.components_by_id.clear()
        state.data_records = []
        return

    if begin_rendering is not None:
        root = begin_rendering.get("root")
        if isinstance(root, str) and root.strip():
            state.root = root
        styles = begin_rendering.get("styles")
        if isinstance(styles, dict):
            state.styles = dict(styles)
    else:
        root = record.get("root")
        if isinstance(root, str) and root.strip():
            state.root = root

    component_source = _get_envelope_component_source(record, surface_update)
    if component_source is not None:
        for raw_component in component_source:
            if not isinstance(raw_component, dict):
                continue
            component_id = raw_component.get("id")
            if isinstance(component_id, str) and component_id.strip():
                state.components_by_id[component_id] = raw_component

    data_record = _build_data_record(record, data_model_update, surface_id=state.surface_id)
    if data_record is not None:
        state.data_records.append(data_record)


def _serialize_stream_state(state: _A2UIMessageStreamState) -> str:
    """Serialize reconstructed surface state back into canonical JSONL."""
    records: list[dict[str, object]] = []
    visible_component_ids = (
        _reachable_component_ids(state.root, state.components_by_id)
        if state.root is not None
        else set(state.components_by_id)
    )

    if state.root is not None:
        begin_rendering: dict[str, object] = {"root": state.root}
        if state.surface_id:
            begin_rendering["surfaceId"] = state.surface_id
        if state.styles:
            begin_rendering["styles"] = state.styles
        records.append({"beginRendering": begin_rendering})

    if state.components_by_id:
        surface_update: dict[str, object] = {
            "components": [
                component
                for component_id, component in state.components_by_id.items()
                if component_id in visible_component_ids
            ],
        }
        if state.surface_id:
            surface_update["surfaceId"] = state.surface_id
        records.append({"surfaceUpdate": surface_update})

    records.extend(state.data_records)
    return "\n".join(json.dumps(record) for record in records)


def merge_a2ui_message_stream(  # noqa: C901, PLR0911
    previous_messages: str | None,
    incoming_messages: str,
) -> str:
    """Merge incremental A2UI JSONL updates for validation and replay use cases."""
    if not incoming_messages:
        return canonicalize_a2ui_messages(previous_messages) if previous_messages else ""

    canonical_previous_messages = (
        canonicalize_a2ui_messages(previous_messages) if previous_messages else previous_messages
    )
    previous_records = (
        _iter_message_dicts(canonical_previous_messages) if canonical_previous_messages else []
    )
    previous_state = _rebuild_stream_state(previous_records) if previous_records else None
    canonical_incoming_messages = canonicalize_a2ui_messages(
        incoming_messages,
        reserved_component_ids=(
            set(previous_state.components_by_id) if previous_state is not None else None
        ),
    )

    if not canonical_previous_messages:
        return canonical_incoming_messages

    incoming_records = _iter_message_dicts(canonical_incoming_messages)
    if not incoming_records:
        return canonical_incoming_messages

    has_begin_rendering = False
    has_delete_surface = False
    has_incremental_update = False
    for record in incoming_records:
        if _extract_envelope_payload(record, "beginRendering", "begin_rendering") is not None:
            has_begin_rendering = True
        if _extract_envelope_payload(record, "deleteSurface", "delete_surface") is not None:
            has_delete_surface = True
        if _extract_envelope_payload(record, "surfaceUpdate", "surface_update") is not None:
            has_incremental_update = True
        if _extract_envelope_payload(record, "dataModelUpdate", "data_model_update") is not None:
            has_incremental_update = True

    if has_begin_rendering or has_delete_surface or not has_incremental_update:
        return canonical_incoming_messages

    if not previous_records:
        return canonical_incoming_messages

    if previous_state is not None and previous_state.surface_id:
        incoming_surface_ids = {
            surface_id
            for record in incoming_records
            if (surface_id := _surface_id_from_record(record)) is not None
        }
        if incoming_surface_ids != {previous_state.surface_id}:
            return canonical_incoming_messages

    state = _rebuild_stream_state(previous_records + incoming_records)

    serialized = _serialize_stream_state(state)
    return serialized or canonical_incoming_messages


def validate_a2ui_messages(  # noqa: PLR0911
    messages: str,
    *,
    require_initial_render: bool = True,
    require_user_action: bool = False,
) -> str | None:
    """Validate A2UI payloads before creating or waiting on a surface."""
    _raw_records, parse_error = _parse_a2ui_validation_records(messages)
    if parse_error is not None:
        return parse_error
    canonical_messages = canonicalize_a2ui_messages(messages)
    records = _iter_message_dicts(canonical_messages)
    if not records:
        return _invalid_a2ui_payload("could not parse any supported A2UI envelopes.")

    (
        saw_begin_rendering,
        saw_surface_update,
        saw_supported_envelope,
        record_error,
    ) = _scan_a2ui_validation_records(records, require_initial_render=require_initial_render)
    error = _finalize_a2ui_validation(
        canonical_messages,
        require_initial_render=require_initial_render,
        saw_begin_rendering=saw_begin_rendering,
        saw_surface_update=saw_surface_update,
        saw_supported_envelope=saw_supported_envelope,
        error=record_error,
    )
    if error is not None:
        return error

    declared_roots = _collect_begin_render_roots(records)
    if declared_roots:
        component_ids = _collect_surface_component_ids(records)
        missing_roots = declared_roots - component_ids
        if missing_roots:
            return _invalid_a2ui_payload(
                "beginRendering.root must reference a component id present in "
                f"surfaceUpdate.components. Missing roots: {sorted(missing_roots)}."
            )
    state = _rebuild_stream_state(records)
    if error := _validate_component_references(state.root, state.components_by_id):
        return error
    if require_user_action and not _contains_actionable_component(records):
        detail = (
            "interactive surfaces must include at least one reachable Button with child + "
            "action.name. Use canvas_create for display-only layouts such as read-only Cards."
        )
        if not require_initial_render:
            detail = (
                "interactive updates must still resolve to at least one reachable actionable "
                "Button. Send a full render payload or include the reachable Button in the "
                "update. Use canvas_update for display-only layouts."
            )
        return _invalid_a2ui_payload(detail)
    return None


def validate_a2ui_message_syntax(messages: str) -> str | None:
    """Strictly validate raw A2UI JSON/envelope syntax before canonicalization."""
    records, parse_error = _parse_a2ui_validation_records(messages)
    if parse_error is not None:
        return parse_error

    for record in records:
        if _extract_envelope_payload(record, "beginRendering", "begin_rendering") is not None:
            return None
        if _extract_envelope_payload(record, "surfaceUpdate", "surface_update") is not None:
            return None
        if _extract_envelope_payload(record, "dataModelUpdate", "data_model_update") is not None:
            return None
        if _extract_envelope_payload(record, "deleteSurface", "delete_surface") is not None:
            return None

    return _invalid_a2ui_payload("could not parse any supported A2UI envelopes.")


def validate_a2ui_incremental_surface_id(
    messages: str,
    *,
    expected_surface_id: str,
) -> str | None:
    """Reject incremental payloads that drift away from an existing surface id."""
    records, parse_error = _parse_a2ui_validation_records(messages)
    if parse_error is not None:
        return parse_error

    for record in records:
        for envelope_name, legacy_name in (
            ("beginRendering", "begin_rendering"),
            ("surfaceUpdate", "surface_update"),
            ("dataModelUpdate", "data_model_update"),
            ("deleteSurface", "delete_surface"),
        ):
            payload = _extract_envelope_payload(record, envelope_name, legacy_name)
            if payload is None:
                continue
            surface_id = payload.get("surfaceId")
            if not isinstance(surface_id, str) or not surface_id.strip():
                return _invalid_a2ui_payload(
                    "incremental updates for an existing surface must include surfaceId on every envelope."
                )
            if surface_id != expected_surface_id:
                return _invalid_a2ui_payload(
                    f"incremental updates for this surface must use surfaceId "
                    f"{expected_surface_id!r}. Got {surface_id!r}."
                )

    return None


def extract_surface_ids(messages: str) -> list[str]:
    """Return unique surface IDs discovered in A2UI message payloads."""
    seen: set[str] = set()
    ordered: list[str] = []
    for record in _iter_message_dicts(messages):
        surface_id = _surface_id_from_record(record)
        if surface_id is None:
            continue
        if surface_id in seen:
            continue
        seen.add(surface_id)
        ordered.append(surface_id)
    return ordered


def extract_surface_id(messages: str) -> str | None:
    """Return the single discovered surface ID, if the payload is unambiguous."""
    surface_ids = extract_surface_ids(messages)
    if len(surface_ids) != 1:
        return None
    return surface_ids[0]


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
    gap: str | int | float = "8px",
) -> dict[str, Any]:
    """Build an A2UI ``Column`` layout component."""
    child_ids = [c["id"] for c in children]
    normalized_gap = _normalize_gap_payload(gap) or "8px"
    return {
        "id": _new_id(),
        "component": {"Column": {"gap": normalized_gap, "children": {"explicitList": child_ids}}},
    }


def row_component(
    children: list[dict[str, Any]],
    *,
    gap: str | int | float = "8px",
) -> dict[str, Any]:
    """Build an A2UI ``Row`` layout component."""
    child_ids = [c["id"] for c in children]
    normalized_gap = _normalize_gap_payload(gap) or "8px"
    return {
        "id": _new_id(),
        "component": {"Row": {"gap": normalized_gap, "children": {"explicitList": child_ids}}},
    }


def text_field_component(
    label: str,
    action_id: str,
    *,
    placeholder: str = "",
    value: str = "",
) -> dict[str, Any]:
    """Build an A2UI ``TextField`` input component.

    The ``action_id`` argument is normalized into the TextField's bound data path
    for compatibility with earlier callers that used it as a logical field name.
    To seed an initial value in the data model, pair this component with a
    ``data_model_update()`` envelope for the same path.
    """
    text_binding: dict[str, str] = {
        "path": _normalize_data_path(action_id),
    }
    if value:
        text_binding["literalString"] = value
    return {
        "id": _new_id(),
        "component": {
            "TextField": {
                "label": _str_val(label),
                "text": text_binding,
                **({"placeholder": placeholder} if placeholder else {}),
            },
        },
    }


def image_component(
    url: str,
    *,
    usage_hint: str | None = None,
    fit: str | None = None,
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build an A2UI ``Image`` component."""
    props: dict[str, Any] = {"url": _str_val(url)}
    if usage_hint:
        props["usageHint"] = usage_hint
    if fit:
        props["fit"] = fit
    if style:
        props["style"] = style
    return {
        "id": _new_id(),
        "component": {"Image": props},
    }


def checkbox_component(
    label: str,
    action_id: str,
    *,
    checked: bool | None = None,
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ``Checkbox`` component backed by A2UI's ``CheckBox`` renderer."""
    value: dict[str, Any] = {"path": _normalize_data_path(action_id)}
    if checked is not None:
        value["literalBoolean"] = checked
    props: dict[str, Any] = {
        "label": _str_val(label),
        "value": value,
    }
    if style:
        props["style"] = style
    return {
        "id": _new_id(),
        "component": {"Checkbox": props},
    }


def _normalize_choice_options(
    options: list[str] | list[tuple[str, str]] | list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Normalize helper input into A2UI choice option records."""
    normalized: list[dict[str, Any]] = []
    for option in options:
        if isinstance(option, str):
            normalized.append({"label": _str_val(option), "value": option})
            continue
        if isinstance(option, tuple) and len(option) == 2:
            label, value = option
            normalized.append({"label": _str_val(label), "value": value})
            continue
        if isinstance(option, dict) and _is_non_empty_string(option.get("value")):
            dict_label = option.get("label")
            normalized.append(
                {
                    "label": _str_val(str(dict_label))
                    if isinstance(dict_label, str)
                    else _str_val(str(option["value"])),
                    "value": str(option["value"]),
                }
            )
            continue
        raise ValueError(
            "Choice options must be strings, (label, value) tuples, or {label, value} dicts."
        )
    return normalized


def select_component(
    label: str,
    action_id: str,
    options: list[str] | list[tuple[str, str]] | list[dict[str, str]],
    *,
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ``Select`` component backed by A2UI's ``MultipleChoice`` renderer."""
    props: dict[str, Any] = {
        "description": _str_val(label),
        "options": _normalize_choice_options(options),
        "selections": {"path": _normalize_data_path(action_id)},
    }
    if style:
        props["style"] = style
    return {
        "id": _new_id(),
        "component": {"Select": props},
    }


def radio_component(
    label: str,
    action_id: str,
    options: list[str] | list[tuple[str, str]] | list[dict[str, str]],
    *,
    value: str | None = None,
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ``Radio`` component with scalar value binding."""
    binding: dict[str, Any] = {"path": _normalize_data_path(action_id)}
    if value is not None:
        binding["literalString"] = value
    props: dict[str, Any] = {
        "description": _str_val(label),
        "options": _normalize_choice_options(options),
        "value": binding,
    }
    if style:
        props["style"] = style
    return {
        "id": _new_id(),
        "component": {"Radio": props},
    }


def tabs_component(
    tab_items: list[tuple[str, str]] | list[dict[str, str]],
    *,
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ``Tabs`` component."""
    normalized_items: list[dict[str, Any]] = []
    for item in tab_items:
        if isinstance(item, tuple) and len(item) == 2:
            title, child = item
            normalized_items.append({"title": _str_val(title), "child": child})
            continue
        if (
            isinstance(item, dict)
            and isinstance(item.get("title"), str)
            and _is_non_empty_string(item.get("child"))
        ):
            normalized_items.append(
                {
                    "title": _str_val(str(item["title"])),
                    "child": str(item["child"]),
                }
            )
            continue
        raise ValueError("Tabs items must be (title, child_id) tuples or {title, child} dicts.")

    props: dict[str, Any] = {"tabItems": normalized_items}
    if style:
        props["style"] = style
    return {"id": _new_id(), "component": {"Tabs": props}}


def modal_component(
    entry_point_child_id: str,
    content_child_id: str,
    *,
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ``Modal`` component."""
    props: dict[str, Any] = {
        "entryPointChild": entry_point_child_id,
        "contentChild": content_child_id,
    }
    if style:
        props["style"] = style
    return {"id": _new_id(), "component": {"Modal": props}}


def _cell_value(value: object) -> dict[str, object]:
    """Normalize a table/progress helper value into a literal wrapper."""
    if isinstance(value, dict) and any(
        key in value
        for key in ("path", "literalString", "literalNumber", "literalBoolean", "literal")
    ):
        return dict(value)
    if isinstance(value, bool):
        return {"literalBoolean": value}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"literalNumber": value}
    return {"literalString": str(value)}


def table_component(
    columns: list[str] | list[dict[str, str]],
    rows: list[list[object]] | list[dict[str, object]],
    *,
    caption: str | None = None,
    empty_text: str | None = None,
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ``Table`` component."""
    normalized_columns: list[dict[str, Any]] = []
    for column in columns:
        if isinstance(column, str):
            normalized_columns.append({"header": _str_val(column)})
            continue
        if isinstance(column, dict) and isinstance(column.get("header"), str):
            normalized_column: dict[str, Any] = {"header": _str_val(str(column["header"]))}
            align = column.get("align")
            if isinstance(align, str) and align in {"left", "center", "right"}:
                normalized_column["align"] = align
            normalized_columns.append(normalized_column)
            continue
        raise ValueError("Table columns must be strings or {header, align?} dicts.")

    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        raw_cells = row.get("cells") if isinstance(row, dict) else row
        if not isinstance(raw_cells, list):
            raise ValueError("Table rows must be arrays or {cells: [...]} dicts.")
        normalized_row: dict[str, Any] = {"cells": [_cell_value(cell) for cell in raw_cells]}
        if isinstance(row, dict) and isinstance(row.get("key"), str):
            normalized_row["key"] = row["key"]
        normalized_rows.append(normalized_row)

    props: dict[str, Any] = {
        "columns": normalized_columns,
        "rows": normalized_rows,
    }
    if caption:
        props["caption"] = _str_val(caption)
    if empty_text:
        props["emptyText"] = _str_val(empty_text)
    if style:
        props["style"] = style
    return {"id": _new_id(), "component": {"Table": props}}


def progress_component(
    *,
    value: int | float | None = None,
    value_path: str | None = None,
    label: str | None = None,
    max_value: int | float | None = 100,
    max_path: str | None = None,
    tone: str | None = None,
    show_value: bool = True,
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ``Progress`` component."""
    progress_value: dict[str, object]
    if value_path:
        progress_value = {"path": _normalize_data_path(value_path)}
        if value is not None:
            progress_value["literalNumber"] = value
    elif value is not None:
        progress_value = {"literalNumber": value}
    else:
        raise ValueError("Progress requires value or value_path.")

    props: dict[str, Any] = {"value": progress_value, "showValue": show_value}
    if label:
        props["label"] = _str_val(label)
    if max_path:
        max_payload: dict[str, object] = {"path": _normalize_data_path(max_path)}
        if max_value is not None:
            max_payload["literalNumber"] = max_value
        props["max"] = max_payload
    elif max_value is not None:
        props["max"] = {"literalNumber": max_value}
    if tone:
        props["tone"] = tone
    if style:
        props["style"] = style
    return {"id": _new_id(), "component": {"Progress": props}}


def badge_component(
    text: str,
    *,
    tone: str = "neutral",
    style: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ``Badge`` component, normalized to styled Text on the frontend."""
    props: dict[str, Any] = {
        "text": _str_val(text),
        "tone": tone,
    }
    if style:
        props["style"] = style
    return {
        "id": _new_id(),
        "component": {"Badge": props},
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
    contents: list[dict[str, object]] | list[object] | dict[str, object] | object,
    *,
    path: str = "/",
) -> dict[str, Any]:
    """Build a ``dataModelUpdate`` JSONL envelope.

    Plain Python objects are normalized into A2UI ValueMap entries so the
    envelope matches the v0.8 data model contract.
    """
    return {
        "dataModelUpdate": {
            "surfaceId": surface_id,
            "path": path,
            "contents": _normalize_data_model_contents(contents),
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
