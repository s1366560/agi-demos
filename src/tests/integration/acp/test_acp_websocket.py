from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.routers import acp


class DummySessionFactory:
    def __init__(self) -> None:
        self.commits = 0

    def __call__(self) -> DummySessionFactory:
        return self

    async def __aenter__(self) -> DummySessionFactory:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeAgentService:
    async def create_conversation(self, **kwargs: Any) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(id="conversation-1")

    async def stream_chat_v2(self, **kwargs: Any) -> Any:
        yield {"type": "text_delta", "data": {"delta": kwargs["user_message"]}}


def test_acp_websocket_initialize_new_session_and_prompt(monkeypatch) -> None:
    app = FastAPI()
    app.state.container = SimpleNamespace(with_db=lambda db: SimpleNamespace())
    app.include_router(acp.router)

    async def authenticate(token: str, db: object) -> tuple[str, str] | None:
        assert token == "ms_sk_test"
        return ("user-1", "tenant-1")

    async def agent_service(self: object, db: object) -> FakeAgentService:
        del self, db
        return FakeAgentService()

    monkeypatch.setattr(acp, "authenticate_websocket", authenticate)
    monkeypatch.setattr(acp, "async_session_factory", DummySessionFactory())
    monkeypatch.setattr(acp.MemStackACPAgent, "_agent_service", agent_service)

    with TestClient(app).websocket_connect(
        "/api/v1/acp/ws",
        headers={"Authorization": "Bearer ms_sk_test"},
    ) as websocket:
        websocket.send_text(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": 1},
                }
            )
        )
        initialize_response = json.loads(websocket.receive_text())
        assert initialize_response["result"]["protocolVersion"] == 1
        assert initialize_response["result"]["agentInfo"]["name"] == "memstack"

        websocket.send_text(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/new",
                    "params": {
                        "cwd": "/tmp/project",
                        "mcpServers": [],
                        "_meta": {"memstack": {"projectId": "project-1"}},
                    },
                }
            )
        )
        session_response = json.loads(websocket.receive_text())
        assert session_response["result"]["sessionId"] == "conversation-1"

        websocket.send_text(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "session/prompt",
                    "params": {
                        "sessionId": "conversation-1",
                        "prompt": [{"type": "text", "text": "hello"}],
                    },
                }
            )
        )
        update = json.loads(websocket.receive_text())
        prompt_response = json.loads(websocket.receive_text())

        assert update["method"] == "session/update"
        assert update["params"]["update"]["content"] == {"text": "hello", "type": "text"}
        assert prompt_response["result"]["stopReason"] == "end_turn"
