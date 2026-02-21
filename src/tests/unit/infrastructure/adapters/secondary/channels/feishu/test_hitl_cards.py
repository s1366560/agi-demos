"""Tests for HITLCardBuilder."""
import json

import pytest

from src.infrastructure.adapters.secondary.channels.feishu.hitl_cards import (
    HITLCardBuilder,
)


@pytest.fixture
def builder() -> HITLCardBuilder:
    return HITLCardBuilder()


@pytest.mark.unit
class TestHITLCardBuilder:
    def test_clarification_card_with_options(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card(
            "clarification_asked", "req-1",
            {"question": "Which DB?", "options": ["Postgres", "MySQL"]},
        )
        assert card is not None
        assert card["header"]["template"] == "blue"
        assert card["header"]["title"]["content"] == "Agent needs clarification"
        assert len(card["elements"]) == 2
        actions = card["elements"][1]["actions"]
        assert len(actions) == 2
        assert actions[0]["value"]["hitl_request_id"] == "req-1"
        assert actions[0]["value"]["response_data"] == json.dumps({"answer": "Postgres"})
        assert actions[0]["type"] == "primary"
        assert actions[1]["type"] == "default"

    def test_clarification_card_no_options(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card(
            "clarification", "req-2",
            {"question": "What color?"},
        )
        assert card is not None
        assert len(card["elements"]) == 1  # Just markdown, no actions

    def test_clarification_card_empty_question(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card("clarification", "req-3", {"question": ""})
        assert card is None

    def test_decision_card_with_risk(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card(
            "decision_asked", "req-4",
            {
                "question": "Delete production DB?",
                "options": ["Yes", "No"],
                "risk_level": "high",
            },
        )
        assert card is not None
        assert card["header"]["template"] == "orange"
        content = card["elements"][0]["content"]
        assert "Risk: high" in content
        assert "Delete production DB?" in content

    def test_decision_card_without_risk(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card(
            "decision", "req-5",
            {"question": "Which approach?", "options": ["A", "B"]},
        )
        assert card is not None
        content = card["elements"][0]["content"]
        assert "Risk" not in content

    def test_permission_card(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card(
            "permission_asked", "req-6",
            {"tool_name": "terminal", "description": "Execute shell command"},
        )
        assert card is not None
        assert card["header"]["template"] == "red"
        assert card["header"]["title"]["content"] == "Permission Request"
        actions = card["elements"][1]["actions"]
        assert len(actions) == 2
        assert actions[0]["text"]["content"] == "Allow"
        assert actions[0]["type"] == "primary"
        assert actions[1]["text"]["content"] == "Deny"
        assert actions[1]["type"] == "danger"
        assert actions[0]["value"]["response_data"] == json.dumps({"action": "allow"})
        assert actions[1]["value"]["response_data"] == json.dumps({"action": "deny"})

    def test_env_var_card(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card(
            "env_var_requested", "req-7",
            {
                "tool_name": "github_api",
                "fields": [
                    {"name": "GITHUB_TOKEN", "description": "Personal access token"},
                    {"name": "GITHUB_ORG", "description": "Organization name"},
                ],
                "message": "GitHub credentials needed",
            },
        )
        assert card is not None
        assert card["header"]["template"] == "yellow"
        # Description markdown
        content = card["elements"][0]["content"]
        assert "github_api" in content
        # Form container with input fields
        form = card["elements"][1]
        assert form["tag"] == "form"
        inputs = [e for e in form["elements"] if e["tag"] == "input"]
        assert len(inputs) == 2
        assert inputs[0]["name"] == "GITHUB_TOKEN"
        assert inputs[1]["name"] == "GITHUB_ORG"
        # Submit button
        submit = [e for e in form["elements"] if e.get("action_type") == "form_submit"]
        assert len(submit) == 1

    def test_env_var_card_empty(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card("env_var", "req-8", {})
        assert card is None

    def test_unknown_type_returns_none(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card("unknown_type", "req-9", {"question": "?"})
        assert card is None

    def test_option_buttons_limit(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card(
            "clarification", "req-10",
            {"question": "Pick", "options": [f"opt{i}" for i in range(10)]},
        )
        assert card is not None
        actions = card["elements"][1]["actions"]
        assert len(actions) == 5  # Max 5 buttons

    def test_dict_options(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card(
            "decision", "req-11",
            {
                "question": "Pick",
                "options": [
                    {"label": "Option A", "value": "a"},
                    {"label": "Option B", "value": "b"},
                ],
            },
        )
        assert card is not None
        actions = card["elements"][1]["actions"]
        assert actions[0]["text"]["content"] == "Option A"
        assert actions[0]["value"]["response_data"] == json.dumps({"answer": "a"})

    def test_buttons_include_hitl_type(self, builder: HITLCardBuilder) -> None:
        """All buttons should include hitl_type in their value payload."""
        card = builder.build_card(
            "decision_asked", "req-12",
            {"question": "Which?", "options": ["A", "B"]},
        )
        assert card is not None
        actions = card["elements"][1]["actions"]
        for action in actions:
            assert action["value"]["hitl_type"] == "decision"

    def test_permission_buttons_include_hitl_type(self, builder: HITLCardBuilder) -> None:
        """Permission Allow/Deny buttons should include hitl_type."""
        card = builder.build_card(
            "permission_asked", "req-13",
            {"tool_name": "terminal"},
        )
        assert card is not None
        actions = card["elements"][1]["actions"]
        assert actions[0]["value"]["hitl_type"] == "permission"
        assert actions[1]["value"]["hitl_type"] == "permission"

    def test_build_responded_card_decision(self, builder: HITLCardBuilder) -> None:
        """build_responded_card should return green confirmation card."""
        card = builder.build_responded_card("decision", "Option A")
        assert card is not None
        assert card["header"]["template"] == "green"
        assert card["header"]["title"]["content"] == "Decision Made"
        assert "**Selected**: Option A" in card["elements"][0]["content"]
        assert "submitted" in card["elements"][0]["content"].lower()

    def test_build_responded_card_clarification(self, builder: HITLCardBuilder) -> None:
        card = builder.build_responded_card("clarification_asked", "PostgreSQL")
        assert card["header"]["title"]["content"] == "Clarification Responded"

    def test_build_responded_card_no_label(self, builder: HITLCardBuilder) -> None:
        card = builder.build_responded_card("permission")
        assert "Selected" not in card["elements"][0]["content"]
        assert "submitted" in card["elements"][0]["content"].lower()


@pytest.mark.unit
class TestHITLCardBuilderCardKit:
    """Tests for CardKit-compatible card entity builders."""

    def test_build_card_entity_data_clarification(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card_entity_data(
            "clarification_asked", "req-ck1",
            {"question": "Which DB?"},
        )
        assert card is not None
        assert card["schema"] == "2.0"
        assert card["config"]["update_multi"] is True
        assert card["header"]["template"] == "blue"
        body_elements = card["body"]["elements"]
        assert len(body_elements) == 1
        assert body_elements[0]["tag"] == "markdown"
        assert body_elements[0]["content"] == "Which DB?"
        assert body_elements[0]["element_id"].startswith("hitl_q_")

    def test_build_card_entity_data_decision_with_risk(
        self, builder: HITLCardBuilder
    ) -> None:
        card = builder.build_card_entity_data(
            "decision", "req-ck2",
            {"question": "Delete prod?", "risk_level": "high"},
        )
        assert card is not None
        assert card["header"]["template"] == "orange"
        assert "Risk: high" in card["body"]["elements"][0]["content"]

    def test_build_card_entity_data_permission(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card_entity_data(
            "permission_asked", "req-ck3",
            {"tool_name": "terminal", "description": "Run shell"},
        )
        assert card is not None
        assert card["header"]["template"] == "red"
        assert "terminal" in card["body"]["elements"][0]["content"]

    def test_build_card_entity_data_env_var(self, builder: HITLCardBuilder) -> None:
        card = builder.build_card_entity_data(
            "env_var_requested", "req-ck4",
            {"tool_name": "github", "fields": [{"name": "TOKEN", "description": "PAT"}]},
        )
        assert card is not None
        assert card["header"]["template"] == "yellow"
        assert "github" in card["body"]["elements"][0]["content"]

    def test_build_card_entity_data_empty_returns_none(
        self, builder: HITLCardBuilder
    ) -> None:
        assert builder.build_card_entity_data("clarification", "req-ck5", {}) is None
        assert builder.build_card_entity_data("unknown_type", "req-ck6", {}) is None

    def test_build_hitl_action_elements_options(
        self, builder: HITLCardBuilder
    ) -> None:
        elements = builder.build_hitl_action_elements(
            "clarification", "req-ck7",
            {"options": ["PostgreSQL", "MySQL"]},
        )
        assert len(elements) == 2
        assert elements[0]["tag"] == "button"
        assert elements[0]["element_id"].startswith("hitl_btn_")
        assert elements[0]["type"] == "primary"
        assert elements[0]["value"]["hitl_request_id"] == "req-ck7"
        assert elements[0]["value"]["hitl_type"] == "clarification"
        assert elements[0]["value"]["response_data"] == json.dumps({"answer": "PostgreSQL"})
        assert elements[1]["type"] == "default"

    def test_build_hitl_action_elements_permission(
        self, builder: HITLCardBuilder
    ) -> None:
        elements = builder.build_hitl_action_elements(
            "permission_asked", "req-ck8", {},
        )
        assert len(elements) == 2
        assert elements[0]["text"]["content"] == "Allow"
        assert elements[0]["type"] == "primary"
        assert elements[1]["text"]["content"] == "Deny"
        assert elements[1]["type"] == "danger"

    def test_build_hitl_action_elements_no_options(
        self, builder: HITLCardBuilder
    ) -> None:
        elements = builder.build_hitl_action_elements(
            "clarification", "req-ck9", {"question": "What?"},
        )
        assert elements == []

    def test_build_hitl_action_elements_env_var_form(
        self, builder: HITLCardBuilder
    ) -> None:
        elements = builder.build_hitl_action_elements(
            "env_var", "req-ck10",
            {"fields": [{"name": "API_KEY", "description": "Key", "required": True}]},
        )
        assert len(elements) == 1
        form = elements[0]
        assert form["tag"] == "form"
        inputs = [e for e in form["elements"] if e["tag"] == "input"]
        assert len(inputs) == 1
        assert inputs[0]["name"] == "API_KEY"
        assert inputs[0]["required"] is True
        submit = [e for e in form["elements"] if e.get("action_type") == "form_submit"]
        assert len(submit) == 1
        assert submit[0]["value"]["hitl_request_id"] == "req-ck10"
        assert submit[0]["value"]["hitl_type"] == "env_var"

    def test_build_hitl_action_elements_env_var_empty(
        self, builder: HITLCardBuilder
    ) -> None:
        elements = builder.build_hitl_action_elements(
            "env_var", "req-ck11", {"fields": []},
        )
        assert elements == []

    def test_build_hitl_action_elements_dict_options(
        self, builder: HITLCardBuilder
    ) -> None:
        elements = builder.build_hitl_action_elements(
            "decision", "req-ck11",
            {"options": [{"label": "A", "value": "a"}, {"label": "B", "value": "b"}]},
        )
        assert len(elements) == 2
        assert elements[0]["text"]["content"] == "A"
        assert elements[0]["value"]["response_data"] == json.dumps({"answer": "a"})

    def test_build_hitl_action_elements_max_5(
        self, builder: HITLCardBuilder
    ) -> None:
        elements = builder.build_hitl_action_elements(
            "clarification", "req-ck12",
            {"options": [f"opt{i}" for i in range(10)]},
        )
        assert len(elements) == 5

    def test_wrap_card_v2_structure(self, builder: HITLCardBuilder) -> None:
        card = builder._wrap_card_v2(
            title="Test", template="blue",
            elements=[{"tag": "markdown", "content": "hello"}],
        )
        assert card["schema"] == "2.0"
        assert card["config"]["update_multi"] is True
        assert card["body"]["direction"] == "vertical"
        assert card["body"]["elements"][0]["content"] == "hello"
