"""Production tool schemas retain explicit literal types through real HTTP transport."""

from __future__ import annotations

import asyncio
import json
from contextlib import aclosing
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from src.domain.llm_providers.llm_types import LLMConfig
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.native_computer_use.permission import native_permission_tool
from src.infrastructure.agent.state import agent_worker_state as worker
from src.infrastructure.agent.tools.skill_loader import make_skill_loader_tool
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient

pytestmark = pytest.mark.unit


def literal_type_errors(value, path="parameters"):
    """Check declared JSON Schema literals, including conditional subschemas."""
    errors = []
    if isinstance(value, dict):
        literals = value.get("enum", [value["const"]] if "const" in value else [])
        if literals and all(isinstance(item, str) for item in literals):
            if value.get("type") != "string":
                errors.append(path)
        for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
            for name, child in value.get(key, {}).items():
                errors.extend(literal_type_errors(child, f"{path}.{key}.{name}"))
        for key in (
            "items",
            "contains",
            "additionalProperties",
            "unevaluatedProperties",
            "unevaluatedItems",
            "propertyNames",
            "not",
            "if",
            "then",
            "else",
            "prefixItems",
            "allOf",
            "anyOf",
            "oneOf",
        ):
            if key in value:
                errors.extend(literal_type_errors(value[key], f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(literal_type_errors(child, f"{path}.{index}"))
    return errors


def test_literal_schema_check_ignores_instance_defaults_but_checks_conditional_schemas():
    schema = {
        "type": "object",
        "default": {"enum": ["instance data"]},
        "properties": {"choice": {"type": "string", "enum": ["allowed"]}},
        "allOf": [{"if": {"properties": {"choice": {"const": "allowed"}}}}],
    }
    assert literal_type_errors(schema) == ["parameters.allOf.0.if.properties.choice"]


@pytest.fixture
async def serialized_tools(monkeypatch, tmp_path):
    """Build real worker tools with inert external dependencies; never invoke tools."""
    from src.infrastructure.adapters.secondary.persistence import database
    from src.infrastructure.plugins.v2 import agent_worker_runtime

    sessions = MagicMock(side_effect=AssertionError("schema construction must not open a database"))
    monkeypatch.setattr(database, "async_session_factory", sessions)
    monkeypatch.setattr(worker, "_tools_cache", {})
    monkeypatch.setattr(worker, "resolve_project_base_path", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(worker, "current_mcp_sandbox_adapter_v2", lambda: None)
    monkeypatch.setattr(
        agent_worker_runtime, "current_agent_canvas_manager_v2", lambda: SimpleNamespace()
    )
    monkeypatch.setattr(
        "src.infrastructure.security.encryption_service.get_encryption_service",
        lambda: SimpleNamespace(),
    )
    skill = make_skill_loader_tool(
        skill_service=None, tenant_id="fixture-tenant", project_id="fixture-project"
    )
    monkeypatch.setattr(worker, "get_or_create_skill_loader_tool", AsyncMock(return_value=skill))
    tools = await worker.get_or_create_tools(
        project_id="fixture-project",
        tenant_id="fixture-tenant",
        graph_service=SimpleNamespace(embedder=None),
        redis_client=None,
        generation_descriptor=PluginGenerationDescriptorV2(
            profile_id="schema-fixture", generation=1, digest="a" * 64
        ),
    )
    native_permission = native_permission_tool()
    tools[native_permission.name] = native_permission
    assert {"todowrite", "memory_search", "request_permission", "session_status"} <= set(tools)
    sessions.assert_not_called()
    return [definition.to_openai_format() for definition in convert_tools(tools)]


async def test_runtime_built_tool_schemas_have_explicit_string_literal_types(serialized_tools):
    errors = []
    for tool in serialized_tools:
        function = tool["function"]
        schema = function["parameters"]
        Draft202012Validator.check_schema(schema)
        errors.extend((function["name"], path) for path in literal_type_errors(schema))
    assert errors == []


@pytest.mark.parametrize("streaming", [False, True])
async def test_real_http_tool_serialization_satisfies_literal_type_contract(
    serialized_tools, streaming
):
    received = []

    async def serve(reader, writer):
        await reader.readline()
        headers = {}
        while line := await reader.readline():
            if line == b"\r\n":
                break
            key, value = line.decode().split(":", 1)
            headers[key.lower()] = value.strip()
        body = json.loads(await reader.readexactly(int(headers["content-length"])))
        received.append(body)
        errors = [
            path
            for tool in body.get("tools", [])
            for path in literal_type_errors(tool["function"]["parameters"])
        ]
        if errors:
            payload = json.dumps(
                {"error": {"type": "invalid_request_error", "message": "tool literal type missing"}}
            ).encode()
            status, content_type = "400 Bad Request", "application/json"
        elif body.get("stream"):
            chunk = {
                "id": "fixture",
                "model": "schema-fixture",
                "object": "chat.completion.chunk",
                "created": 1,
                "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
            }
            payload = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
            status, content_type = "200 OK", "text/event-stream"
        else:
            payload = json.dumps(
                {
                    "id": "fixture",
                    "model": "schema-fixture",
                    "object": "chat.completion",
                    "created": 1,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode()
            status, content_type = "200 OK", "application/json"
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + payload
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        provider = ProviderConfig(
            id=uuid4(),
            name="schema-fixture",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="fixture-unused",
            llm_model="openai/schema-fixture",
            base_url=f"http://127.0.0.1:{port}/v1",
            config={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            client = LiteLLMClient(
                LLMConfig(api_key="fixture-local-only", model=provider.llm_model),
                provider,
                cache=False,
            )
        messages = [{"role": "user", "content": "neutral"}]
        if streaming:
            chunks = []
            async with aclosing(client.generate_stream(messages, tools=serialized_tools)) as stream:
                async for chunk in stream:
                    chunks.append(chunk)
            assert chunks
        else:
            response = await client.generate(messages, tools=serialized_tools)
            assert response["content"] == "ok"
        assert len(received) == 1
        assert received[0]["tools"] == serialized_tools
    finally:
        server.close()
        await server.wait_closed()
