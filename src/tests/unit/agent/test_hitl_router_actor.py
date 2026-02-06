"""Unit tests for HITLStreamRouterActor."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.agent.actor import hitl_router_actor


class _FakeContinue:
    def __init__(self):
        self.called_with = None

    def remote(self, request_id, response_data):
        self.called_with = (request_id, response_data)
        return "ref"


class _FakeActor:
    def __init__(self):
        self.continue_chat = _FakeContinue()


@pytest.mark.unit
class TestHITLStreamRouterActor:
    """Tests for HITLStreamRouterActor."""

    async def test_handle_message_routes_to_actor_and_acks(self, monkeypatch):
        # Get the underlying class from the Ray ActorClass wrapper
        ActorClass = hitl_router_actor.HITLStreamRouterActor
        inner_cls = ActorClass.__ray_metadata__.modified_class
        actor = inner_cls.__new__(inner_cls)
        actor._redis = AsyncMock()

        fake_actor = _FakeActor()
        get_actor_mock = AsyncMock(return_value=fake_actor)
        monkeypatch.setattr(actor, "_get_or_create_actor", get_actor_mock)

        await_ray_mock = AsyncMock()
        monkeypatch.setattr(hitl_router_actor, "await_ray", await_ray_mock)

        payload = {
            "request_id": "req-1",
            "response_data": {"answer": "ok"},
            "agent_mode": "default",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        }

        await actor._handle_message(
            stream_key="hitl:response:tenant-1:project-1",
            msg_id="1-0",
            fields={"data": json.dumps(payload)},
        )

        assert fake_actor.continue_chat.called_with == ("req-1", {"answer": "ok"})
        await_ray_mock.assert_awaited_once()
        get_actor_mock.assert_awaited_once_with("tenant-1", "project-1", "default")
        actor._redis.xack.assert_awaited_once_with(
            "hitl:response:tenant-1:project-1",
            actor.CONSUMER_GROUP,
            "1-0",
        )
