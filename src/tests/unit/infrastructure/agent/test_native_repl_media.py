"""Accepted media must exist before observe and remain scoped on authenticated reads."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.domain.events.agent_events import AgentObserveEvent
from src.domain.model.artifact.artifact import ArtifactStatus
from src.infrastructure.adapters.primary.web.routers.agent import computer_use_media as api
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolAttachment, ToolEvent, ToolResult
from src.tests.unit.infrastructure.agent.test_native_computer_use import Artifacts, image_bytes

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy import Select

    from src.infrastructure.agent.tools.context import ToolContext
    from src.infrastructure.agent.tools.pipeline import ToolInfoProtocol


class Pipeline:
    async def execute(
        self, tool: ToolInfoProtocol, args: dict[str, object], ctx: ToolContext
    ) -> AsyncIterator[ToolEvent]:
        yield ToolEvent.started(tool.name, args)
        yield ToolEvent.completed(tool.name, await tool.execute(**args))


@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize(("declared", "blocked"), [(True, False), (False, False), (True, True)])
@pytest.mark.parametrize("storage_failure", [False, True])
async def test_observe_has_durable_binding_exactly_once_before_publish(
    monkeypatch: pytest.MonkeyPatch,
    pipeline: bool,
    declared: bool,
    blocked: bool,
    storage_failure: bool,
) -> None:
    content = image_bytes()
    service = Artifacts()
    service.create_artifact = AsyncMock(
        wraps=service.create_artifact,
        side_effect=RuntimeError("storage unavailable") if storage_failure else None,
    )
    executions = []

    async def execute(ctx: ToolContext, **args: object) -> ToolResult:
        executions.append(ctx.call_id)
        return ToolResult(
            output=json.dumps(
                {
                    "outputs": [
                        {"type": "text", "text": "before"},
                        {"type": "text", "text": "after"},
                    ],
                    "artifacts": [
                        {
                            "kind": "image",
                            "artifact_id": "native-id",
                            "mime_type": "image/png",
                            "size_bytes": len(content),
                            "url": "cua-artifact:native-id",
                            "store": "device",
                        }
                    ],
                    "output_order": [
                        {"source": "text", "index": 0},
                        {"source": "media", "index": 0},
                        {"source": "text", "index": 1},
                    ],
                }
            ),
            attachments=[ToolAttachment(name="native-id", content=content, mime_type="image/png")],
        )

    async def generate(
        _stream: object, messages: list[dict[str, object]], **kwargs: object
    ) -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(
            type=StreamEventType.TOOL_CALL_START,
            data={"call_id": "repl-call", "name": "unrelated_name"},
        )
        yield SimpleNamespace(
            type=StreamEventType.TOOL_CALL_END,
            data={
                "call_id": "repl-call",
                "name": "unrelated_name",
                "arguments": {
                    "input": {},
                    "display": {
                        "kind": "repl_output",
                        "entries": [{"kind": "text", "text": "forged"}],
                    },
                },
            },
        )
        yield SimpleNamespace(type=StreamEventType.FINISH, data={"reason": "tool_calls"})

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream.generate", generate)
    info = ToolInfo(
        name="unrelated_name",
        description="fixture",
        permission="read",
        execute=execute,
        parameters={
            "type": "object",
            **({"x-agistack-display-kind": "repl_output"} if declared else {}),
        },
    )
    processor = SessionProcessor(
        config=ProcessorConfig(model="test", run_id="run"),
        tools=convert_tools({info.name: info}),
        artifact_service=service,
        tool_pipeline=Pipeline() if pipeline else None,
    )
    processor._langfuse_context = {
        "tenant_id": "tenant",
        "project_id": "project",
        "conversation_id": "conversation",
        "user_id": "user",
    }
    processor._artifact_handler.set_langfuse_context(processor._langfuse_context)
    if blocked:
        processor._apply_tool_result_policy = AsyncMock(return_value=("rejected", {}, True, True))
    observed = []
    async for event in processor._process_step(
        "engine-session", [{"role": "user", "content": "run"}]
    ):
        if isinstance(event, AgentObserveEvent):
            observed.append(event)
            if declared and not blocked and not storage_failure:
                assert service.create_artifact.await_count == 1
                assert [e["kind"] for e in event.display["entries"]] == ["text", "image", "text"]
                assert event.display["entries"][1]["artifactId"] == "artifact-1"
                assert event.display["entries"][1]["store"] == "conversation_tool_media"
            else:
                assert event.display is None
    assert executions == ["repl-call"]
    assert len(observed) == 1
    assert service.create_artifact.await_count == (0 if blocked else 1)


class Database:
    async def scalar(self, statement: Select[tuple[str]]) -> str | None:
        params = set(statement.compile().params.values())
        needed = {"user", "tenant", "project"}
        if "conversations" in str(statement):
            needed.add("conversation")
        return "allowed" if needed <= params else None


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({}, 200),
        ({"user": "other"}, 403),
        ({"tenant": "other"}, 403),
        ({"project": "other"}, 403),
        ({"conversation": "other"}, 404),
        ({"artifact": "native-id"}, 404),
        ({"origin": "ordinary_upload"}, 404),
        ({"artifact_conversation": "other"}, 404),
        ({"mime": "text/html"}, 404),
        ({"size": 99}, 409),
        ({"media_type": "audio/wav"}, 200),
        ({"content_error": "integrity"}, 409),
        ({"content_error": "size"}, 413),
        ({"content_error": "missing"}, 404),
    ],
)
async def test_authenticated_owned_media_bytes(change: dict[str, str | int], status: int) -> None:
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/agent")
    artifact = SimpleNamespace(
        tenant_id="tenant",
        project_id="project",
        conversation_id=change.get("artifact_conversation", "conversation"),
        status=ArtifactStatus.READY,
        metadata={"upload_source": change.get("origin", "native_computer_use")},
        mime_type=change.get("mime", change.get("media_type", "image/png")),
        size_bytes=change.get("size", 3),
    )
    content = SimpleNamespace(mime_type=change.get("media_type", "image/png"), content=b"png")
    errors = {
        "integrity": api.ArtifactContentIntegrityError("fixture"),
        "size": api.ArtifactContentTooLargeError(
            actual_bytes=65 * 1024 * 1024, max_bytes=64 * 1024 * 1024
        ),
        "missing": api.ArtifactContentNotReadyError("fixture"),
    }

    async def get_artifact(identifier: str) -> SimpleNamespace | None:
        return artifact if identifier == "cloud-id" else None

    services = SimpleNamespace(
        artifacts=SimpleNamespace(get_artifact=get_artifact),
        content=SimpleNamespace(
            get_bytes=AsyncMock(
                return_value=content, side_effect=errors.get(change.get("content_error"))
            )
        ),
        commit=AsyncMock(),
    )
    app.dependency_overrides[api.get_current_user] = lambda: SimpleNamespace(
        id=change.get("user", "user")
    )
    app.dependency_overrides[api.get_db] = lambda: Database()
    app.dependency_overrides[api.artifact_http_application_authority_dependency_v2] = (
        lambda: SimpleNamespace(services=services)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/agent/conversations/"
            + change.get("conversation", "conversation")
            + "/tool-media/"
            + change.get("artifact", "cloud-id"),
            params={
                "tenant_id": change.get("tenant", "tenant"),
                "project_id": change.get("project", "project"),
            },
        )
    assert response.status_code == status, response.text
    if status == 200:
        assert response.content == b"png"
        assert response.headers["content-type"] == change.get("media_type", "image/png")
        assert response.headers["content-length"] == "3"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        services.commit.assert_awaited_once()
    elif status in {403, 404} and not change.get("content_error"):
        services.content.get_bytes.assert_not_awaited()
