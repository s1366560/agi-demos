"""MemStack-side ACP client support for external ACP agents."""
# ruff: noqa: ANN401

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import tomllib
import uuid
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import orjson
import websockets
from acp import PROTOCOL_VERSION, connect_to_agent
from acp.exceptions import RequestError
from acp.interfaces import Agent, Client
from acp.schema import (
    ClientCapabilities,
    Implementation,
    NewSessionRequest,
    PromptRequest,
    SessionNotification,
)
from pydantic import BaseModel, Field, ValidationError

from src.configuration.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ExternalACPAgentConfig(BaseModel):
    """Configuration for an external ACP agent."""

    id: str
    name: str
    transport: Literal["stdio", "websocket"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    headers_env: dict[str, str] = Field(default_factory=dict)
    env_values: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    source: Literal["legacy", "tenant"] = "legacy"


class ExternalACPAgentSummary(BaseModel):
    id: str
    name: str
    transport: Literal["stdio", "websocket"]
    available: bool
    missing_env: list[str] = Field(default_factory=list)
    enabled: bool = True
    source: Literal["legacy", "tenant"] = "legacy"
    active_sessions: int = 0
    total_sessions: int = 0
    prompt_count: int = 0
    update_count: int = 0
    last_latency_ms: int | None = None
    last_error: str | None = None
    last_activity: datetime | None = None


class ExternalACPSessionResult(BaseModel):
    session_id: str
    remote_session_id: str


class ExternalACPPromptResult(BaseModel):
    result: dict[str, Any] | None = None
    updates: list[dict[str, Any]] = Field(default_factory=list)


class ExternalACPOperationEvent(BaseModel):
    tenant_id: str | None = None
    agent_id: str
    action: str
    status: Literal["success", "error"]
    timestamp: datetime
    duration_ms: int | None = None
    error: str | None = None


class ExternalACPSessionSummary(BaseModel):
    session_id: str
    remote_session_id: str
    agent_id: str
    owner_user_id: str
    tenant_id: str | None = None
    created_at: datetime
    last_activity: datetime


@dataclass(slots=True)
class ExternalACPSession:
    local_session_id: str
    remote_session_id: str
    agent_id: str
    owner_user_id: str
    transport: ExternalACPTransport
    tenant_id: str | None
    created_at: datetime
    last_activity: datetime


@dataclass(slots=True)
class _ExternalACPAgentMetrics:
    total_sessions: int = 0
    prompt_count: int = 0
    update_count: int = 0
    last_latency_ms: int | None = None
    last_error: str | None = None
    last_activity: datetime | None = None
    recent_events: deque[ExternalACPOperationEvent] = field(
        default_factory=lambda: deque(maxlen=50)
    )


class ExternalACPClientCallbacks:
    """Client callbacks for SDK-backed stdio ACP connections."""

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.agent: Agent | None = None

    def on_connect(self, conn: Agent) -> None:
        self.agent = conn

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        notification = SessionNotification(session_id=session_id, update=update, field_meta=kwargs or None)
        self.updates.append(notification.model_dump(mode="json", by_alias=True, exclude_none=True))

    async def request_permission(self, **kwargs: Any) -> Any:
        del kwargs
        raise RequestError.method_not_found("session/request_permission")

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RequestError.method_not_found(f"_{method}")

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        del method, params

    def drain_updates(self, remote_session_id: str) -> list[dict[str, Any]]:
        matching: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        for update in self.updates:
            if update.get("sessionId") == remote_session_id:
                matching.append(update)
            else:
                remaining.append(update)
        self.updates = remaining
        return matching


class ExternalACPTransport(ABC):
    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def new_session(
        self,
        *,
        cwd: str,
        additional_directories: list[str] | None,
        mcp_servers: list[dict[str, Any]],
        field_meta: dict[str, Any] | None = None,
    ) -> str: ...

    @abstractmethod
    async def prompt(
        self,
        *,
        remote_session_id: str,
        prompt: list[dict[str, Any]],
        message_id: str | None,
    ) -> ExternalACPPromptResult: ...

    @abstractmethod
    async def cancel(self, remote_session_id: str) -> None: ...

    @abstractmethod
    async def close(self, remote_session_id: str) -> None: ...


class StdioExternalACPTransport(ExternalACPTransport):
    def __init__(self, config: ExternalACPAgentConfig) -> None:
        self._config = config
        self._callbacks = ExternalACPClientCallbacks()
        self._process: asyncio.subprocess.Process | None = None
        self._connection: Agent | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        if not self._config.command:
            raise ValueError("stdio ACP agent requires command")
        env = os.environ.copy()
        env.update(_resolve_env_refs(self._config.env))
        env.update(self._config.env_values)
        self._process = await asyncio.create_subprocess_exec(
            self._config.command,
            *self._config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("failed to open stdio ACP process pipes")
        if self._process.stderr is not None:
            self._stderr_task = asyncio.create_task(self._drain_stderr(self._process.stderr))
        self._connection = connect_to_agent(
            cast(Client, self._callbacks),
            self._process.stdin,
            self._process.stdout,
            use_unstable_protocol=True,
        )
        await self._connection.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(name="memstack", title="MemStack", version="0.1.0"),
        )

    async def new_session(
        self,
        *,
        cwd: str,
        additional_directories: list[str] | None,
        mcp_servers: list[dict[str, Any]],
        field_meta: dict[str, Any] | None = None,
    ) -> str:
        request = NewSessionRequest.model_validate(
            {
                "cwd": cwd,
                "additionalDirectories": additional_directories,
                "mcpServers": mcp_servers,
                "_meta": field_meta,
            }
        )
        connection = self._require_connection()
        response = await connection.new_session(
            cwd=request.cwd,
            additional_directories=request.additional_directories,
            mcp_servers=request.mcp_servers,
            field_meta=request.field_meta,
        )
        return response.session_id

    async def prompt(
        self,
        *,
        remote_session_id: str,
        prompt: list[dict[str, Any]],
        message_id: str | None,
    ) -> ExternalACPPromptResult:
        request = PromptRequest.model_validate(
            {"sessionId": remote_session_id, "prompt": prompt, "messageId": message_id}
        )
        connection = self._require_connection()
        response = await connection.prompt(
            session_id=request.session_id,
            prompt=request.prompt,
            message_id=request.message_id,
        )
        updates = self._callbacks.drain_updates(remote_session_id)
        return ExternalACPPromptResult(
            result=response.model_dump(mode="json", by_alias=True, exclude_none=True),
            updates=updates,
        )

    async def cancel(self, remote_session_id: str) -> None:
        await self._require_connection().cancel(session_id=remote_session_id)

    async def close(self, remote_session_id: str) -> None:
        connection = self._require_connection()
        try:
            await connection.close_session(session_id=remote_session_id)
        except RequestError:
            await connection.cancel(session_id=remote_session_id)
        close = getattr(connection, "close", None)
        if close is not None:
            await close()
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2)
            except TimeoutError:
                self._process.kill()
        if self._stderr_task is not None:
            self._stderr_task.cancel()

    def _require_connection(self) -> Agent:
        if self._connection is None:
            raise RuntimeError("ACP stdio connection is not initialized")
        return self._connection

    async def _drain_stderr(self, stderr: asyncio.StreamReader) -> None:
        while not stderr.at_eof():
            line = await stderr.readline()
            if line:
                logger.debug("[ACP external %s stderr] %s", self._config.id, line.decode(errors="replace").rstrip())


class WebSocketJSONRPCClient:
    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self._url = url
        self._headers = headers
        self._socket: Any | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._updates: list[dict[str, Any]] = []
        self._reader_task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()

    async def connect(self) -> None:
        self._socket = await websockets.connect(self._url, additional_headers=self._headers or None)
        self._reader_task = asyncio.create_task(self._read_loop())

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        socket = self._require_socket()
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        async with self._send_lock:
            await socket.send(orjson.dumps(payload).decode("utf-8"))
        return await future

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        socket = self._require_socket()
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        async with self._send_lock:
            await socket.send(orjson.dumps(payload).decode("utf-8"))

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._socket is not None:
            await self._socket.close()

    def drain_updates(self, remote_session_id: str) -> list[dict[str, Any]]:
        matching: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        for update in self._updates:
            params = update.get("params")
            if isinstance(params, dict) and params.get("sessionId") == remote_session_id:
                matching.append(params)
            else:
                remaining.append(update)
        self._updates = remaining
        return matching

    def _require_socket(self) -> Any:
        if self._socket is None:
            raise RuntimeError("ACP WebSocket connection is not initialized")
        return self._socket

    async def _read_loop(self) -> None:
        socket = self._require_socket()
        async for raw_message in socket:
            try:
                message = orjson.loads(raw_message)
            except orjson.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if "id" in message and "method" not in message:
                self._handle_response(message)
            elif message.get("method") == "session/update":
                self._updates.append(message)
            elif "id" in message:
                await self._send_method_not_found(message)

    def _handle_response(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return
        if "error" in message:
            error = message["error"] if isinstance(message["error"], dict) else {}
            future.set_exception(
                RequestError(
                    int(error.get("code", -32603)),
                    str(error.get("message", "Error")),
                    error.get("data"),
                )
            )
            return
        future.set_result(message.get("result"))

    async def _send_method_not_found(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = message.get("method")
        error = RequestError.method_not_found(str(method)).to_error_obj()
        payload = {"jsonrpc": "2.0", "id": request_id, "error": error}
        async with self._send_lock:
            await self._require_socket().send(orjson.dumps(payload).decode("utf-8"))


class WebSocketExternalACPTransport(ExternalACPTransport):
    def __init__(self, config: ExternalACPAgentConfig) -> None:
        self._config = config
        if not config.url:
            raise ValueError("websocket ACP agent requires url")
        self._client = WebSocketJSONRPCClient(
            config.url,
            {**_resolve_env_refs(config.headers_env), **config.headers},
        )

    async def initialize(self) -> None:
        await self._client.connect()
        await self._client.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": ClientCapabilities().model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
                "clientInfo": Implementation(
                    name="memstack", title="MemStack", version="0.1.0"
                ).model_dump(mode="json", by_alias=True, exclude_none=True),
            },
        )

    async def new_session(
        self,
        *,
        cwd: str,
        additional_directories: list[str] | None,
        mcp_servers: list[dict[str, Any]],
        field_meta: dict[str, Any] | None = None,
    ) -> str:
        result = await self._client.request(
            "session/new",
            {
                "cwd": cwd,
                "additionalDirectories": additional_directories,
                "mcpServers": mcp_servers,
                "_meta": field_meta,
            },
        )
        if not isinstance(result, dict):
            raise RuntimeError("ACP WebSocket agent returned invalid session/new response")
        session_id = result.get("sessionId")
        if not isinstance(session_id, str):
            raise RuntimeError("ACP WebSocket agent returned invalid session/new response")
        return session_id

    async def prompt(
        self,
        *,
        remote_session_id: str,
        prompt: list[dict[str, Any]],
        message_id: str | None,
    ) -> ExternalACPPromptResult:
        result = await self._client.request(
            "session/prompt",
            {"sessionId": remote_session_id, "prompt": prompt, "messageId": message_id},
        )
        return ExternalACPPromptResult(
            result=result if isinstance(result, dict) else None,
            updates=self._client.drain_updates(remote_session_id),
        )

    async def cancel(self, remote_session_id: str) -> None:
        await self._client.notify("session/cancel", {"sessionId": remote_session_id})

    async def close(self, remote_session_id: str) -> None:
        try:
            await self._client.request("session/close", {"sessionId": remote_session_id})
        finally:
            await self._client.close()


class ExternalACPAgentService:
    """Registry and session manager for configured external ACP agents."""

    def __init__(self, configs: Iterable[ExternalACPAgentConfig]) -> None:
        self._configs = {config.id: config for config in configs}
        self._tenant_configs: dict[str, dict[str, ExternalACPAgentConfig]] = {}
        self._sessions: dict[str, ExternalACPSession] = {}
        self._metrics: dict[tuple[str | None, str], _ExternalACPAgentMetrics] = {}

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ExternalACPAgentService:
        resolved_settings = settings or get_settings()
        return cls(load_external_agent_configs(resolved_settings.acp_external_agents_config_path))

    def set_tenant_configs(
        self,
        tenant_id: str,
        configs: Iterable[ExternalACPAgentConfig],
    ) -> None:
        self._tenant_configs[tenant_id] = {config.id: config for config in configs}

    def list_agents(self, tenant_id: str | None = None) -> list[ExternalACPAgentSummary]:
        configs = (
            self._tenant_configs.get(tenant_id, {})
            if tenant_id is not None
            else self._configs
        )
        return [
            self._build_summary(tenant_id=tenant_id, config=config)
            for config in configs.values()
        ]

    def list_sessions(self, tenant_id: str | None = None) -> list[ExternalACPSessionSummary]:
        return [
            ExternalACPSessionSummary(
                session_id=session.local_session_id,
                remote_session_id=session.remote_session_id,
                agent_id=session.agent_id,
                owner_user_id=session.owner_user_id,
                tenant_id=session.tenant_id,
                created_at=session.created_at,
                last_activity=session.last_activity,
            )
            for session in self._sessions.values()
            if tenant_id is None or session.tenant_id == tenant_id
        ]

    def recent_events(
        self,
        tenant_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[ExternalACPOperationEvent]:
        events: list[ExternalACPOperationEvent] = []
        for (metric_tenant_id, _agent_id), metrics in self._metrics.items():
            if tenant_id is None or metric_tenant_id == tenant_id:
                events.extend(metrics.recent_events)
        events.sort(key=lambda event: event.timestamp, reverse=True)
        return events[:limit]

    async def new_session(
        self,
        *,
        agent_id: str,
        owner_user_id: str,
        cwd: str,
        additional_directories: list[str] | None,
        mcp_servers: list[dict[str, Any]],
        tenant_id: str | None = None,
        field_meta: dict[str, Any] | None = None,
    ) -> ExternalACPSessionResult:
        started = time.perf_counter()
        config = self._require_config(agent_id, tenant_id=tenant_id)
        try:
            transport = self._build_transport(config)
            await transport.initialize()
            remote_session_id = await transport.new_session(
                cwd=cwd,
                additional_directories=additional_directories,
                mcp_servers=mcp_servers,
                field_meta=field_meta,
            )
            local_session_id = str(uuid.uuid4())
            now = datetime.now(UTC)
            self._sessions[local_session_id] = ExternalACPSession(
                local_session_id=local_session_id,
                remote_session_id=remote_session_id,
                agent_id=agent_id,
                owner_user_id=owner_user_id,
                transport=transport,
                tenant_id=tenant_id,
                created_at=now,
                last_activity=now,
            )
            metrics = self._metrics_for(tenant_id, agent_id)
            metrics.total_sessions += 1
            self._record_event(
                tenant_id,
                agent_id,
                "session/new",
                started,
                status="success",
            )
            return ExternalACPSessionResult(
                session_id=local_session_id,
                remote_session_id=remote_session_id,
            )
        except Exception as exc:
            self._record_event(
                tenant_id,
                agent_id,
                "session/new",
                started,
                status="error",
                error=str(exc),
            )
            raise

    async def prompt(
        self,
        *,
        agent_id: str,
        session_id: str,
        owner_user_id: str,
        prompt: list[dict[str, Any]],
        message_id: str | None,
        tenant_id: str | None = None,
    ) -> ExternalACPPromptResult:
        started = time.perf_counter()
        session = self._require_session(agent_id, session_id, owner_user_id, tenant_id=tenant_id)
        try:
            result = await session.transport.prompt(
                remote_session_id=session.remote_session_id,
                prompt=prompt,
                message_id=message_id,
            )
            session.last_activity = datetime.now(UTC)
            metrics = self._metrics_for(tenant_id, agent_id)
            metrics.prompt_count += 1
            metrics.update_count += len(result.updates)
            self._record_event(
                tenant_id,
                agent_id,
                "session/prompt",
                started,
                status="success",
            )
            return result
        except Exception as exc:
            self._record_event(
                tenant_id,
                agent_id,
                "session/prompt",
                started,
                status="error",
                error=str(exc),
            )
            raise

    async def cancel(
        self,
        *,
        agent_id: str,
        session_id: str,
        owner_user_id: str,
        tenant_id: str | None = None,
    ) -> None:
        started = time.perf_counter()
        session = self._require_session(agent_id, session_id, owner_user_id, tenant_id=tenant_id)
        try:
            await session.transport.cancel(session.remote_session_id)
            session.last_activity = datetime.now(UTC)
            self._record_event(
                tenant_id,
                agent_id,
                "session/cancel",
                started,
                status="success",
            )
        except Exception as exc:
            self._record_event(
                tenant_id,
                agent_id,
                "session/cancel",
                started,
                status="error",
                error=str(exc),
            )
            raise

    async def close(
        self,
        *,
        agent_id: str,
        session_id: str,
        owner_user_id: str,
        tenant_id: str | None = None,
    ) -> None:
        started = time.perf_counter()
        session = self._require_session(agent_id, session_id, owner_user_id, tenant_id=tenant_id)
        try:
            await session.transport.close(session.remote_session_id)
            self._record_event(
                tenant_id,
                agent_id,
                "session/close",
                started,
                status="success",
            )
        except Exception as exc:
            self._record_event(
                tenant_id,
                agent_id,
                "session/close",
                started,
                status="error",
                error=str(exc),
            )
            raise
        finally:
            self._sessions.pop(session_id, None)

    def _require_config(
        self,
        agent_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ExternalACPAgentConfig:
        config = (
            self._tenant_configs.get(tenant_id, {}).get(agent_id)
            if tenant_id is not None
            else self._configs.get(agent_id)
        )
        if config is None:
            raise KeyError(agent_id)
        if not config.enabled:
            raise RuntimeError("ACP external agent is disabled")
        missing = self._missing_env(config)
        if missing:
            raise RuntimeError(f"Missing ACP external agent environment: {', '.join(missing)}")
        return config

    def _require_session(
        self,
        agent_id: str,
        session_id: str,
        owner_user_id: str,
        tenant_id: str | None = None,
    ) -> ExternalACPSession:
        session = self._sessions.get(session_id)
        if (
            session is None
            or session.agent_id != agent_id
            or session.owner_user_id != owner_user_id
            or session.tenant_id != tenant_id
        ):
            raise KeyError(session_id)
        return session

    def _build_transport(self, config: ExternalACPAgentConfig) -> ExternalACPTransport:
        if config.transport == "stdio":
            return StdioExternalACPTransport(config)
        return WebSocketExternalACPTransport(config)

    def _missing_env(self, config: ExternalACPAgentConfig) -> list[str]:
        refs = list(config.env.values()) + list(config.headers_env.values())
        return sorted(ref for ref in refs if ref and ref not in os.environ)

    def _build_summary(
        self,
        *,
        tenant_id: str | None,
        config: ExternalACPAgentConfig,
    ) -> ExternalACPAgentSummary:
        metrics = self._metrics_for(tenant_id, config.id)
        missing = self._missing_env(config)
        return ExternalACPAgentSummary(
            id=config.id,
            name=config.name,
            transport=config.transport,
            available=config.enabled and not missing,
            missing_env=missing,
            enabled=config.enabled,
            source=config.source,
            active_sessions=self._active_session_count(tenant_id, config.id),
            total_sessions=metrics.total_sessions,
            prompt_count=metrics.prompt_count,
            update_count=metrics.update_count,
            last_latency_ms=metrics.last_latency_ms,
            last_error=metrics.last_error,
            last_activity=metrics.last_activity,
        )

    def _active_session_count(self, tenant_id: str | None, agent_id: str) -> int:
        return sum(
            1
            for session in self._sessions.values()
            if session.tenant_id == tenant_id and session.agent_id == agent_id
        )

    def _metrics_for(
        self,
        tenant_id: str | None,
        agent_id: str,
    ) -> _ExternalACPAgentMetrics:
        key = (tenant_id, agent_id)
        metrics = self._metrics.get(key)
        if metrics is None:
            metrics = _ExternalACPAgentMetrics()
            self._metrics[key] = metrics
        return metrics

    def _record_event(
        self,
        tenant_id: str | None,
        agent_id: str,
        action: str,
        started: float,
        *,
        status: Literal["success", "error"],
        error: str | None = None,
    ) -> None:
        metrics = self._metrics_for(tenant_id, agent_id)
        duration_ms = int((time.perf_counter() - started) * 1000)
        now = datetime.now(UTC)
        metrics.last_latency_ms = duration_ms
        metrics.last_activity = now
        if error:
            metrics.last_error = error
        elif status == "success":
            metrics.last_error = None
        metrics.recent_events.append(
            ExternalACPOperationEvent(
                tenant_id=tenant_id,
                agent_id=agent_id,
                action=action,
                status=status,
                timestamp=now,
                duration_ms=duration_ms,
                error=error,
            )
        )


def load_external_agent_configs(path: str | None) -> list[ExternalACPAgentConfig]:
    if not path:
        return []
    config_path = Path(path)
    if not config_path.exists():
        logger.warning("[ACP] External agent config path does not exist: %s", config_path)
        return []

    if config_path.suffix == ".toml":
        raw_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    else:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))

    raw_agents = raw_config.get("agents") if isinstance(raw_config, dict) else raw_config
    if not isinstance(raw_agents, list):
        raise ValueError("ACP external agent config must contain an agents list")
    try:
        return [ExternalACPAgentConfig.model_validate(agent) for agent in raw_agents]
    except ValidationError:
        logger.exception("[ACP] Invalid external ACP agent configuration")
        raise


def _resolve_env_refs(refs: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for target_name, source_env_name in refs.items():
        if not source_env_name:
            continue
        value = os.environ.get(source_env_name)
        if value is not None:
            resolved[target_name] = value
    return resolved


_external_agent_service: ExternalACPAgentService | None = None


def get_external_agent_service() -> ExternalACPAgentService:
    global _external_agent_service
    if _external_agent_service is None:
        _external_agent_service = ExternalACPAgentService.from_settings()
    return _external_agent_service


def reset_external_agent_service_for_tests() -> None:
    global _external_agent_service
    _external_agent_service = None
