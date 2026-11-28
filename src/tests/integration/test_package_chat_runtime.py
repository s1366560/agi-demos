"""Exercise package chat through full HTTP/WS admission, SQL WAL, and model-stream fixture."""

import asyncio
import json
import os
from importlib import import_module
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_from_header_or_query,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    initialize_scoped_profile_runtime_v2,
)
from src.infrastructure.adapters.primary.web.websocket.handlers import chat_handler
from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent
from src.tests.integration.governance.conftest import _workspace_core_runtime_factory
from src.tests.unit.infrastructure.adapters.primary.web.test_agent_message_history_http_application_authority_v2 import (
    _RedisClient,
)
from src.tests.unit.routers.test_optional_business_http_v2 import (  # noqa: F401
    create_api_key,
    publisher,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


def _redis():
    redis_url = os.environ.get("PACKAGE_CHAT_TEST_REDIS_URL")
    if redis_url:
        return Redis.from_url(redis_url)
    redis = _RedisClient()
    redis.set = AsyncMock(return_value=True)
    redis.smembers = AsyncMock(return_value=set())
    return redis


async def test_cloud_turn_and_p5_replay(
    test_app,
    publisher,  # noqa: F811
    test_project_db,
    db_session,
    test_user,
    test_engine,
    monkeypatch,
):
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    test_app.state.plugin_marketplace_trusted_public_keys_v2 = (publisher[0],)
    test_app.state.plugin_marketplace_allowed_registries_v2 = frozenset()
    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides.pop(get_current_user_from_header_or_query, None)
    redis = _redis()
    test_app.state.container._redis_client = redis
    await initialize_plugin_runtime_v2(
        test_app,
        session_factory=sessions,
        sandbox_redis_client=redis,
        workspace_core_runtime_factory=_workspace_core_runtime_factory,
    )
    scoped = initialize_scoped_profile_runtime_v2(
        test_app, session_factory=sessions, redis_client=redis
    )
    key, _ = await create_api_key(db_session, test_user.id, "qa", [])
    await db_session.commit()
    scope = {"tenant_id": test_project_db.tenant_id, "project_id": test_project_db.id}
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://localhost",
        headers={"authorization": "Bearer " + key},
    )
    path = "/api/v1/platform-plugins/v2/optional-business"
    base = path + "/memstack-agent"
    body, digest = publisher[1](
        plugin_id="memstack-agent",
        application_command={k: "app.agent." + k for k in ("create", "history", "turn", "cancel")}
    )

    async def command(name, payload, stream=False):
        response = await client.post(
            base + "/commands",
            params={"stream": str(stream).lower()},
            json={**scope, "expected_digest": digest, "command_id": name, "payload": payload},
        )
        assert response.is_success, response.text
        return (
            [json.loads(line) for line in response.text.splitlines()] if stream else response.json()
        )

    monkeypatch.setattr(
        import_module("src.infrastructure.adapters.primary.web.websocket.router"),
        "async_session_factory",
        sessions,
    )

    async def model_stream(
        *, context, conversation_id, user_message, execution_message_id, **kwargs
    ):
        # Substitute the model/actor only, after canonical turn admission has committed.
        text = "Replay " + user_message
        async with sessions.begin() as writer:
            for i, (kind, content) in enumerate(
                [("user_message", user_message), ("assistant_message", text)]
            ):
                writer.add(
                    AgentExecutionEvent(
                        id=str(uuid4()),
                        conversation_id=conversation_id,
                        message_id=execution_message_id,
                        event_type=kind,
                        event_time_us=10000 + i,
                        event_counter=0,
                        event_data={"content": content},
                    )
                )
        for kind, body in [("text_delta", {"delta": text}), ("complete", {})]:
            await context.connection_manager.broadcast_agent_stream_event(
                conversation_id,
                {
                    "type": kind,
                    "conversation_id": conversation_id,
                    "run_id": execution_message_id,
                    "data": body,
                },
                message_id=execution_message_id,
            )

    monkeypatch.setattr(chat_handler, "stream_agent_to_websocket_with_fresh_session", model_stream)
    try:
        installed = await client.post(path + "/install", json={**body, **scope})
        assert installed.is_success, installed.text
        enabled = await client.post(base + "/enable", json=scope)
        assert enabled.is_success, enabled.text
        conv = await command("create", {"title": "QA signed chat"})
        async with asyncio.timeout(30):
            events = await command(
                "turn",
                {
                    "conversation_id": conv["id"],
                    "message": "integration",
                    "message_id": str(uuid4()),
                },
                stream=True,
            )
        frames = [e["data"] for e in events if e["type"] == "progress"]
        assert events[-1]["type"] == "result", events
        assert frames[0]["type"] == "accepted"
        assert frames[1] == {"type": "text_delta", "text": "Replay integration"}
        cancel = await command(
            "cancel",
            {
                "conversation_id": conv["id"],
                "expected_revision": frames[0]["revision"],
                "run_id": frames[0]["run_id"],
            },
        )
        assert cancel == {"status": "cancel_requested"}
        result = await command("history", {"conversation_id": conv["id"]})
        assert [m["content"] for m in result["messages"]] == ["integration", "Replay integration"]
    finally:
        await client.aclose()
        await scoped.close()
        await shutdown_plugin_runtime_v2(test_app)
        await redis.aclose()
