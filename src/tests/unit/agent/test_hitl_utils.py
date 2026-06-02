"""Unit tests for HITL utility helpers."""

from types import SimpleNamespace

import pytest

from src.configuration.config import get_settings
from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestType
from src.infrastructure.agent.hitl import utils as hitl_utils
from src.infrastructure.agent.hitl.utils import (
    build_hitl_request_data_from_record,
    deserialize_hitl_stream_response,
    restore_persisted_hitl_response,
    serialize_hitl_stream_response,
    summarize_hitl_response,
    unseal_hitl_response_data,
)


def _set_hitl_encryption_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LLM_ENCRYPTION_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
def test_build_hitl_request_data_from_record_handles_a2ui_action() -> None:
    hitl_request = HITLRequest(
        id="req-a2ui",
        request_type=HITLRequestType.A2UI_ACTION,
        conversation_id="conv-1",
        tenant_id="tenant-1",
        project_id="project-1",
        question="Choose an action",
        metadata={"title": "Review artifact"},
    )

    request_data = build_hitl_request_data_from_record(hitl_request)

    assert request_data["_request_id"] == "req-a2ui"
    assert request_data["title"] == "Review artifact"


@pytest.mark.unit
def test_build_hitl_request_data_from_record_uses_metadata_hitl_type() -> None:
    hitl_request = HITLRequest(
        id="req-permission",
        request_type=HITLRequestType.CLARIFICATION,
        conversation_id="conv-1",
        tenant_id="tenant-1",
        project_id="project-1",
        question="Fallback question",
        metadata={
            "hitl_type": "permission",
            "description": "Allow tool execution?",
            "action": "allow",
        },
    )

    request_data = build_hitl_request_data_from_record(hitl_request)

    assert request_data["_request_id"] == "req-permission"
    assert request_data["description"] == "Allow tool execution?"
    assert request_data["action"] == "allow"


@pytest.mark.unit
def test_summarize_hitl_response_keeps_bare_env_var_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_hitl_encryption_env(monkeypatch)
    summary, metadata = summarize_hitl_response(
        "env_var",
        {"OPENAI_API_KEY": "secret", "INVALID-NAME": "ignored"},
    )

    assert summary == "[redacted env var response]"
    assert metadata["value_count"] == 1
    assert metadata["variable_names"] == ["OPENAI_API_KEY"]
    assert unseal_hitl_response_data(metadata) == {
        "OPENAI_API_KEY": "secret",
        "INVALID-NAME": "ignored",
    }
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
def test_summarize_hitl_response_marks_env_var_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_hitl_encryption_env(monkeypatch)
    summary, metadata = summarize_hitl_response("env_var", {"cancelled": True})

    assert summary == "[cancelled env var response]"
    assert metadata["cancelled"] is True
    assert metadata["value_count"] == 0
    assert metadata["variable_names"] == []
    assert unseal_hitl_response_data(metadata) == {"cancelled": True}
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
def test_hitl_stream_response_round_trips_encrypted_env_var_payload(monkeypatch) -> None:
    _set_hitl_encryption_env(monkeypatch)
    payload = serialize_hitl_stream_response(
        "env_var",
        {"values": {"OPENAI_API_KEY": "super-secret"}, "save": True},
    )

    assert "response_data" not in payload
    assert "response_data_encrypted" in payload

    decoded = deserialize_hitl_stream_response(payload, expected_hitl_type="env_var")

    assert decoded == {"values": {"OPENAI_API_KEY": "super-secret"}, "save": True}
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
def test_hitl_stream_response_round_trips_encrypted_a2ui_payload(monkeypatch) -> None:
    _set_hitl_encryption_env(monkeypatch)
    payload = serialize_hitl_stream_response(
        "a2ui_action",
        {
            "action_name": "approve",
            "source_component_id": "toolbar",
            "context": {"tab": "details", "approved": True},
        },
    )

    assert "response_data" not in payload
    assert "response_data_encrypted" in payload

    decoded = deserialize_hitl_stream_response(payload, expected_hitl_type="a2ui_action")

    assert decoded == {
        "action_name": "approve",
        "source_component_id": "toolbar",
        "context": {"tab": "details", "approved": True},
    }
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
def test_hitl_stream_response_decodes_legacy_plain_payload() -> None:
    decoded = deserialize_hitl_stream_response({"response_data": '{"answer":"ok"}'})

    assert decoded == {"answer": "ok"}


@pytest.mark.unit
def test_hitl_stream_response_rejects_plain_env_var_payload() -> None:
    with pytest.raises(ValueError, match="encrypted payloads"):
        deserialize_hitl_stream_response(
            {
                "response_data": '{"values":{"OPENAI_API_KEY":"secret"}}',
            },
            expected_hitl_type="env_var",
        )


@pytest.mark.unit
def test_hitl_stream_response_rejects_plain_a2ui_payload() -> None:
    with pytest.raises(ValueError, match="encrypted payloads"):
        deserialize_hitl_stream_response(
            {
                "response_data": (
                    '{"action_name":"approve","source_component_id":"toolbar","context":{}}'
                ),
            },
            expected_hitl_type="a2ui_action",
        )


@pytest.mark.unit
def test_restore_persisted_hitl_response_recovers_sealed_env_var_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_hitl_encryption_env(monkeypatch)
    summary, metadata = summarize_hitl_response(
        "env_var",
        {"values": {"OPENAI_API_KEY": "secret"}, "save": True},
    )
    hitl_request = SimpleNamespace(
        id="req-env",
        request_type=SimpleNamespace(value="env_var"),
        question="Provide credentials",
        options=[],
        context={},
        metadata={"hitl_type": "env_var"},
        response=summary,
        response_metadata=metadata,
    )

    restored = restore_persisted_hitl_response(hitl_request)

    assert restored == {"values": {"OPENAI_API_KEY": "secret"}, "save": True}
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
def test_summarize_and_restore_a2ui_action_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_hitl_encryption_env(monkeypatch)
    summary, metadata = summarize_hitl_response(
        "a2ui_action",
        {
            "action_name": "approve",
            "source_component_id": "toolbar",
            "context": {"tab": "details", "form": {"approved": True, "reason": "looks good"}},
        },
    )
    hitl_request = SimpleNamespace(
        id="req-a2ui",
        request_type=SimpleNamespace(value="a2ui_action"),
        question="Choose",
        options=[],
        context={},
        metadata={"hitl_type": "a2ui_action"},
        response=summary,
        response_metadata=metadata,
    )

    restored = restore_persisted_hitl_response(hitl_request)

    assert summary == "approve"
    assert metadata["source_component_id"] == "toolbar"
    assert metadata["context"] == {"tab": "details"}
    assert restored == {
        "action_name": "approve",
        "source_component_id": "toolbar",
        "context": {"tab": "details", "form": {"approved": True, "reason": "looks good"}},
    }
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
def test_missing_hitl_state_is_permanent_resume_error() -> None:
    assert hitl_utils.is_permanent_hitl_resume_error("HITL state not found or expired") is True
    assert hitl_utils.is_permanent_hitl_resume_error("temporary transport error") is False
