"""Agent Client Protocol endpoints."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, cast

from acp.agent.router import build_agent_router
from acp.interfaces import Agent
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.config import get_settings
from src.configuration.di_container import DIContainer
from src.infrastructure.acp.client import (
    ExternalACPAgentConfig,
    ExternalACPAgentSummary,
    ExternalACPOperationEvent,
    ExternalACPPromptResult,
    ExternalACPSessionResult,
    ExternalACPSessionSummary,
    get_external_agent_service,
)
from src.infrastructure.acp.event_mapper import ACPUpdate, update_to_payload
from src.infrastructure.acp.jsonrpc import ACPWebSocketJSONRPCPeer
from src.infrastructure.acp.server import MemStackACPAgent
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.primary.web.websocket.auth import (
    authenticate_websocket,
    extract_websocket_api_key,
    select_websocket_auth_subprotocol,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    ACPExternalAgentConfigModel,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_acp_external_agent_config_repository import (
    ACPExternalAgentConfigRepository,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/acp", tags=["acp"])

_AGENT_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"
_SECRET_UNCHANGED_SENTINEL = "__MEMSTACK_SECRET_UNCHANGED__"


class ExternalACPSessionRequest(BaseModel):
    cwd: str
    additional_directories: list[str] | None = Field(default=None, alias="additionalDirectories")
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list, alias="mcpServers")
    field_meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class ExternalACPPromptRequest(BaseModel):
    prompt: list[dict[str, Any]]
    message_id: str | None = Field(default=None, alias="messageId")


class ExternalACPAckResponse(BaseModel):
    ok: bool = True


class ACPConfigValue(BaseModel):
    type: str = Field(pattern="^(env_ref|secret)$")
    value: str | None = None
    has_value: bool = False


class TenantExternalACPAgentCreateRequest(BaseModel):
    agent_key: str = Field(pattern=_AGENT_KEY_PATTERN, alias="agentKey")
    name: str = Field(min_length=1, max_length=255)
    transport: str = Field(pattern="^(stdio|websocket)$")
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, ACPConfigValue] = Field(default_factory=dict)
    headers: dict[str, ACPConfigValue] = Field(default_factory=dict)
    enabled: bool = True


class TenantExternalACPAgentUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    transport: str = Field(pattern="^(stdio|websocket)$")
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, ACPConfigValue] = Field(default_factory=dict)
    headers: dict[str, ACPConfigValue] = Field(default_factory=dict)
    enabled: bool = True


class TenantExternalACPAgentResponse(BaseModel):
    id: str
    agent_key: str = Field(alias="agentKey")
    name: str
    transport: str
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, ACPConfigValue] = Field(default_factory=dict)
    headers: dict[str, ACPConfigValue] = Field(default_factory=dict)
    enabled: bool
    source: str = "tenant"
    available: bool
    missing_env: list[str] = Field(default_factory=list, alias="missingEnv")
    active_sessions: int = Field(default=0, alias="activeSessions")
    total_sessions: int = Field(default=0, alias="totalSessions")
    prompt_count: int = Field(default=0, alias="promptCount")
    update_count: int = Field(default=0, alias="updateCount")
    last_latency_ms: int | None = Field(default=None, alias="lastLatencyMs")
    last_error: str | None = Field(default=None, alias="lastError")
    last_activity: Any | None = Field(default=None, alias="lastActivity")
    created_at: Any | None = Field(default=None, alias="createdAt")
    updated_at: Any | None = Field(default=None, alias="updatedAt")


class TenantACPStatusResponse(BaseModel):
    enabled: bool
    websocket_enabled: bool = Field(alias="websocketEnabled")
    http_base_url: str = Field(alias="httpBaseUrl")
    external_agents_config_path: str | None = Field(default=None, alias="externalAgentsConfigPath")
    agent_count: int = Field(alias="agentCount")
    available_count: int = Field(alias="availableCount")
    missing_env_count: int = Field(alias="missingEnvCount")
    active_session_count: int = Field(alias="activeSessionCount")
    agents: list[TenantExternalACPAgentResponse]
    sessions: list[ExternalACPSessionSummary]
    recent_events: list[ExternalACPOperationEvent] = Field(alias="recentEvents")


class TenantExternalACPSessionRequest(ExternalACPSessionRequest):
    project_id: str | None = Field(default=None, alias="projectId")


class TenantExternalACPTestRequest(TenantExternalACPSessionRequest):
    prompt: str = "请只回复 PONG"
    timeout_seconds: float = Field(default=30, alias="timeoutSeconds")


class TenantExternalACPTestResponse(BaseModel):
    success: bool
    session_id: str | None = Field(default=None, alias="sessionId")
    remote_session_id: str | None = Field(default=None, alias="remoteSessionId")
    assistant_text: str = Field(default="", alias="assistantText")
    updates_count: int = Field(default=0, alias="updatesCount")
    duration_ms: int = Field(alias="durationMs")
    error: str | None = None


def _validate_agent_shape(
    *,
    transport: str,
    command: str | None,
    url: str | None,
) -> None:
    if transport == "stdio" and not command:
        raise ValueError("stdio ACP agent requires command")
    if transport == "websocket" and not url:
        raise ValueError("websocket ACP agent requires url")


def _ensure_absolute_cwd(cwd: str) -> None:
    if not Path(cwd).is_absolute():
        raise ValueError("ACP session cwd must be an absolute path")


def _stored_config_values_for_response(raw_values: dict[str, Any]) -> dict[str, ACPConfigValue]:
    result: dict[str, ACPConfigValue] = {}
    for name, raw_value in raw_values.items():
        if not isinstance(raw_value, dict):
            continue
        value_type = str(raw_value.get("type") or "")
        stored_value = raw_value.get("value")
        if value_type == "env_ref":
            result[name] = ACPConfigValue(
                type="env_ref",
                value=stored_value if isinstance(stored_value, str) else "",
                has_value=bool(stored_value),
            )
        elif value_type == "secret":
            result[name] = ACPConfigValue(
                type="secret",
                value=_SECRET_UNCHANGED_SENTINEL if stored_value else None,
                has_value=bool(stored_value),
            )
    return result


def _store_config_values(
    values: dict[str, ACPConfigValue],
    existing: dict[str, Any] | None,
) -> dict[str, object]:
    encryption_service = get_encryption_service()
    stored: dict[str, object] = {}
    existing = existing or {}
    for name, value in values.items():
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("ACP env/header names must be non-empty")
        if value.type == "env_ref":
            if not value.value or not value.value.strip():
                raise ValueError("ACP env_ref values must name an environment variable")
            stored[normalized_name] = {"type": "env_ref", "value": value.value.strip()}
            continue
        existing_entry = existing.get(normalized_name)
        existing_secret = existing_entry if isinstance(existing_entry, dict) else {}
        existing_encrypted = existing_secret.get("value") if existing_secret.get("type") == "secret" else None
        if value.value == _SECRET_UNCHANGED_SENTINEL and isinstance(existing_encrypted, str):
            stored[normalized_name] = {"type": "secret", "value": existing_encrypted}
            continue
        if not value.value:
            if isinstance(existing_encrypted, str):
                stored[normalized_name] = {"type": "secret", "value": existing_encrypted}
                continue
            raise ValueError("ACP secret values are required when creating a secret entry")
        stored[normalized_name] = {"type": "secret", "value": encryption_service.encrypt(value.value)}
    return stored


def _decrypt_stored_values(
    raw_values: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    env_refs: dict[str, str] = {}
    secrets: dict[str, str] = {}
    encryption_service = get_encryption_service()
    for name, raw_value in raw_values.items():
        if not isinstance(raw_value, dict):
            continue
        value_type = raw_value.get("type")
        stored_value = raw_value.get("value")
        if not isinstance(stored_value, str) or not stored_value:
            continue
        if value_type == "env_ref":
            env_refs[name] = stored_value
        elif value_type == "secret":
            secrets[name] = encryption_service.decrypt(stored_value)
    return env_refs, secrets


def _runtime_config_from_row(row: ACPExternalAgentConfigModel) -> ExternalACPAgentConfig:
    env_refs, env_values = _decrypt_stored_values(row.env or {})
    header_refs, header_values = _decrypt_stored_values(row.headers or {})
    return ExternalACPAgentConfig(
        id=row.agent_key,
        name=row.name,
        transport=cast(Any, row.transport),
        command=row.command,
        args=list(row.args or []),
        url=row.url,
        env=env_refs,
        headers_env=header_refs,
        env_values=env_values,
        headers=header_values,
        enabled=row.enabled,
        source="tenant",
    )


def _build_field_meta(
    *,
    project_id: str | None,
    existing: dict[str, Any] | None,
) -> dict[str, Any] | None:
    meta = dict(existing or {})
    if project_id:
        memstack_meta = meta.get("memstack")
        if not isinstance(memstack_meta, dict):
            memstack_meta = {}
        memstack_meta["projectId"] = project_id
        meta["memstack"] = memstack_meta
    return meta or None


def _summary_for_agent(
    summaries: list[ExternalACPAgentSummary],
    agent_key: str,
) -> ExternalACPAgentSummary | None:
    return next((summary for summary in summaries if summary.id == agent_key), None)


def _response_from_row(
    row: ACPExternalAgentConfigModel,
    summary: ExternalACPAgentSummary | None,
) -> TenantExternalACPAgentResponse:
    return TenantExternalACPAgentResponse(
        id=row.id,
        agentKey=row.agent_key,
        name=row.name,
        transport=row.transport,
        command=row.command,
        args=list(row.args or []),
        url=row.url,
        env=_stored_config_values_for_response(row.env or {}),
        headers=_stored_config_values_for_response(row.headers or {}),
        enabled=row.enabled,
        source=summary.source if summary else "tenant",
        available=summary.available if summary else row.enabled,
        missingEnv=summary.missing_env if summary else [],
        activeSessions=summary.active_sessions if summary else 0,
        totalSessions=summary.total_sessions if summary else 0,
        promptCount=summary.prompt_count if summary else 0,
        updateCount=summary.update_count if summary else 0,
        lastLatencyMs=summary.last_latency_ms if summary else None,
        lastError=summary.last_error if summary else None,
        lastActivity=summary.last_activity if summary else None,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


async def _refresh_tenant_agent_cache(
    db: AsyncSession,
    tenant_id: str,
) -> tuple[list[ACPExternalAgentConfigModel], list[ExternalACPAgentSummary]]:
    rows = await ACPExternalAgentConfigRepository(db).list_by_tenant(tenant_id)
    get_external_agent_service().set_tenant_configs(
        tenant_id,
        [_runtime_config_from_row(row) for row in rows],
    )
    summaries = get_external_agent_service().list_agents(tenant_id=tenant_id)
    return rows, summaries


def _extract_text_from_prompt_result(result: ExternalACPPromptResult) -> str:
    chunks: list[str] = []
    for item in result.updates:
        update = item.get("update")
        if not isinstance(update, dict):
            params = item.get("params")
            update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue
        content = update.get("content")
        if isinstance(content, dict) and content.get("type") == "text":
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)


@router.websocket("/ws")
async def acp_websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(None, description="Legacy API key query parameter"),
) -> None:
    """ACP JSON-RPC WebSocket endpoint."""
    settings = get_settings()
    if not settings.acp_enabled or not settings.acp_websocket_enabled:
        await websocket.close(code=1013, reason="ACP is disabled")
        return

    api_key = extract_websocket_api_key(websocket, token)
    if not api_key:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    async with async_session_factory() as auth_db:
        auth_result = await authenticate_websocket(api_key, auth_db)
    if not auth_result:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    user_id, tenant_id = auth_result
    await websocket.accept(subprotocol=select_websocket_auth_subprotocol(websocket))

    container = cast(DIContainer, websocket.app.state.container)
    peer_ref: dict[str, ACPWebSocketJSONRPCPeer] = {}

    async def emit_update(session_id: str, update: ACPUpdate) -> None:
        await peer_ref["peer"].send_notification(
            "session/update",
            {"sessionId": session_id, "update": update_to_payload(update)},
        )

    agent = MemStackACPAgent(
        container=container,
        session_factory=async_session_factory,
        user_id=user_id,
        tenant_id=tenant_id,
        api_key=api_key,
        emit_update=emit_update,
        settings=settings,
    )
    handler = build_agent_router(cast(Agent, agent), use_unstable_protocol=True)
    peer = ACPWebSocketJSONRPCPeer(websocket, handler)
    peer_ref["peer"] = peer
    await peer.serve()


@router.get(
    "/tenants/{tenant_id}/status",
    response_model=TenantACPStatusResponse,
)
async def get_tenant_acp_status(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantACPStatusResponse:
    await require_tenant_access(db, cast(Any, current_user), tenant_id)
    rows, summaries = await _refresh_tenant_agent_cache(db, tenant_id)
    agents = [
        _response_from_row(row, _summary_for_agent(summaries, row.agent_key))
        for row in rows
    ]
    settings = get_settings()
    return TenantACPStatusResponse(
        enabled=settings.acp_enabled,
        websocketEnabled=settings.acp_websocket_enabled,
        httpBaseUrl=settings.acp_http_base_url,
        externalAgentsConfigPath=settings.acp_external_agents_config_path,
        agentCount=len(agents),
        availableCount=sum(1 for agent in agents if agent.available),
        missingEnvCount=sum(len(agent.missing_env) for agent in agents),
        activeSessionCount=sum(agent.active_sessions for agent in agents),
        agents=agents,
        sessions=get_external_agent_service().list_sessions(tenant_id=tenant_id),
        recentEvents=get_external_agent_service().recent_events(tenant_id=tenant_id),
    )


@router.get(
    "/tenants/{tenant_id}/external-agents",
    response_model=list[TenantExternalACPAgentResponse],
)
async def list_tenant_external_agents(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TenantExternalACPAgentResponse]:
    await require_tenant_access(db, cast(Any, current_user), tenant_id)
    rows, summaries = await _refresh_tenant_agent_cache(db, tenant_id)
    return [
        _response_from_row(row, _summary_for_agent(summaries, row.agent_key))
        for row in rows
    ]


@router.post(
    "/tenants/{tenant_id}/external-agents",
    response_model=TenantExternalACPAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant_external_agent(
    tenant_id: str,
    payload: TenantExternalACPAgentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantExternalACPAgentResponse:
    await require_tenant_access(db, cast(Any, current_user), tenant_id, require_admin=True)
    try:
        _validate_agent_shape(
            transport=payload.transport,
            command=payload.command,
            url=payload.url,
        )
        repo = ACPExternalAgentConfigRepository(db)
        row = await repo.create_or_restore(
            tenant_id=tenant_id,
            agent_key=payload.agent_key,
            name=payload.name,
            transport=payload.transport,
            command=payload.command,
            args=payload.args,
            url=payload.url,
            env=_store_config_values(payload.env, None),
            headers=_store_config_values(payload.headers, None),
            enabled=payload.enabled,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows, summaries = await _refresh_tenant_agent_cache(db, tenant_id)
    row = next((item for item in rows if item.id == row.id), row)
    return _response_from_row(row, _summary_for_agent(summaries, row.agent_key))


@router.get(
    "/tenants/{tenant_id}/external-agents/{agent_key}",
    response_model=TenantExternalACPAgentResponse,
)
async def get_tenant_external_agent(
    tenant_id: str,
    agent_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantExternalACPAgentResponse:
    await require_tenant_access(db, cast(Any, current_user), tenant_id)
    row = await ACPExternalAgentConfigRepository(db).get_by_tenant_and_key(tenant_id, agent_key)
    if row is None:
        raise HTTPException(status_code=404, detail=_("External ACP agent not found"))
    await _refresh_tenant_agent_cache(db, tenant_id)
    summary = _summary_for_agent(get_external_agent_service().list_agents(tenant_id=tenant_id), agent_key)
    return _response_from_row(row, summary)


@router.put(
    "/tenants/{tenant_id}/external-agents/{agent_key}",
    response_model=TenantExternalACPAgentResponse,
)
async def update_tenant_external_agent(
    tenant_id: str,
    agent_key: str,
    payload: TenantExternalACPAgentUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantExternalACPAgentResponse:
    await require_tenant_access(db, cast(Any, current_user), tenant_id, require_admin=True)
    repo = ACPExternalAgentConfigRepository(db)
    row = await repo.get_by_tenant_and_key(tenant_id, agent_key)
    if row is None:
        raise HTTPException(status_code=404, detail=_("External ACP agent not found"))
    try:
        _validate_agent_shape(
            transport=payload.transport,
            command=payload.command,
            url=payload.url,
        )
        row = await repo.update(
            row,
            name=payload.name,
            transport=payload.transport,
            command=payload.command,
            args=payload.args,
            url=payload.url,
            env=_store_config_values(payload.env, row.env or {}),
            headers=_store_config_values(payload.headers, row.headers or {}),
            enabled=payload.enabled,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows, summaries = await _refresh_tenant_agent_cache(db, tenant_id)
    row = next((item for item in rows if item.id == row.id), row)
    return _response_from_row(row, _summary_for_agent(summaries, row.agent_key))


@router.delete(
    "/tenants/{tenant_id}/external-agents/{agent_key}",
    response_model=ExternalACPAckResponse,
)
async def delete_tenant_external_agent(
    tenant_id: str,
    agent_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExternalACPAckResponse:
    await require_tenant_access(db, cast(Any, current_user), tenant_id, require_admin=True)
    repo = ACPExternalAgentConfigRepository(db)
    row = await repo.get_by_tenant_and_key(tenant_id, agent_key)
    if row is None:
        raise HTTPException(status_code=404, detail=_("External ACP agent not found"))
    await repo.soft_delete(row)
    await db.commit()
    await _refresh_tenant_agent_cache(db, tenant_id)
    return ExternalACPAckResponse()


@router.get(
    "/tenants/{tenant_id}/sessions",
    response_model=list[ExternalACPSessionSummary],
)
async def list_tenant_external_agent_sessions(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExternalACPSessionSummary]:
    await require_tenant_access(db, cast(Any, current_user), tenant_id)
    await _refresh_tenant_agent_cache(db, tenant_id)
    return get_external_agent_service().list_sessions(tenant_id=tenant_id)


@router.post(
    "/tenants/{tenant_id}/external-agents/{agent_key}/sessions",
    response_model=ExternalACPSessionResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant_external_agent_session(
    tenant_id: str,
    agent_key: str,
    payload: TenantExternalACPSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExternalACPSessionResult:
    await require_tenant_access(db, cast(Any, current_user), tenant_id, require_admin=True)
    try:
        _ensure_absolute_cwd(payload.cwd)
        await _refresh_tenant_agent_cache(db, tenant_id)
        return await get_external_agent_service().new_session(
            agent_id=agent_key,
            owner_user_id=str(current_user.id),
            cwd=payload.cwd,
            additional_directories=payload.additional_directories,
            mcp_servers=payload.mcp_servers,
            tenant_id=tenant_id,
            field_meta=_build_field_meta(
                project_id=payload.project_id,
                existing=payload.field_meta,
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_("External ACP agent not found")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/tenants/{tenant_id}/external-agents/{agent_key}/sessions/{session_id}/prompt",
    response_model=ExternalACPPromptResult,
)
async def prompt_tenant_external_agent_session(
    tenant_id: str,
    agent_key: str,
    session_id: str,
    payload: ExternalACPPromptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExternalACPPromptResult:
    await require_tenant_access(db, cast(Any, current_user), tenant_id, require_admin=True)
    try:
        await _refresh_tenant_agent_cache(db, tenant_id)
        return await get_external_agent_service().prompt(
            agent_id=agent_key,
            session_id=session_id,
            owner_user_id=str(current_user.id),
            prompt=payload.prompt,
            message_id=payload.message_id,
            tenant_id=tenant_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_("External ACP session not found")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/tenants/{tenant_id}/external-agents/{agent_key}/sessions/{session_id}/cancel",
    response_model=ExternalACPAckResponse,
)
async def cancel_tenant_external_agent_session(
    tenant_id: str,
    agent_key: str,
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExternalACPAckResponse:
    await require_tenant_access(db, cast(Any, current_user), tenant_id, require_admin=True)
    try:
        await _refresh_tenant_agent_cache(db, tenant_id)
        await get_external_agent_service().cancel(
            agent_id=agent_key,
            session_id=session_id,
            owner_user_id=str(current_user.id),
            tenant_id=tenant_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_("External ACP session not found")) from exc
    return ExternalACPAckResponse()


@router.delete(
    "/tenants/{tenant_id}/external-agents/{agent_key}/sessions/{session_id}",
    response_model=ExternalACPAckResponse,
)
async def close_tenant_external_agent_session(
    tenant_id: str,
    agent_key: str,
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExternalACPAckResponse:
    await require_tenant_access(db, cast(Any, current_user), tenant_id, require_admin=True)
    try:
        await _refresh_tenant_agent_cache(db, tenant_id)
        await get_external_agent_service().close(
            agent_id=agent_key,
            session_id=session_id,
            owner_user_id=str(current_user.id),
            tenant_id=tenant_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_("External ACP session not found")) from exc
    return ExternalACPAckResponse()


@router.post(
    "/tenants/{tenant_id}/external-agents/{agent_key}/test",
    response_model=TenantExternalACPTestResponse,
)
async def test_tenant_external_agent(
    tenant_id: str,
    agent_key: str,
    payload: TenantExternalACPTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantExternalACPTestResponse:
    await require_tenant_access(db, cast(Any, current_user), tenant_id, require_admin=True)
    started = time.perf_counter()
    session_result: ExternalACPSessionResult | None = None
    prompt_result: ExternalACPPromptResult | None = None
    try:
        _ensure_absolute_cwd(payload.cwd)
        await _refresh_tenant_agent_cache(db, tenant_id)
        session_result = await asyncio.wait_for(
            get_external_agent_service().new_session(
                agent_id=agent_key,
                owner_user_id=str(current_user.id),
                cwd=payload.cwd,
                additional_directories=payload.additional_directories,
                mcp_servers=payload.mcp_servers,
                tenant_id=tenant_id,
                field_meta=_build_field_meta(
                    project_id=payload.project_id,
                    existing=payload.field_meta,
                ),
            ),
            timeout=payload.timeout_seconds,
        )
        prompt_result = await asyncio.wait_for(
            get_external_agent_service().prompt(
                agent_id=agent_key,
                session_id=session_result.session_id,
                owner_user_id=str(current_user.id),
                prompt=[{"type": "text", "text": payload.prompt}],
                message_id=None,
                tenant_id=tenant_id,
            ),
            timeout=payload.timeout_seconds,
        )
        return TenantExternalACPTestResponse(
            success=True,
            sessionId=session_result.session_id,
            remoteSessionId=session_result.remote_session_id,
            assistantText=_extract_text_from_prompt_result(prompt_result),
            updatesCount=len(prompt_result.updates),
            durationMs=int((time.perf_counter() - started) * 1000),
            error=None,
        )
    except Exception as exc:
        return TenantExternalACPTestResponse(
            success=False,
            sessionId=session_result.session_id if session_result else None,
            remoteSessionId=session_result.remote_session_id if session_result else None,
            assistantText=_extract_text_from_prompt_result(prompt_result) if prompt_result else "",
            updatesCount=len(prompt_result.updates) if prompt_result else 0,
            durationMs=int((time.perf_counter() - started) * 1000),
            error=str(exc),
        )
    finally:
        if session_result is not None:
            try:
                await get_external_agent_service().close(
                    agent_id=agent_key,
                    session_id=session_result.session_id,
                    owner_user_id=str(current_user.id),
                    tenant_id=tenant_id,
                )
            except Exception:
                logger.debug("[ACP] Failed to close smoke test session", exc_info=True)


@router.get("/external-agents", response_model=list[ExternalACPAgentSummary])
async def list_external_agents(
    current_user: User = Depends(get_current_user),
) -> list[ExternalACPAgentSummary]:
    del current_user
    return get_external_agent_service().list_agents()


@router.post(
    "/external-agents/{agent_id}/sessions",
    response_model=ExternalACPSessionResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_external_agent_session(
    agent_id: str,
    payload: ExternalACPSessionRequest,
    current_user: User = Depends(get_current_user),
) -> ExternalACPSessionResult:
    try:
        return await get_external_agent_service().new_session(
            agent_id=agent_id,
            owner_user_id=current_user.id,
            cwd=payload.cwd,
            additional_directories=payload.additional_directories,
            mcp_servers=payload.mcp_servers,
            field_meta=payload.field_meta,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_("External ACP agent not found")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/external-agents/{agent_id}/sessions/{session_id}/prompt",
    response_model=ExternalACPPromptResult,
)
async def prompt_external_agent_session(
    agent_id: str,
    session_id: str,
    payload: ExternalACPPromptRequest,
    current_user: User = Depends(get_current_user),
) -> ExternalACPPromptResult:
    try:
        return await get_external_agent_service().prompt(
            agent_id=agent_id,
            session_id=session_id,
            owner_user_id=current_user.id,
            prompt=payload.prompt,
            message_id=payload.message_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_("External ACP session not found")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/external-agents/{agent_id}/sessions/{session_id}/cancel",
    response_model=ExternalACPAckResponse,
)
async def cancel_external_agent_session(
    agent_id: str,
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> ExternalACPAckResponse:
    try:
        await get_external_agent_service().cancel(
            agent_id=agent_id,
            session_id=session_id,
            owner_user_id=current_user.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_("External ACP session not found")) from exc
    return ExternalACPAckResponse()


@router.delete(
    "/external-agents/{agent_id}/sessions/{session_id}",
    response_model=ExternalACPAckResponse,
)
async def close_external_agent_session(
    agent_id: str,
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> ExternalACPAckResponse:
    try:
        await get_external_agent_service().close(
            agent_id=agent_id,
            session_id=session_id,
            owner_user_id=current_user.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_("External ACP session not found")) from exc
    return ExternalACPAckResponse()
