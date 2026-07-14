"""Verify a real local Agent turn against the deterministic LLM fixture."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlencode

import httpx
import websockets

from scripts.fake_openai_server import E2E_AGENT_RESPONSE


@dataclass(frozen=True)
class _AgentFixture:
    token: str
    project_id: str
    conversation_id: str


class _WebSocket(Protocol):
    async def recv(self) -> str | bytes: ...


def _require_mapping(payload: object, description: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"Agent E2E fixture did not return {description}")
    return cast("Mapping[str, object]", payload)


def _require_string(payload: Mapping[str, object], key: str, description: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Agent E2E fixture did not return {description}")
    return value


def _bootstrap_agent_fixture(api_base: str, client: httpx.Client) -> _AgentFixture:
    base = api_base.rstrip("/")
    auth_response = client.post(
        f"{base}/api/v1/auth/token",
        data={"username": "admin@memstack.ai", "password": "adminpassword"},
    )
    _ = auth_response.raise_for_status()
    auth_payload = _require_mapping(
        cast("object", auth_response.json()), "an authentication object"
    )
    token = _require_string(auth_payload, "access_token", "an access token")
    headers = {"Authorization": f"Bearer {token}"}

    tenant_response = client.get(f"{base}/api/v1/tenants/", headers=headers)
    _ = tenant_response.raise_for_status()
    tenant_payload = cast("object", tenant_response.json())
    if isinstance(tenant_payload, Mapping):
        tenant_payload = cast("Mapping[str, object]", tenant_payload).get("tenants")
    if not isinstance(tenant_payload, list) or not tenant_payload:
        raise RuntimeError("Agent E2E fixture did not return a tenant")
    first_tenant = _require_mapping(cast("object", tenant_payload[0]), "a tenant object")
    tenant_id = _require_string(first_tenant, "id", "a tenant id")

    project_response = client.post(
        f"{base}/api/v1/projects/",
        headers=headers,
        json={
            "name": f"Agent E2E {uuid.uuid4().hex[:8]}",
            "description": "Deterministic local Agent and LLM E2E fixture",
            "tenant_id": tenant_id,
        },
    )
    _ = project_response.raise_for_status()
    project_payload = _require_mapping(cast("object", project_response.json()), "a project object")
    project_id = _require_string(project_payload, "id", "a project id")

    conversation_response = client.post(
        f"{base}/api/v1/agent/conversations",
        headers=headers,
        json={"project_id": project_id, "title": "Deterministic Agent E2E"},
    )
    _ = conversation_response.raise_for_status()
    conversation_payload = _require_mapping(
        cast("object", conversation_response.json()), "a conversation object"
    )
    conversation_id = _require_string(conversation_payload, "id", "a conversation id")
    return _AgentFixture(
        token=token,
        project_id=project_id,
        conversation_id=conversation_id,
    )


def verify_agent_events(events: Sequence[Mapping[str, object]]) -> None:
    """Fail unless a stream contains the deterministic answer and clean completion."""
    text_parts: list[str] = []
    completed = False
    for event in events:
        event_type = event.get("type")
        data = event.get("data")
        event_data: Mapping[str, object] = (
            cast("Mapping[str, object]", data) if isinstance(data, Mapping) else {}
        )
        if event_type == "error":
            message = event_data.get("message")
            raise RuntimeError(str(message or "Agent E2E stream returned an error"))
        if event_type == "text_delta":
            delta = event_data.get("delta")
            if isinstance(delta, str):
                text_parts.append(delta)
        if event_type == "complete":
            completed = True

    if E2E_AGENT_RESPONSE not in "".join(text_parts):
        raise RuntimeError("Agent E2E stream did not contain deterministic assistant text")
    if not completed:
        raise RuntimeError("Agent E2E stream did not contain a terminal complete event")


def verify_agent_history(payload: object) -> None:
    """Fail unless the REST timeline persisted the deterministic assistant answer."""
    history = _require_mapping(payload, "a conversation history object")
    timeline = history.get("timeline")
    if not isinstance(timeline, list):
        raise RuntimeError("Agent E2E history did not contain a timeline")

    for raw_item in cast("list[object]", timeline):
        if not isinstance(raw_item, Mapping):
            continue
        item = cast("Mapping[str, object]", raw_item)
        if item.get("role") == "assistant" and item.get("content") == E2E_AGENT_RESPONSE:
            return
    raise RuntimeError("Agent E2E history did not contain persisted assistant text")


def _wait_for_agent_history(
    client: httpx.Client,
    api_base: str,
    fixture: _AgentFixture,
    *,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: RuntimeError | None = None
    while time.monotonic() < deadline:
        history_response = client.get(
            f"{api_base.rstrip('/')}/api/v1/agent/conversations/{fixture.conversation_id}/messages",
            headers={"Authorization": f"Bearer {fixture.token}"},
            params={"project_id": fixture.project_id},
        )
        _ = history_response.raise_for_status()
        try:
            verify_agent_history(cast("object", history_response.json()))
            return
        except RuntimeError as exc:
            last_error = exc
            time.sleep(0.25)
    raise last_error or RuntimeError("Agent E2E history did not become available")


async def _receive_json(websocket: _WebSocket) -> Mapping[str, object]:
    raw_message = await websocket.recv()
    if not isinstance(raw_message, str):
        raise RuntimeError("Agent E2E WebSocket returned a non-text frame")
    raw_payload = cast("object", json.loads(raw_message))
    if not isinstance(raw_payload, Mapping):
        raise RuntimeError("Agent E2E WebSocket returned a non-object payload")
    return cast("Mapping[str, object]", raw_payload)


async def _verify_agent_websocket(
    websocket_base: str,
    fixture: _AgentFixture,
    *,
    timeout_seconds: float,
) -> None:
    query = urlencode({"token": fixture.token, "session_id": f"e2e-{uuid.uuid4().hex}"})
    uri = f"{websocket_base.rstrip('/')}/api/v1/agent/ws?{query}"
    events: list[Mapping[str, object]] = []

    async with asyncio.timeout(timeout_seconds):
        async with websockets.connect(uri) as websocket:
            connected = await _receive_json(websocket)
            if connected.get("type") != "connected":
                raise RuntimeError("Agent E2E WebSocket did not confirm the connection")

            await websocket.send(
                json.dumps({"type": "subscribe", "conversation_id": fixture.conversation_id})
            )
            while True:
                message = await _receive_json(websocket)
                if message.get("type") == "error":
                    verify_agent_events([message])
                if message.get("type") == "ack" and message.get("action") == "subscribe":
                    break

            await websocket.send(
                json.dumps(
                    {
                        "type": "send_message",
                        "conversation_id": fixture.conversation_id,
                        "project_id": fixture.project_id,
                        "message": "Reply exactly E2E_AGENT_OK and do not call tools.",
                    }
                )
            )
            while True:
                message = await _receive_json(websocket)
                events.append(message)
                if message.get("type") in {"complete", "error"}:
                    break

    verify_agent_events(events)


def verify_agent(
    api_base: str,
    websocket_base: str,
    *,
    timeout_seconds: float = 60.0,
) -> None:
    """Create an isolated project/conversation and complete one real Agent turn."""
    with httpx.Client(timeout=15.0) as client:
        fixture = _bootstrap_agent_fixture(api_base, client)
        asyncio.run(
            _verify_agent_websocket(
                websocket_base,
                fixture,
                timeout_seconds=timeout_seconds,
            )
        )
        _wait_for_agent_history(client, api_base, fixture)


if __name__ == "__main__":
    verify_agent(
        os.getenv("API_BASE", "http://localhost:8000"),
        os.getenv("WEBSOCKET_BASE", "ws://localhost:8000"),
    )
    print("Deterministic Agent/LLM E2E verified")
