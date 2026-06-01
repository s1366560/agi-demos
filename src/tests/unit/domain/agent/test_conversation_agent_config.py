"""Tests for conversation agent config normalization."""

from src.domain.model.agent.conversation.agent_config import (
    normalize_agent_config,
    selected_agent_id_from_config,
)


def test_selected_agent_id_prefers_canonical_key() -> None:
    config = {
        "selected_agent_id": "agent-canonical",
        "agent_definition_id": "agent-legacy",
    }

    assert selected_agent_id_from_config(config) == "agent-canonical"


def test_selected_agent_id_accepts_legacy_agent_definition_id() -> None:
    assert selected_agent_id_from_config({"agent_definition_id": "agent-legacy"}) == "agent-legacy"


def test_normalize_agent_config_removes_legacy_alias() -> None:
    normalized = normalize_agent_config(
        {
            "agent_definition_id": "agent-legacy",
            "other": "value",
        }
    )

    assert normalized == {"selected_agent_id": "agent-legacy", "other": "value"}


def test_normalize_agent_config_omits_empty_selected_agent_id() -> None:
    normalized = normalize_agent_config(
        {
            "selected_agent_id": " ",
            "agent_definition_id": "",
            "other": "value",
        }
    )

    assert normalized == {"other": "value"}
