"""Tests for Phase 2 Wave 3: ControlChannel port + RedisControlChannel infrastructure."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlChannelPort, ControlMessage
from src.infrastructure.agent.subagent.control_channel import (
    RedisControlChannel,
    _deserialize_message,  # pyright: ignore[reportPrivateUsage]
    _kill_key,  # pyright: ignore[reportPrivateUsage]
    _serialize_message,  # pyright: ignore[reportPrivateUsage]
    _stream_key,  # pyright: ignore[reportPrivateUsage]
)


@pytest.mark.unit
class TestControlMessage:
    def test_create_kill_message(self) -> None:
        msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.KILL,
            payload="timeout",
            sender_id="parent-1",
            cascade=True,
        )
        assert msg.run_id == "run-1"
        assert msg.message_type == ControlMessageType.KILL
        assert msg.payload == "timeout"
        assert msg.sender_id == "parent-1"
        assert msg.cascade is True
        assert isinstance(msg.timestamp, datetime)

    def test_create_steer_message_defaults(self) -> None:
        msg = ControlMessage(
            run_id="run-2",
            message_type=ControlMessageType.STEER,
        )
        assert msg.payload == ""
        assert msg.sender_id == ""
        assert msg.cascade is False

    def test_frozen(self) -> None:
        msg = ControlMessage(run_id="r", message_type=ControlMessageType.PAUSE)
        with pytest.raises(AttributeError):
            msg.run_id = "changed"  # type: ignore[misc]

    def test_all_message_types(self) -> None:
        for mtype in ControlMessageType:
            msg = ControlMessage(run_id="r", message_type=mtype)
            assert msg.message_type == mtype

    def test_timestamp_auto_set(self) -> None:
        before = datetime.now(UTC)
        msg = ControlMessage(run_id="r", message_type=ControlMessageType.RESUME)
        after = datetime.now(UTC)
        assert before <= msg.timestamp <= after


@pytest.mark.unit
class TestControlChannelProtocol:
    def test_redis_channel_is_protocol_instance(self) -> None:
        mock_redis = AsyncMock()
        channel = RedisControlChannel(mock_redis)
        assert isinstance(channel, ControlChannelPort)


@pytest.mark.unit
class TestHelperFunctions:
    def test_kill_key_format(self) -> None:
        assert _kill_key("run-abc") == "agent:control:kill:run-abc"

    def test_stream_key_format(self) -> None:
        assert _stream_key("run-abc") == "agent:control:stream:run-abc"

    def test_serialize_message_fields(self) -> None:
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        msg = ControlMessage(
            run_id="r1",
            message_type=ControlMessageType.STEER,
            payload="focus on tests",
            sender_id="parent",
            timestamp=ts,
            cascade=False,
        )
        data = _serialize_message(msg)
        assert data["run_id"] == "r1"
        assert data["message_type"] == "steer"
        assert data["payload"] == "focus on tests"
        assert data["sender_id"] == "parent"
        assert data["timestamp"] == "2026-01-01T12:00:00+00:00"
        assert data["cascade"] == "False"

    def test_deserialize_message_from_str_dict(self) -> None:
        data = {
            "run_id": "r1",
            "message_type": "kill",
            "payload": "reason",
            "sender_id": "s1",
            "timestamp": "2026-01-01T12:00:00+00:00",
            "cascade": "True",
        }
        msg = _deserialize_message(data)
        assert msg.run_id == "r1"
        assert msg.message_type == ControlMessageType.KILL
        assert msg.payload == "reason"
        assert msg.sender_id == "s1"
        assert msg.cascade is True

    def test_deserialize_message_from_bytes_dict(self) -> None:
        data: dict[str | bytes, str | bytes] = {
            b"run_id": b"r2",
            b"message_type": b"pause",
            b"payload": b"",
            b"sender_id": b"",
            b"timestamp": b"2026-06-15T00:00:00+00:00",
            b"cascade": b"False",
        }
        msg = _deserialize_message(data)
        assert msg.run_id == "r2"
        assert msg.message_type == ControlMessageType.PAUSE
        assert msg.cascade is False

    def test_serialize_deserialize_round_trip(self) -> None:
        original = ControlMessage(
            run_id="r3",
            message_type=ControlMessageType.RESUME,
            payload="go",
            sender_id="orchestrator",
            cascade=True,
        )
        data = _serialize_message(original)
        restored = _deserialize_message(data)
        assert restored.run_id == original.run_id
        assert restored.message_type == original.message_type
        assert restored.payload == original.payload
        assert restored.sender_id == original.sender_id
        assert restored.cascade == original.cascade

    def test_canonical_run_input_metadata_round_trip(self) -> None:
        original = ControlMessage(
            run_id="run-4",
            message_type=ControlMessageType.STEER,
            payload="Use the focused regression suite.",
            sender_id="user-1",
            run_input_id="input-1",
            delivery_mode="steer_now",
            run_revision=7,
            message_id="message-1",
            idempotency_key="input-key-1",
            target_agent_id="agent-1",
            target_agent_name="Researcher",
        )

        restored = _deserialize_message(_serialize_message(original))

        assert restored.run_input_id == "input-1"
        assert restored.delivery_mode == "steer_now"
        assert restored.run_revision == 7
        assert restored.message_id == "message-1"
        assert restored.idempotency_key == "input-key-1"
        assert restored.target_agent_id == "agent-1"
        assert restored.target_agent_name == "Researcher"


def _make_channel() -> tuple[RedisControlChannel, AsyncMock]:
    mock_redis = AsyncMock()
    channel = RedisControlChannel(mock_redis)
    return channel, mock_redis


@pytest.mark.unit
class TestSendControl:
    async def test_send_kill_sets_key_with_ttl(self) -> None:
        channel, redis = _make_channel()
        msg = ControlMessage(
            run_id="r1",
            message_type=ControlMessageType.KILL,
            payload="timeout",
            sender_id="parent",
            cascade=True,
            run_revision=7,
            idempotency_key="kill-key-1",
            target_agent_id="agent-1",
            target_agent_name="Researcher",
        )
        result = await channel.send_control(msg)
        assert result is True
        redis.set.assert_awaited_once()
        call_args = redis.set.call_args
        assert call_args[0][0] == "agent:control:kill:r1"
        stored = json.loads(call_args[0][1])
        assert stored["reason"] == "timeout"
        assert stored["sender_id"] == "parent"
        assert stored["cascade"] is True
        assert stored["run_revision"] == 7
        assert stored["idempotency_key"] == "kill-key-1"
        assert stored["target_agent_id"] == "agent-1"
        assert call_args[1]["ex"] == 600

    async def test_send_steer_appends_to_stream(self) -> None:
        channel, redis = _make_channel()
        msg = ControlMessage(
            run_id="r1",
            message_type=ControlMessageType.STEER,
            payload="focus on auth",
            sender_id="parent",
        )
        result = await channel.send_control(msg)
        assert result is True
        redis.xadd.assert_awaited_once()
        call_args = redis.xadd.call_args
        assert call_args[0][0] == "agent:control:stream:r1"
        fields = call_args[0][1]
        assert fields["message_type"] == "steer"
        assert fields["payload"] == "focus on auth"
        assert call_args[1]["maxlen"] == 100

    async def test_send_pause_uses_stream(self) -> None:
        channel, redis = _make_channel()
        msg = ControlMessage(run_id="r1", message_type=ControlMessageType.PAUSE)
        result = await channel.send_control(msg)
        assert result is True
        redis.xadd.assert_awaited_once()

    async def test_send_resume_uses_stream(self) -> None:
        channel, redis = _make_channel()
        msg = ControlMessage(run_id="r1", message_type=ControlMessageType.RESUME)
        result = await channel.send_control(msg)
        assert result is True
        redis.xadd.assert_awaited_once()

    async def test_send_returns_false_on_exception(self) -> None:
        channel, redis = _make_channel()
        redis.set.side_effect = ConnectionError("connection lost")
        msg = ControlMessage(run_id="r1", message_type=ControlMessageType.KILL)
        result = await channel.send_control(msg)
        assert result is False

    async def test_send_stream_returns_false_on_exception(self) -> None:
        channel, redis = _make_channel()
        redis.xadd.side_effect = ConnectionError("connection lost")
        msg = ControlMessage(run_id="r1", message_type=ControlMessageType.STEER)
        result = await channel.send_control(msg)
        assert result is False


@pytest.mark.unit
class TestCheckControl:
    async def test_returns_kill_message_when_key_exists(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = json.dumps(
            {"reason": "cancelled", "sender_id": "user", "cascade": False}
        ).encode()
        msg = await channel.check_control("r1")
        assert msg is not None
        assert msg.message_type == ControlMessageType.KILL
        assert msg.payload == "cancelled"
        assert msg.sender_id == "user"
        assert msg.cascade is False
        redis.get.assert_awaited_once_with("agent:control:kill:r1")

    async def test_returns_stream_message_when_no_kill(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = None
        redis.xrange.return_value = [
            (
                b"1234-0",
                {
                    b"run_id": b"r1",
                    b"message_type": b"steer",
                    b"payload": b"hint",
                    b"sender_id": b"p1",
                    b"timestamp": b"2026-01-01T00:00:00+00:00",
                    b"cascade": b"False",
                },
            )
        ]
        msg = await channel.check_control("r1")
        assert msg is not None
        assert msg.message_type == ControlMessageType.STEER
        assert msg.payload == "hint"
        redis.xrange.assert_awaited_once_with("agent:control:stream:r1", count=1)

    async def test_returns_none_when_nothing_pending(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = None
        redis.xrange.return_value = []
        msg = await channel.check_control("r1")
        assert msg is None

    async def test_kill_takes_priority_over_stream(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = json.dumps(
            {"reason": "killed", "sender_id": "admin", "cascade": True}
        ).encode()
        msg = await channel.check_control("r1")
        assert msg is not None
        assert msg.message_type == ControlMessageType.KILL
        redis.xrange.assert_not_awaited()

    async def test_returns_none_on_exception(self) -> None:
        channel, redis = _make_channel()
        redis.get.side_effect = ConnectionError("down")
        msg = await channel.check_control("r1")
        assert msg is None


@pytest.mark.unit
class TestConsumeControl:
    async def test_consumes_kill_and_stream_messages(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = json.dumps(
            {
                "reason": "stop",
                "sender_id": "p1",
                "cascade": False,
                "run_revision": 7,
                "idempotency_key": "kill-key-1",
                "target_agent_id": "agent-1",
                "target_agent_name": "Researcher",
            }
        ).encode()
        redis.xrange.return_value = [
            (
                b"100-0",
                {
                    b"run_id": b"r1",
                    b"message_type": b"steer",
                    b"payload": b"do X",
                    b"sender_id": b"p1",
                    b"timestamp": b"2026-01-01T00:00:00+00:00",
                    b"cascade": b"False",
                },
            ),
        ]
        messages = await channel.consume_control("r1")
        assert len(messages) == 2
        types = {m.message_type for m in messages}
        assert ControlMessageType.KILL in types
        assert ControlMessageType.STEER in types
        kill = next(m for m in messages if m.message_type == ControlMessageType.KILL)
        assert kill.run_revision == 7
        assert kill.target_agent_id == "agent-1"
        redis.delete.assert_awaited_once_with("agent:control:kill:r1")
        redis.xdel.assert_awaited_once()

    async def test_consumes_only_kill_when_no_stream(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = json.dumps(
            {"reason": "bye", "sender_id": "s", "cascade": False}
        ).encode()
        redis.xrange.return_value = []
        messages = await channel.consume_control("r1")
        assert len(messages) == 1
        assert messages[0].message_type == ControlMessageType.KILL
        redis.delete.assert_awaited_once_with("agent:control:kill:r1")

    async def test_consumes_only_stream_when_no_kill(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = None
        redis.xrange.return_value = [
            (
                b"200-0",
                {
                    b"run_id": b"r1",
                    b"message_type": b"pause",
                    b"payload": b"",
                    b"sender_id": b"",
                    b"timestamp": b"2026-06-01T00:00:00+00:00",
                    b"cascade": b"False",
                },
            ),
        ]
        messages = await channel.consume_control("r1")
        assert len(messages) == 1
        assert messages[0].message_type == ControlMessageType.PAUSE

    async def test_returns_empty_when_nothing(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = None
        redis.xrange.return_value = []
        messages = await channel.consume_control("r1")
        assert messages == []

    async def test_messages_sorted_by_timestamp(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = json.dumps(
            {
                "reason": "kill",
                "sender_id": "s",
                "cascade": False,
                "timestamp": "2026-01-01T12:00:00+00:00",
            }
        ).encode()
        redis.xrange.return_value = [
            (
                b"50-0",
                {
                    b"run_id": b"r1",
                    b"message_type": b"steer",
                    b"payload": b"earlier",
                    b"sender_id": b"s",
                    b"timestamp": b"2026-01-01T10:00:00+00:00",
                    b"cascade": b"False",
                },
            ),
        ]
        messages = await channel.consume_control("r1")
        assert len(messages) == 2
        assert messages[0].message_type == ControlMessageType.STEER
        assert messages[1].message_type == ControlMessageType.KILL

    async def test_resilient_to_kill_read_error(self) -> None:
        channel, redis = _make_channel()
        redis.get.side_effect = ConnectionError("fail")
        redis.xrange.return_value = [
            (
                b"300-0",
                {
                    b"run_id": b"r1",
                    b"message_type": b"resume",
                    b"payload": b"",
                    b"sender_id": b"",
                    b"timestamp": b"2026-01-01T00:00:00+00:00",
                    b"cascade": b"False",
                },
            ),
        ]
        messages = await channel.consume_control("r1")
        assert len(messages) == 1
        assert messages[0].message_type == ControlMessageType.RESUME

    async def test_resilient_to_stream_read_error(self) -> None:
        channel, redis = _make_channel()
        redis.get.return_value = json.dumps(
            {"reason": "err", "sender_id": "", "cascade": False}
        ).encode()
        redis.xrange.side_effect = ConnectionError("stream fail")
        messages = await channel.consume_control("r1")
        assert len(messages) == 1
        assert messages[0].message_type == ControlMessageType.KILL


@pytest.mark.unit
class TestCleanup:
    async def test_cleanup_deletes_both_keys(self) -> None:
        channel, redis = _make_channel()
        mock_pipeline = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[1, 1])
        redis.pipeline = MagicMock(return_value=mock_pipeline)

        await channel.cleanup("r1")
        mock_pipeline.delete.assert_any_call("agent:control:kill:r1")
        mock_pipeline.delete.assert_any_call("agent:control:stream:r1")
        mock_pipeline.execute.assert_awaited_once()

    async def test_cleanup_resilient_to_error(self) -> None:
        channel, redis = _make_channel()
        redis.pipeline = MagicMock(side_effect=ConnectionError("gone"))
        await channel.cleanup("r1")
