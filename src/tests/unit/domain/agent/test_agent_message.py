"""Tests for AgentMessage and AgentMessageType data classes."""

from datetime import UTC, datetime

import pytest

from src.domain.ports.services.agent_message_bus_port import (
    AgentMessage,
    AgentMessageType,
)


@pytest.mark.unit
class TestAgentMessageType:
    def test_request_value(self):
        assert AgentMessageType.REQUEST.value == "request"

    def test_response_value(self):
        assert AgentMessageType.RESPONSE.value == "response"

    def test_notification_value(self):
        assert AgentMessageType.NOTIFICATION.value == "notification"

    def test_from_string(self):
        assert AgentMessageType("request") is AgentMessageType.REQUEST
        assert AgentMessageType("response") is AgentMessageType.RESPONSE
        assert AgentMessageType("notification") is AgentMessageType.NOTIFICATION

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            AgentMessageType("invalid")

    def test_is_str_subclass(self):
        assert isinstance(AgentMessageType.REQUEST, str)
        assert AgentMessageType.REQUEST == "request"


@pytest.mark.unit
class TestAgentMessage:
    def _make_message(self, **overrides: object) -> AgentMessage:
        defaults: dict[str, object] = {
            "message_id": "msg-1",
            "from_agent_id": "agent-a",
            "to_agent_id": "agent-b",
            "session_id": "session-1",
            "content": "Hello from A",
            "message_type": AgentMessageType.REQUEST,
        }
        defaults.update(overrides)
        return AgentMessage(**defaults)  # type: ignore[arg-type]

    def test_create_message_defaults(self):
        msg = self._make_message()
        assert msg.message_id == "msg-1"
        assert msg.from_agent_id == "agent-a"
        assert msg.to_agent_id == "agent-b"
        assert msg.session_id == "session-1"
        assert msg.content == "Hello from A"
        assert msg.message_type is AgentMessageType.REQUEST
        assert isinstance(msg.timestamp, datetime)
        assert msg.metadata is None
        assert msg.parent_message_id is None

    def test_create_message_with_metadata(self):
        meta = {"key": "value", "priority": 1}
        msg = self._make_message(metadata=meta, parent_message_id="parent-1")
        assert msg.metadata == {"key": "value", "priority": 1}
        assert msg.parent_message_id == "parent-1"

    def test_message_is_mutable(self):
        msg = self._make_message()
        msg.content = "Updated"
        assert msg.content == "Updated"

    def test_to_dict_keys(self):
        msg = self._make_message()
        d = msg.to_dict()
        expected_keys = {
            "message_id",
            "from_agent_id",
            "to_agent_id",
            "session_id",
            "content",
            "message_type",
            "timestamp",
            "metadata",
            "parent_message_id",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_message_type_as_string(self):
        msg = self._make_message()
        d = msg.to_dict()
        assert d["message_type"] == "request"

    def test_to_dict_timestamp_as_iso_string(self):
        msg = self._make_message()
        d = msg.to_dict()
        assert isinstance(d["timestamp"], str)
        datetime.fromisoformat(d["timestamp"])

    def test_to_dict_metadata_none_becomes_empty_dict(self):
        msg = self._make_message(metadata=None)
        d = msg.to_dict()
        assert d["metadata"] == {}

    def test_to_dict_parent_message_id_none(self):
        msg = self._make_message()
        d = msg.to_dict()
        assert d["parent_message_id"] is None

    def test_from_dict_round_trip(self):
        original = self._make_message(
            metadata={"k": "v"},
            parent_message_id="parent-1",
        )
        d = original.to_dict()
        restored = AgentMessage.from_dict(d)

        assert restored.message_id == original.message_id
        assert restored.from_agent_id == original.from_agent_id
        assert restored.to_agent_id == original.to_agent_id
        assert restored.session_id == original.session_id
        assert restored.content == original.content
        assert restored.message_type == original.message_type
        assert restored.parent_message_id == original.parent_message_id

    def test_from_dict_minimal(self):
        d: dict[str, object] = {}
        msg = AgentMessage.from_dict(d)
        assert msg.message_id == ""
        assert msg.from_agent_id == ""
        assert msg.to_agent_id == ""
        assert msg.session_id == ""
        assert msg.content == ""
        assert msg.message_type is AgentMessageType.NOTIFICATION

    def test_from_dict_timestamp_string_parsed(self):
        ts = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)
        d = {"timestamp": ts.isoformat()}
        msg = AgentMessage.from_dict(d)
        assert msg.timestamp == ts

    def test_from_dict_timestamp_datetime_passthrough(self):
        ts = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)
        d: dict[str, object] = {"timestamp": ts}
        msg = AgentMessage.from_dict(d)
        assert msg.timestamp == ts

    def test_from_dict_message_type_from_string(self):
        d = {"message_type": "response"}
        msg = AgentMessage.from_dict(d)
        assert msg.message_type is AgentMessageType.RESPONSE

    def test_all_message_types_round_trip(self):
        for mt in AgentMessageType:
            msg = self._make_message(message_type=mt)
            d = msg.to_dict()
            restored = AgentMessage.from_dict(d)
            assert restored.message_type is mt
