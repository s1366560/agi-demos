"""Deterministic OpenAI-compatible fixture for credential-free Agent E2E tests."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

E2E_MODEL = "memstack-e2e"
E2E_AGENT_RESPONSE = "E2E_AGENT_OK"
E2E_GOAL_RESPONSE = json.dumps(
    {
        "goal_achieved": True,
        "reason": "The deterministic E2E response was delivered.",
    },
    separators=(",", ":"),
)
E2E_BROKER_RESPONSE = {
    "tier": "medium",
    "require_vision": False,
    "require_tools": False,
    "category": "analysis",
    "rationale": "Deterministic E2E routing verdict.",
}

app = FastAPI(title="MemStack deterministic OpenAI fixture")


def _chunk(content: str, *, finish_reason: str | None) -> dict[str, Any]:
    delta: dict[str, str] = {}
    if content:
        delta = {"role": "assistant", "content": content}
    return {
        "id": "chatcmpl-memstack-e2e",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": E2E_MODEL,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def _stream_completion(content: str) -> Iterator[str]:
    for payload in (
        _chunk(content, finish_reason=None),
        _chunk("", finish_reason="stop"),
    ):
        yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/v1/models")
async def list_models() -> dict[str, object]:
    """Expose the minimal model catalog used by provider health checks."""
    return {
        "object": "list",
        "data": [{"id": E2E_MODEL, "object": "model", "owned_by": "memstack-e2e"}],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    """Return a deterministic response without inspecting or logging secrets."""
    raw_body = cast("object", await request.json())
    if not isinstance(raw_body, Mapping):
        raise HTTPException(status_code=400, detail="Request body must be an object")
    body = cast("Mapping[str, object]", raw_body)

    is_streaming = body.get("stream") is True
    tools = body.get("tools")
    has_route_request_tool = False
    if isinstance(tools, list):
        for raw_tool in cast("list[object]", tools):
            if not isinstance(raw_tool, Mapping):
                continue
            function = cast("Mapping[str, object]", raw_tool).get("function")
            if not isinstance(function, Mapping):
                continue
            function_mapping = cast("Mapping[str, object]", function)
            if function_mapping.get("name") == "route_request":
                has_route_request_tool = True
                break

    content = E2E_AGENT_RESPONSE if is_streaming else E2E_GOAL_RESPONSE
    if is_streaming:
        return StreamingResponse(_stream_completion(content), media_type="text/event-stream")

    message: dict[str, object] = {"role": "assistant", "content": content}
    finish_reason = "stop"
    if has_route_request_tool:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-memstack-e2e-route",
                    "type": "function",
                    "function": {
                        "name": "route_request",
                        "arguments": json.dumps(E2E_BROKER_RESPONSE, separators=(",", ":")),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"

    return JSONResponse(
        {
            "id": "chatcmpl-memstack-e2e",
            "object": "chat.completion",
            "created": 0,
            "model": E2E_MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
