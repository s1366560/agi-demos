"""Unit tests for the A2UI JSONL message builder.

Validates that component helpers emit the correct v0.8 ComponentInstance
format and that envelope constructors produce valid A2UI message shapes.
"""

from __future__ import annotations

import json

from src.infrastructure.agent.canvas.a2ui_builder import (
    begin_rendering,
    button_component,
    card_component,
    column_component,
    data_model_update,
    delete_surface,
    divider_component,
    pack_messages,
    row_component,
    surface_update,
    text_component,
    text_field_component,
)

# ---------------------------------------------------------------------------
# Component helpers — v0.8 format: {id, component: {TypeName: {props}}}
# ---------------------------------------------------------------------------


class TestTextComponent:
    """Tests for text_component()."""

    def test_basic_text(self) -> None:
        comp = text_component("hello")
        assert isinstance(comp["id"], str)
        assert len(comp["id"]) == 12
        assert "component" in comp
        assert "Text" in comp["component"]
        assert comp["component"]["Text"]["text"] == {"literal": "hello"}

    def test_text_with_style(self) -> None:
        comp = text_component("styled", style={"color": "red", "fontSize": "16px"})
        text_props = comp["component"]["Text"]
        assert text_props["text"] == {"literal": "styled"}
        assert text_props["style"] == {"color": "red", "fontSize": "16px"}

    def test_no_legacy_type_field(self) -> None:
        comp = text_component("test")
        assert "type" not in comp
        assert "props" not in comp


class TestButtonComponent:
    """Tests for button_component()."""

    def test_basic_button(self) -> None:
        btn, label_text = button_component("Click me", "btn_action")
        assert "component" in btn
        assert "Button" in btn["component"]
        btn_props = btn["component"]["Button"]
        assert btn_props["child"] == label_text["id"]
        assert btn_props["action"] == {"name": "btn_action"}
        # Label text is a valid Text component
        assert label_text["component"]["Text"]["text"] == {"literal": "Click me"}

    def test_button_with_style(self) -> None:
        btn, _label = button_component("OK", "ok_action", style={"width": "100px"})
        btn_props = btn["component"]["Button"]
        assert btn_props["style"] == {"width": "100px"}

    def test_button_returns_tuple(self) -> None:
        result = button_component("X", "x")
        assert isinstance(result, tuple)
        assert len(result) == 2
        btn, label_text = result
        assert "id" in btn
        assert "id" in label_text

    def test_no_legacy_fields(self) -> None:
        btn, _label = button_component("X", "x")
        assert "type" not in btn
        assert "props" not in btn
        assert "label" not in btn["component"]["Button"]
        assert "onPress" not in btn["component"]["Button"]
        assert "variant" not in btn["component"]["Button"]


class TestCardComponent:
    """Tests for card_component()."""

    def test_card_with_children(self) -> None:
        child1 = text_component("item 1")
        child2 = text_component("item 2")
        card = card_component([child1, child2], title="My Card")
        assert "component" in card
        assert "Card" in card["component"]
        card_props = card["component"]["Card"]
        assert card_props["title"] == "My Card"
        assert card_props["children"] == {"explicitList": [child1["id"], child2["id"]]}

    def test_card_without_title(self) -> None:
        child = text_component("solo")
        card = card_component([child])
        card_props = card["component"]["Card"]
        assert "title" not in card_props
        assert card_props["children"] == {"explicitList": [child["id"]]}

    def test_card_with_style(self) -> None:
        child = text_component("styled child")
        card = card_component([child], style={"padding": "16px"})
        card_props = card["component"]["Card"]
        assert card_props["style"] == {"padding": "16px"}

    def test_no_legacy_children_field(self) -> None:
        child = text_component("x")
        card = card_component([child])
        # Children should only be inside the component dict, not at top level
        assert "children" not in card


class TestColumnComponent:
    """Tests for column_component()."""

    def test_column_layout(self) -> None:
        child1 = text_component("row 1")
        child2 = text_component("row 2")
        col = column_component([child1, child2])
        assert "component" in col
        assert "Column" in col["component"]
        col_props = col["component"]["Column"]
        assert col_props["gap"] == "8px"
        assert col_props["children"] == {"explicitList": [child1["id"], child2["id"]]}

    def test_custom_gap(self) -> None:
        child = text_component("x")
        col = column_component([child], gap="16px")
        assert col["component"]["Column"]["gap"] == "16px"

    def test_no_legacy_fields(self) -> None:
        child = text_component("x")
        col = column_component([child])
        assert "type" not in col
        assert "props" not in col
        assert "children" not in col


class TestRowComponent:
    """Tests for row_component()."""

    def test_row_layout(self) -> None:
        child1 = text_component("col 1")
        child2 = text_component("col 2")
        row = row_component([child1, child2])
        assert "component" in row
        assert "Row" in row["component"]
        row_props = row["component"]["Row"]
        assert row_props["gap"] == "8px"
        assert row_props["children"] == {"explicitList": [child1["id"], child2["id"]]}


class TestTextFieldComponent:
    """Tests for text_field_component()."""

    def test_basic_field(self) -> None:
        comp = text_field_component("Name", "name_change")
        assert "component" in comp
        assert "TextField" in comp["component"]
        field = comp["component"]["TextField"]
        assert field["label"] == {"literal": "Name"}
        assert field["onChange"] == {"name": "name_change"}
        assert field["placeholder"] == ""
        assert field["value"] == ""

    def test_field_with_defaults(self) -> None:
        comp = text_field_component(
            "Email", "email_change", placeholder="you@example.com", value="test@test.com"
        )
        field = comp["component"]["TextField"]
        assert field["placeholder"] == "you@example.com"
        assert field["value"] == "test@test.com"

    def test_no_legacy_fields(self) -> None:
        comp = text_field_component("X", "x")
        assert "type" not in comp
        assert "props" not in comp


class TestDividerComponent:
    """Tests for divider_component()."""

    def test_divider(self) -> None:
        comp = divider_component()
        assert "component" in comp
        assert "Divider" in comp["component"]
        assert comp["component"]["Divider"] == {}

    def test_no_legacy_fields(self) -> None:
        comp = divider_component()
        assert "type" not in comp
        assert "props" not in comp


# ---------------------------------------------------------------------------
# Envelope constructors
# ---------------------------------------------------------------------------


class TestSurfaceUpdate:
    """Tests for surface_update()."""

    def test_envelope_shape(self) -> None:
        comps = [text_component("hi")]
        envelope = surface_update("surf-1", comps)
        assert "surfaceUpdate" in envelope
        assert envelope["surfaceUpdate"]["surfaceId"] == "surf-1"
        assert envelope["surfaceUpdate"]["components"] == comps


class TestDataModelUpdate:
    """Tests for data_model_update()."""

    def test_default_path(self) -> None:
        contents = [{"key": "value"}]
        envelope = data_model_update("surf-1", contents)
        assert envelope["dataModelUpdate"]["path"] == "/"
        assert envelope["dataModelUpdate"]["contents"] == contents

    def test_custom_path(self) -> None:
        envelope = data_model_update("surf-1", [{"x": 1}], path="/items")
        assert envelope["dataModelUpdate"]["path"] == "/items"


class TestBeginRendering:
    """Tests for begin_rendering()."""

    def test_basic(self) -> None:
        envelope = begin_rendering("surf-1", "root-id")
        assert envelope["beginRendering"]["surfaceId"] == "surf-1"
        assert envelope["beginRendering"]["root"] == "root-id"
        assert "styles" not in envelope["beginRendering"]

    def test_with_styles(self) -> None:
        envelope = begin_rendering("surf-1", "root-id", styles={"primaryColor": "#000"})
        assert envelope["beginRendering"]["styles"] == {"primaryColor": "#000"}


class TestDeleteSurface:
    """Tests for delete_surface()."""

    def test_envelope(self) -> None:
        envelope = delete_surface("surf-1")
        assert envelope["deleteSurface"]["surfaceId"] == "surf-1"


# ---------------------------------------------------------------------------
# pack_messages
# ---------------------------------------------------------------------------


class TestPackMessages:
    """Tests for pack_messages()."""

    def test_single_message(self) -> None:
        msg = begin_rendering("s1", "root")
        result = pack_messages([msg])
        parsed = json.loads(result)
        assert "beginRendering" in parsed

    def test_multiple_messages(self) -> None:
        msgs = [
            begin_rendering("s1", "root"),
            surface_update("s1", [text_component("hi")]),
        ]
        result = pack_messages(msgs)
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert "beginRendering" in json.loads(lines[0])
        assert "surfaceUpdate" in json.loads(lines[1])

    def test_no_whitespace_in_json(self) -> None:
        """pack_messages uses compact separators."""
        msg = begin_rendering("s1", "root")
        result = pack_messages([msg])
        assert " " not in result  # compact JSON has no spaces


# ---------------------------------------------------------------------------
# Integration: full surface build
# ---------------------------------------------------------------------------


class TestFullSurfaceBuild:
    """End-to-end: build a surface with multiple components and pack to JSONL."""

    def test_info_card_surface(self) -> None:
        """Build a card with title, text, and a button, then pack to JSONL."""
        title = text_component("Welcome!")
        body = text_component("This is an A2UI surface rendered in MemStack.")
        action_btn, action_label = button_component("Get Started", "get_started")
        card = card_component([title, body, action_btn], title="Info Card")
        layout = column_component([card])

        surface_id = "test-surface-001"
        messages = [
            begin_rendering(surface_id, layout["id"]),
            surface_update(
                surface_id,
                [title, body, action_label, action_btn, card, layout],
            ),
        ]
        jsonl = pack_messages(messages)

        lines = jsonl.strip().split("\n")
        assert len(lines) == 2

        # Verify begin_rendering
        begin = json.loads(lines[0])
        assert begin["beginRendering"]["root"] == layout["id"]

        # Verify surface_update has all 6 components (title, body, label_text, button, card, layout)
        update = json.loads(lines[1])
        assert len(update["surfaceUpdate"]["components"]) == 6

        # Verify all components use v0.8 format
        for comp in update["surfaceUpdate"]["components"]:
            assert "id" in comp
            assert "component" in comp
            assert "type" not in comp, "Legacy 'type' field should not exist"
            assert "props" not in comp, "Legacy 'props' field should not exist"
