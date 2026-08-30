from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.infrastructure.acp.server as acp_server_module
from src.infrastructure.adapters.primary.web.routers import acp
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[4]


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

    async def after_create_committed(self, conversation: object) -> None:
        del conversation


def test_acp_websocket_initialize_new_session_and_prompt(monkeypatch) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await host.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=1,
            version=1,
            nonce="acp-websocket-integration",
        )
        install_process_generation_host_v2(host)
        try:
            yield None
        finally:
            clear_process_generation_host_v2(host)
            await host.close()

    app = FastAPI(lifespan=lifespan)
    app.state.container = SimpleNamespace(with_db=lambda db: SimpleNamespace())
    app.include_router(acp.router)

    async def authenticate(token: str, db: object) -> tuple[str, str] | None:
        assert token == "ms_sk_test"
        return ("user-1", "tenant-1")

    service = FakeAgentService()

    @asynccontextmanager
    async def conversation_collection_authority(
        **_kwargs: object,
    ) -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(operation=object(), service=service)

    async def current_agent_turn_service() -> FakeAgentService:
        return service

    monkeypatch.setattr(acp, "authenticate_websocket", authenticate)
    monkeypatch.setattr(acp, "async_session_factory", DummySessionFactory())
    monkeypatch.setattr(
        acp_server_module,
        "acp_conversation_collection_authority_v2",
        conversation_collection_authority,
    )
    monkeypatch.setattr(
        acp_server_module,
        "current_agent_turn_service_v2",
        current_agent_turn_service,
    )

    with (
        TestClient(app) as client,
        client.websocket_connect(
            "/api/v1/acp/ws",
            headers={"Authorization": "Bearer ms_sk_test"},
        ) as websocket,
    ):
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
