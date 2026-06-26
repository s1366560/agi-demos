"""Outbound ACP runner gateway and runner-backed transport."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from src.configuration.config import get_settings
from src.infrastructure.acp.client import (
    ExternalACPAgentConfig,
    ExternalACPPromptResult,
    ExternalACPTransport,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_acp_runner_repository import (
    ACPRunnerRepository,
)

logger = logging.getLogger(__name__)


class ACPRunnerUnavailableError(RuntimeError):
    """Raised when no connected runner can handle a request."""


@dataclass(slots=True)
class ACPRunnerSessionContext:
    """Runner ownership details for a created session."""

    pool_id: str
    pool_key: str
    runner_id: str
    runner_session_id: str


@dataclass(slots=True)
class _RunnerConnection:
    tenant_id: str
    pool_id: str
    pool_key: str
    runner_id: str
    connection_id: str
    websocket: WebSocket
    labels: dict[str, str] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    current_sessions: int = 0
    max_sessions: int = 1
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def request(
        self,
        request_type: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending[request_id] = future
        message = {
            "type": request_type,
            "id": request_id,
            "payload": payload,
        }
        try:
            async with self.send_lock:
                await self.websocket.send_json(message)
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        finally:
            self.pending.pop(request_id, None)

    def resolve_response(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if not isinstance(request_id, str):
            return
        future = self.pending.get(request_id)
        if future is None or future.done():
            return
        if message.get("ok") is False:
            error = message.get("error")
            future.set_exception(RuntimeError(str(error or "ACP runner request failed")))
            return
        result = message.get("result")
        future.set_result(result if isinstance(result, dict) else {})


class ACPRunnerGateway:
    """In-process live connection registry for outbound ACP runners."""

    def __init__(self) -> None:
        self._connections: dict[tuple[str, str, str], _RunnerConnection] = {}
        self._lock = asyncio.Lock()

    async def serve(self, websocket: WebSocket, token: str) -> None:
        """Accept and serve one outbound runner WebSocket connection."""
        pool = None
        async with async_session_factory() as db:
            repo = ACPRunnerRepository(db)
            token_row = await repo.consume_registration_token(token)
            if token_row is not None:
                pool = await repo.get_pool_by_id(token_row.pool_id)
            await db.commit()

        if pool is None or not pool.enabled or pool.deleted_at is not None:
            await websocket.close(code=4001, reason="Invalid ACP runner token")
            return

        await websocket.accept()
        connection: _RunnerConnection | None = None
        try:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    continue
                message_type = message.get("type")
                if message_type == "runner/register":
                    connection = await self._register_connection(
                        websocket=websocket,
                        pool_id=pool.id,
                        tenant_id=pool.tenant_id,
                        pool_key=pool.pool_key,
                        pool_labels={
                            str(key): str(value)
                            for key, value in (pool.labels or {}).items()
                            if value is not None
                        },
                        message=message,
                    )
                    await websocket.send_json(
                        {
                            "type": "runner/registered",
                            "runnerId": connection.runner_id,
                            "connectionId": connection.connection_id,
                        }
                    )
                elif message_type == "runner/heartbeat" and connection is not None:
                    await self._heartbeat(connection, message)
                elif message_type == "response" and connection is not None:
                    connection.resolve_response(message)
                elif connection is not None:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "error": f"unknown runner message type: {message_type}",
                        }
                    )
        except WebSocketDisconnect:
            logger.info("[ACP runner] disconnected")
        finally:
            if connection is not None:
                await self._disconnect(connection)

    async def request(
        self,
        *,
        tenant_id: str,
        pool_key: str,
        request_type: str,
        payload: dict[str, Any],
        required_labels: dict[str, str] | None = None,
        preferred_runner_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[dict[str, Any], ACPRunnerSessionContext]:
        connection = await self._select_connection(
            tenant_id=tenant_id,
            pool_key=pool_key,
            required_labels=required_labels or {},
            preferred_runner_id=preferred_runner_id,
        )
        result = await connection.request(
            request_type,
            payload,
            timeout_seconds=timeout_seconds or get_settings().acp_external_prompt_timeout_seconds,
        )
        if request_type == "session/new":
            connection.current_sessions = min(
                connection.current_sessions + 1,
                connection.max_sessions,
            )
        elif request_type == "session/close":
            connection.current_sessions = max(connection.current_sessions - 1, 0)
        if request_type in {"session/new", "session/close"}:
            await self._persist_instance(
                connection,
                status="ready",
                version=None,
                last_error=None,
            )
        return result, ACPRunnerSessionContext(
            pool_id=connection.pool_id,
            pool_key=connection.pool_key,
            runner_id=connection.runner_id,
            runner_session_id=str(payload.get("sessionId") or result.get("sessionId") or ""),
        )

    async def _register_connection(
        self,
        *,
        websocket: WebSocket,
        pool_id: str,
        tenant_id: str,
        pool_key: str,
        pool_labels: dict[str, str],
        message: dict[str, Any],
    ) -> _RunnerConnection:
        runner_id = str(message.get("runnerId") or uuid.uuid4())
        capabilities = message.get("capabilities")
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        runner_labels = capabilities.get("labels")
        labels = dict(pool_labels)
        if isinstance(runner_labels, dict):
            labels.update({str(key): str(value) for key, value in runner_labels.items()})
        max_sessions = _coerce_positive_int(message.get("maxSessions"), default=1)
        current_sessions = _coerce_non_negative_int(message.get("currentSessions"), default=0)
        connection = _RunnerConnection(
            tenant_id=tenant_id,
            pool_id=pool_id,
            pool_key=pool_key,
            runner_id=runner_id,
            connection_id=str(uuid.uuid4()),
            websocket=websocket,
            labels=labels,
            capabilities=capabilities,
            current_sessions=current_sessions,
            max_sessions=max_sessions,
        )
        async with self._lock:
            self._connections[(tenant_id, pool_key, runner_id)] = connection
        await self._persist_instance(
            connection,
            status="ready",
            version=_string_or_none(message.get("version")),
            last_error=None,
        )
        return connection

    async def _heartbeat(self, connection: _RunnerConnection, message: dict[str, Any]) -> None:
        connection.current_sessions = _coerce_non_negative_int(
            message.get("currentSessions"),
            default=connection.current_sessions,
        )
        connection.max_sessions = _coerce_positive_int(
            message.get("maxSessions"),
            default=connection.max_sessions,
        )
        capabilities = message.get("capabilities")
        if isinstance(capabilities, dict):
            connection.capabilities = capabilities
            labels = capabilities.get("labels")
            if isinstance(labels, dict):
                connection.labels.update({str(key): str(value) for key, value in labels.items()})
        await self._persist_instance(
            connection,
            status=str(message.get("status") or "ready"),
            version=_string_or_none(message.get("version")),
            last_error=_string_or_none(message.get("lastError")),
        )

    async def _disconnect(self, connection: _RunnerConnection) -> None:
        async with self._lock:
            self._connections.pop(
                (connection.tenant_id, connection.pool_key, connection.runner_id),
                None,
            )
        for pending in list(connection.pending.values()):
            if not pending.done():
                pending.set_exception(ACPRunnerUnavailableError("ACP runner disconnected"))
        async with async_session_factory() as db:
            repo = ACPRunnerRepository(db)
            await repo.mark_runner_offline(
                tenant_id=connection.tenant_id,
                runner_id=connection.runner_id,
                connection_id=connection.connection_id,
                last_error="runner disconnected",
            )
            await db.commit()

    async def _select_connection(
        self,
        *,
        tenant_id: str,
        pool_key: str,
        required_labels: dict[str, str],
        preferred_runner_id: str | None,
    ) -> _RunnerConnection:
        async with self._lock:
            candidates = [
                connection
                for (conn_tenant_id, conn_pool_key, _runner_id), connection in self._connections.items()
                if conn_tenant_id == tenant_id and conn_pool_key == pool_key
            ]
        if preferred_runner_id is not None:
            candidates = [
                connection for connection in candidates if connection.runner_id == preferred_runner_id
            ]
        candidates = [
            connection
            for connection in candidates
            if _labels_match(connection.labels, required_labels)
            and connection.current_sessions < connection.max_sessions
        ]
        if not candidates:
            raise ACPRunnerUnavailableError("No ready ACP runner is available for this pool")
        return sorted(candidates, key=lambda item: (item.current_sessions, item.runner_id))[0]

    async def _persist_instance(
        self,
        connection: _RunnerConnection,
        *,
        status: str,
        version: str | None,
        last_error: str | None,
    ) -> None:
        async with async_session_factory() as db:
            pool = await ACPRunnerRepository(db).get_pool_by_id(connection.pool_id)
            if pool is None:
                return
            await ACPRunnerRepository(db).upsert_instance(
                pool=pool,
                runner_id=connection.runner_id,
                status=status,
                connection_id=connection.connection_id,
                version=version,
                capabilities=connection.capabilities,
                current_sessions=connection.current_sessions,
                max_sessions=connection.max_sessions,
                last_error=last_error,
            )
            await db.commit()


class RunnerExternalACPTransport(ExternalACPTransport):
    """External ACP transport that delegates execution to an outbound runner."""

    def __init__(self, config: ExternalACPAgentConfig) -> None:
        self._config = config
        self._session_context: ACPRunnerSessionContext | None = None

    @property
    def session_context(self) -> ACPRunnerSessionContext | None:
        return self._session_context

    async def initialize(self) -> None:
        if not self._config.tenant_id or not self._config.runner_pool_key:
            raise ValueError("runner-backed ACP agents require tenant_id and runner_pool_key")

    async def new_session(
        self,
        *,
        cwd: str,
        additional_directories: list[str] | None,
        mcp_servers: list[dict[str, Any]],
        field_meta: dict[str, Any] | None = None,
    ) -> str:
        self._validate_cwd_policy(cwd)
        runner_session_id = str(uuid.uuid4())
        result, context = await get_acp_runner_gateway().request(
            tenant_id=self._require_tenant_id(),
            pool_key=self._require_pool_key(),
            request_type="session/new",
            required_labels=self._config.required_labels,
            payload={
                "sessionId": runner_session_id,
                "agentId": self._config.id,
                "config": self._runner_config_payload(),
                "cwd": cwd,
                "additionalDirectories": additional_directories,
                "mcpServers": mcp_servers,
                "_meta": field_meta,
            },
        )
        self._session_context = context
        return str(result.get("sessionId") or runner_session_id)

    async def prompt(
        self,
        *,
        remote_session_id: str,
        prompt: list[dict[str, Any]],
        message_id: str | None,
    ) -> ExternalACPPromptResult:
        result, _context = await get_acp_runner_gateway().request(
            tenant_id=self._require_tenant_id(),
            pool_key=self._require_pool_key(),
            request_type="session/prompt",
            required_labels=self._config.required_labels,
            preferred_runner_id=self._session_context.runner_id if self._session_context else None,
            payload={
                "sessionId": remote_session_id,
                "prompt": prompt,
                "messageId": message_id,
            },
        )
        result_value = result.get("result")
        updates_value = result.get("updates")
        updates = [item for item in updates_value if isinstance(item, dict)] if isinstance(
            updates_value,
            list,
        ) else []
        return ExternalACPPromptResult(
            result=result_value if isinstance(result_value, dict) else result,
            updates=updates,
        )

    async def cancel(self, remote_session_id: str) -> None:
        with contextlib.suppress(ACPRunnerUnavailableError):
            await get_acp_runner_gateway().request(
                tenant_id=self._require_tenant_id(),
                pool_key=self._require_pool_key(),
                request_type="session/cancel",
                required_labels=self._config.required_labels,
                preferred_runner_id=self._session_context.runner_id if self._session_context else None,
                payload={"sessionId": remote_session_id},
            )

    async def close(self, remote_session_id: str) -> None:
        await get_acp_runner_gateway().request(
            tenant_id=self._require_tenant_id(),
            pool_key=self._require_pool_key(),
            request_type="session/close",
            required_labels=self._config.required_labels,
            preferred_runner_id=self._session_context.runner_id if self._session_context else None,
            payload={"sessionId": remote_session_id},
        )

    async def bind_local_session(
        self,
        *,
        local_session_id: str,
        owner_user_id: str,
    ) -> None:
        if self._session_context is None:
            return
        async with async_session_factory() as db:
            await ACPRunnerRepository(db).create_session_mapping(
                session_id=local_session_id,
                tenant_id=self._require_tenant_id(),
                pool_id=self._session_context.pool_id,
                runner_id=self._session_context.runner_id,
                agent_key=self._config.id,
                owner_user_id=owner_user_id,
                remote_session_id=self._session_context.runner_session_id,
            )
            await db.commit()

    async def mark_session_error(self, *, local_session_id: str, error: str) -> None:
        await self.mark_local_session_status(
            local_session_id=local_session_id,
            status="failed",
            last_error=error,
        )

    async def mark_local_session_status(
        self,
        *,
        local_session_id: str,
        status: str,
        last_error: str | None = None,
    ) -> None:
        async with async_session_factory() as db:
            await ACPRunnerRepository(db).update_session_status(
                session_id=local_session_id,
                status=status,
                last_error=last_error,
            )
            await db.commit()

    def _runner_config_payload(self) -> dict[str, Any]:
        payload = self._config.model_dump(mode="json", exclude_none=True)
        payload.pop("tenant_id", None)
        payload.pop("runner_pool_key", None)
        payload.pop("required_labels", None)
        payload.pop("cwd_policy", None)
        return payload

    def _require_tenant_id(self) -> str:
        if not self._config.tenant_id:
            raise ValueError("runner-backed ACP agent is missing tenant_id")
        return self._config.tenant_id

    def _require_pool_key(self) -> str:
        if not self._config.runner_pool_key:
            raise ValueError("runner-backed ACP agent is missing runner_pool_key")
        return self._config.runner_pool_key

    def _validate_cwd_policy(self, cwd: str) -> None:
        roots = self._config.cwd_policy.get("allowed_roots")
        if not isinstance(roots, list) or not roots:
            return
        allowed_roots = [root for root in roots if isinstance(root, str) and root]
        if allowed_roots and not any(
            cwd == root or cwd.startswith(f"{root.rstrip('/')}/") for root in allowed_roots
        ):
            raise ValueError("ACP session cwd is outside configured runner cwd policy")


_gateway: ACPRunnerGateway | None = None


def get_acp_runner_gateway() -> ACPRunnerGateway:
    global _gateway
    if _gateway is None:
        _gateway = ACPRunnerGateway()
    return _gateway


def reset_acp_runner_gateway_for_tests() -> None:
    global _gateway
    _gateway = None


def _labels_match(labels: dict[str, str], required: dict[str, str]) -> bool:
    return all(labels.get(key) == value for key, value in required.items())


def _coerce_positive_int(value: object, *, default: int) -> int:
    number = _coerce_non_negative_int(value, default=default)
    return max(number, 1)


def _coerce_non_negative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, str):
        try:
            return max(int(value), 0)
        except ValueError:
            return default
    return default


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
