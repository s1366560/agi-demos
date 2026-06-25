import pytest

from src.domain.model.agent.execution_backend import (
    EXECUTION_BACKEND_METADATA_KEY,
    execution_backend_from_metadata,
    metadata_with_execution_backend,
    normalize_execution_backend,
)


def test_execution_backend_defaults_to_memstack_for_legacy_metadata() -> None:
    assert execution_backend_from_metadata(None) == {"type": "memstack"}
    assert execution_backend_from_metadata({"other": "value"}) == {"type": "memstack"}


def test_execution_backend_normalizes_external_acp_agent_key() -> None:
    backend = normalize_execution_backend(
        {"type": "acp_external", "acp_agent_key": " opencode-local "}
    )

    assert backend == {"type": "acp_external", "acp_agent_key": "opencode-local"}


def test_execution_backend_rejects_invalid_external_acp_backend() -> None:
    with pytest.raises(ValueError, match="requires acp_agent_key"):
        normalize_execution_backend({"type": "acp_external"})

    with pytest.raises(ValueError, match="unsupported"):
        normalize_execution_backend({"type": "opencode"})


def test_metadata_with_execution_backend_stores_external_acp_backend() -> None:
    metadata = metadata_with_execution_backend(
        {"keep": "yes"},
        {"type": "acp_external", "acp_agent_key": "agent-a"},
    )

    assert metadata == {
        "keep": "yes",
        EXECUTION_BACKEND_METADATA_KEY: {
            "type": "acp_external",
            "acp_agent_key": "agent-a",
        },
    }


def test_metadata_with_memstack_backend_clears_external_acp_backend() -> None:
    metadata = metadata_with_execution_backend(
        {
            "keep": "yes",
            EXECUTION_BACKEND_METADATA_KEY: {
                "type": "acp_external",
                "acp_agent_key": "agent-a",
            },
        },
        {"type": "memstack"},
    )

    assert metadata == {"keep": "yes"}
