"""Tests for HITLCardBuilder."""
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
        assert actions[0]["value"]["response_data"]["answer"] == "Postgres"
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
        assert actions[0]["value"]["response_data"]["action"] == "allow"
        assert actions[1]["value"]["response_data"]["action"] == "deny"

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
        content = card["elements"][0]["content"]
        assert "GITHUB_TOKEN" in content
        assert "GITHUB_ORG" in content
        assert "github_api" in content

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
        assert actions[0]["value"]["response_data"]["answer"] == "a"

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
