from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["security"])


@dataclass
class ExecutionContext:
    tool_name: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    agent_instance_id: str = ""
    workspace_id: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class EvaluationResult:
    allowed: bool = True
    reason: str = ""
    risk_level: str = "low"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SecurityPipeline:
    async def run_before(self, ctx: ExecutionContext) -> EvaluationResult:
        return EvaluationResult(
            allowed=True,
            reason="default-allow",
            risk_level="low",
        )

    async def run_after(
        self,
        ctx: ExecutionContext,
        exec_result: ExecutionResult,
    ) -> EvaluationResult:
        return EvaluationResult(
            allowed=True,
            reason="default-pass",
            risk_level="low",
        )


_pipeline: SecurityPipeline | None = None


def set_pipeline(pipeline: SecurityPipeline) -> None:
    global _pipeline
    _pipeline = pipeline


def get_pipeline() -> SecurityPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = SecurityPipeline()
    return _pipeline


def _parse_ctx(data: dict[str, Any]) -> ExecutionContext:
    ctx_raw = data.get("context", {})
    return ExecutionContext(
        tool_name=ctx_raw.get("tool_name", ""),
        params=ctx_raw.get("params", {}),
        agent_instance_id=ctx_raw.get("agent_instance_id", ""),
        workspace_id=ctx_raw.get("workspace_id", ""),
        timestamp=ctx_raw.get("timestamp", time.time()),
        metadata=ctx_raw.get("metadata", {}),
    )


def _parse_exec_result(data: dict[str, Any]) -> ExecutionResult:
    er_raw = data.get("execution_result", {})
    return ExecutionResult(
        result=er_raw.get("result"),
        error=er_raw.get("error"),
        duration_ms=er_raw.get("duration_ms", 0.0),
    )


@router.websocket("/api/v1/security/ws")
async def security_ws(websocket: WebSocket) -> None:
    """Real-time security evaluation over WebSocket.

    Clients send JSON messages with ``type`` = ``evaluate_before`` or
    ``evaluate_after``.  Each message must include an ``id`` field so
    the response can be correlated.

    Request (evaluate_before):
        {"type": "evaluate_before", "id": "req-1", "context": {...}}

    Request (evaluate_after):
        {"type": "evaluate_after", "id": "req-2", "context": {...},
         "execution_result": {...}}

    Response:
        {"id": "req-1", "result": {"allowed": true, "reason": "...", ...}}
    """
    await websocket.accept()
    pipeline = get_pipeline()

    try:
        while True:
            data: dict[str, Any] = await websocket.receive_json()
            msg_type: str = data.get("type", "")
            msg_id: str = data.get("id", "")

            if msg_type == "evaluate_before":
                ctx = _parse_ctx(data)
                result = await pipeline.run_before(ctx)
                await websocket.send_json({"id": msg_id, "result": result.to_dict()})

            elif msg_type == "evaluate_after":
                ctx = _parse_ctx(data)
                exec_result = _parse_exec_result(data)
                result = await pipeline.run_after(ctx, exec_result)
                await websocket.send_json({"id": msg_id, "result": result.to_dict()})

            else:
                await websocket.send_json({"id": msg_id, "error": f"unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.debug("Security WS client disconnected")
    except Exception:
        logger.exception("Security WS error")
