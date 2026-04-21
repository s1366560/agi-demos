"""Unit tests for the Workspace Task Protocol (WTP) envelope."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from src.domain.model.workspace.wtp_envelope import (
    WTP_VERSION,
    WtpEnvelope,
    WtpValidationError,
    WtpVerb,
    is_wtp_message,
)
from src.domain.ports.services.agent_message_bus_port import (
    AgentMessage,
    AgentMessageType,
)


def _ids() -> dict[str, str]:
    return {
        "workspace_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "attempt_id": str(uuid.uuid4()),
    }


@pytest.mark.unit
class TestWtpVerb:
    def test_leader_and_worker_sets_are_disjoint(self) -> None:
        leader = WtpVerb.leader_to_worker()
        worker = WtpVerb.worker_to_leader()
        assert leader & worker == frozenset()

    def test_every_verb_is_routable(self) -> None:
        leader = WtpVerb.leader_to_worker()
        worker = WtpVerb.worker_to_leader()
        assert set(WtpVerb) == leader | worker

    def test_terminal_verbs(self) -> None:
        assert WtpVerb.terminal() == {WtpVerb.TASK_COMPLETED, WtpVerb.TASK_BLOCKED}

    @pytest.mark.parametrize(
        ("verb", "expected_type"),
        [
            (WtpVerb.TASK_ASSIGN, AgentMessageType.REQUEST),
            (WtpVerb.TASK_REVISE, AgentMessageType.REQUEST),
            (WtpVerb.TASK_CLARIFY_REQUEST, AgentMessageType.REQUEST),
            (WtpVerb.TASK_CLARIFY_RESPONSE, AgentMessageType.RESPONSE),
            (WtpVerb.TASK_COMPLETED, AgentMessageType.ANNOUNCE),
            (WtpVerb.TASK_BLOCKED, AgentMessageType.ANNOUNCE),
            (WtpVerb.TASK_PROGRESS, AgentMessageType.NOTIFICATION),
            (WtpVerb.TASK_HEARTBEAT, AgentMessageType.NOTIFICATION),
            (WtpVerb.TASK_CANCEL, AgentMessageType.NOTIFICATION),
        ],
    )
    def test_default_message_type(
        self, verb: WtpVerb, expected_type: AgentMessageType
    ) -> None:
        assert verb.default_message_type() is expected_type


@pytest.mark.unit
class TestWtpEnvelopeValidation:
    def test_valid_task_assign(self) -> None:
        env = WtpEnvelope(
            verb=WtpVerb.TASK_ASSIGN,
            **_ids(),
            payload={"title": "T1", "description": "do stuff"},
        )
        assert env.verb is WtpVerb.TASK_ASSIGN
        assert env.correlation_id  # auto-generated
        assert env.extra_metadata == {}

    def test_missing_required_payload_key(self) -> None:
        with pytest.raises(WtpValidationError, match="missing required payload keys"):
            WtpEnvelope(
                verb=WtpVerb.TASK_ASSIGN,
                **_ids(),
                payload={"title": "T1"},  # description missing
            )

    def test_blank_required_string_payload(self) -> None:
        with pytest.raises(WtpValidationError, match="must not be blank"):
            WtpEnvelope(
                verb=WtpVerb.TASK_ASSIGN,
                **_ids(),
                payload={"title": "T1", "description": "   "},
            )

    def test_empty_workspace_id(self) -> None:
        ids = _ids()
        ids["workspace_id"] = ""
        with pytest.raises(WtpValidationError, match="workspace_id"):
            WtpEnvelope(
                verb=WtpVerb.TASK_PROGRESS,
                **ids,
                payload={"summary": "halfway"},
            )

    def test_heartbeat_has_no_required_payload(self) -> None:
        env = WtpEnvelope(verb=WtpVerb.TASK_HEARTBEAT, **_ids(), payload={})
        assert env.verb is WtpVerb.TASK_HEARTBEAT
        assert env.payload == {}

    def test_wrong_verb_type_rejected(self) -> None:
        with pytest.raises(WtpValidationError, match="verb must be a WtpVerb"):
            WtpEnvelope(
                verb="task.assign",  # type: ignore[arg-type]
                **_ids(),
                payload={"title": "T1", "description": "x"},
            )

    def test_root_goal_task_id_must_be_str_if_provided(self) -> None:
        with pytest.raises(WtpValidationError, match="root_goal_task_id"):
            WtpEnvelope(
                verb=WtpVerb.TASK_HEARTBEAT,
                **_ids(),
                root_goal_task_id=123,  # type: ignore[arg-type]
                payload={},
            )


@pytest.mark.unit
class TestWtpEnvelopeSerialisation:
    def test_to_metadata_includes_required_keys(self) -> None:
        ids = _ids()
        env = WtpEnvelope(
            verb=WtpVerb.TASK_PROGRESS,
            **ids,
            root_goal_task_id="root-1",
            payload={"summary": "progress 40%"},
            extra_metadata={"trace_id": "abc"},
        )
        meta = env.to_metadata()
        assert meta["wtp_version"] == WTP_VERSION
        assert meta["wtp_verb"] == "task.progress"
        assert meta["workspace_id"] == ids["workspace_id"]
        assert meta["task_id"] == ids["task_id"]
        assert meta["attempt_id"] == ids["attempt_id"]
        assert meta["correlation_id"] == env.correlation_id
        assert meta["root_goal_task_id"] == "root-1"
        assert meta["trace_id"] == "abc"  # extra_metadata preserved

    def test_to_metadata_omits_root_goal_when_none(self) -> None:
        env = WtpEnvelope(
            verb=WtpVerb.TASK_HEARTBEAT, **_ids(), payload={}
        )
        assert "root_goal_task_id" not in env.to_metadata()

    def test_to_content_is_valid_json(self) -> None:
        env = WtpEnvelope(
            verb=WtpVerb.TASK_COMPLETED,
            **_ids(),
            payload={"summary": "done", "artifacts": ["a1", "a2"]},
        )
        content = env.to_content()
        decoded = json.loads(content)
        assert decoded == {"summary": "done", "artifacts": ["a1", "a2"]}

    def test_dict_roundtrip(self) -> None:
        original = WtpEnvelope(
            verb=WtpVerb.TASK_COMPLETED,
            **_ids(),
            payload={"summary": "done", "artifacts": ["a1"]},
            extra_metadata={"x": 1},
        )
        restored = WtpEnvelope.from_dict(original.to_dict())
        assert restored.verb == original.verb
        assert restored.workspace_id == original.workspace_id
        assert restored.task_id == original.task_id
        assert restored.attempt_id == original.attempt_id
        assert restored.correlation_id == original.correlation_id
        assert restored.payload == original.payload
        assert restored.extra_metadata == original.extra_metadata


@pytest.mark.unit
class TestWtpEnvelopeAgentMessageInterop:
    def _agent_message(
        self, env: WtpEnvelope, *, from_agent: str = "leader", to_agent: str = "worker-1"
    ) -> AgentMessage:
        return AgentMessage(
            message_id=str(uuid.uuid4()),
            from_agent_id=from_agent,
            to_agent_id=to_agent,
            session_id="sess-1",
            content=env.to_content(),
            message_type=env.default_message_type(),
            timestamp=datetime.now(UTC),
            metadata=env.to_metadata(),
            parent_message_id=env.parent_message_id,
        )

    def test_roundtrip_through_agent_message(self) -> None:
        ids = _ids()
        original = WtpEnvelope(
            verb=WtpVerb.TASK_ASSIGN,
            **ids,
            payload={"title": "T1", "description": "do stuff", "success_criteria": "X"},
        )
        msg = self._agent_message(original)

        assert is_wtp_message(msg)
        restored = WtpEnvelope.from_message(msg)

        assert restored.verb == original.verb
        assert restored.workspace_id == ids["workspace_id"]
        assert restored.task_id == ids["task_id"]
        assert restored.attempt_id == ids["attempt_id"]
        assert restored.correlation_id == original.correlation_id
        assert restored.payload == original.payload
        # Reserved keys must be stripped out of extra_metadata on rehydrate.
        assert "wtp_verb" not in restored.extra_metadata
        assert "wtp_version" not in restored.extra_metadata
        assert "workspace_id" not in restored.extra_metadata

    def test_extra_metadata_preserved_through_message(self) -> None:
        env = WtpEnvelope(
            verb=WtpVerb.TASK_PROGRESS,
            **_ids(),
            payload={"summary": "50%"},
            extra_metadata={"trace_id": "t-123", "tenant_id": "ten-1"},
        )
        msg = self._agent_message(env)
        restored = WtpEnvelope.from_message(msg)
        assert restored.extra_metadata == {"trace_id": "t-123", "tenant_id": "ten-1"}

    def test_from_message_rejects_non_wtp(self) -> None:
        msg = AgentMessage(
            message_id="m1",
            from_agent_id="a",
            to_agent_id="b",
            session_id="s",
            content="hello",
            message_type=AgentMessageType.NOTIFICATION,
            metadata={"other": "x"},
        )
        assert not is_wtp_message(msg)
        with pytest.raises(WtpValidationError, match="missing wtp_verb"):
            WtpEnvelope.from_message(msg)

    def test_from_message_rejects_unknown_verb(self) -> None:
        msg = AgentMessage(
            message_id="m1",
            from_agent_id="a",
            to_agent_id="b",
            session_id="s",
            content="{}",
            message_type=AgentMessageType.NOTIFICATION,
            metadata={"wtp_verb": "task.bogus", "wtp_version": "1"},
        )
        with pytest.raises(WtpValidationError, match="unknown WTP verb"):
            WtpEnvelope.from_message(msg)

    def test_from_message_rejects_non_json_content(self) -> None:
        msg = AgentMessage(
            message_id="m1",
            from_agent_id="a",
            to_agent_id="b",
            session_id="s",
            content="not json",
            message_type=AgentMessageType.NOTIFICATION,
            metadata={
                "wtp_verb": "task.heartbeat",
                "wtp_version": "1",
                "workspace_id": "w",
                "task_id": "t",
                "attempt_id": "a",
                "correlation_id": "c",
            },
        )
        with pytest.raises(WtpValidationError, match="not valid JSON"):
            WtpEnvelope.from_message(msg)

    def test_from_message_rejects_non_object_content(self) -> None:
        msg = AgentMessage(
            message_id="m1",
            from_agent_id="a",
            to_agent_id="b",
            session_id="s",
            content="[1, 2, 3]",
            message_type=AgentMessageType.NOTIFICATION,
            metadata={
                "wtp_verb": "task.heartbeat",
                "wtp_version": "1",
                "workspace_id": "w",
                "task_id": "t",
                "attempt_id": "a",
                "correlation_id": "c",
            },
        )
        with pytest.raises(WtpValidationError, match="must decode to a dict"):
            WtpEnvelope.from_message(msg)


@pytest.mark.unit
class TestWtpEnvelopeConvenience:
    def test_is_terminal(self) -> None:
        complete = WtpEnvelope(
            verb=WtpVerb.TASK_COMPLETED, **_ids(), payload={"summary": "done"}
        )
        blocked = WtpEnvelope(
            verb=WtpVerb.TASK_BLOCKED, **_ids(), payload={"reason": "stuck"}
        )
        progress = WtpEnvelope(
            verb=WtpVerb.TASK_PROGRESS, **_ids(), payload={"summary": "50%"}
        )
        assert complete.is_terminal()
        assert blocked.is_terminal()
        assert not progress.is_terminal()

    def test_envelope_exposes_default_message_type(self) -> None:
        env = WtpEnvelope(
            verb=WtpVerb.TASK_ASSIGN,
            **_ids(),
            payload={"title": "T", "description": "D"},
        )
        assert env.default_message_type() is AgentMessageType.REQUEST
