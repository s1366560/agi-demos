"""Authenticated Avernet Provider 2.0 webhook."""

from __future__ import annotations

import json
import logging
import secrets
from typing import Annotated, Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
    SqlAgentRegistryRepository,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.persistence.llm_providers_models import LLMProvider, TenantProviderMapping
from src.infrastructure.workspace_core.autonomy_judge import (
    WorkspaceAutonomyJudgePort,
    WorkspaceAutonomyJudgeRequest,
    WorkspaceAutonomyJudgeUnavailable,
)
from src.infrastructure.workspace_core.context_judge import (
    WorkspaceContextJudgePort,
    WorkspaceContextJudgeRequest,
    WorkspaceContextJudgeUnavailable,
)
from src.infrastructure.workspace_core.plan_judge import (
    WorkspacePlanJudgePort,
    WorkspacePlanJudgeRequest,
    WorkspacePlanJudgeUnavailable,
)
from src.infrastructure.workspace_core.provider import (
    AvernetProviderAdapter,
    ProviderBotRef,
    ProviderWebhookRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace-core-internal"])

_WORKSPACE_PROVIDER_ID = "memstack-workspace-agent-runtime"
_PLAN_PROVIDER_ID = "memstack-agent-runtime"
_DEFAULT_PLAN_AGENT_ID = "builtin:all-access"
_PLAN_PROVIDER_TIMEOUT_MS = 3_600_000


class WorkspaceAgentRegistryLookup(BaseModel):
    """Trusted scope supplied by Workspace Core for one Agent lookup."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(..., min_length=1, max_length=128)
    project_id: str = Field(..., min_length=1, max_length=128)
    agent_id: str = Field(..., min_length=1, max_length=128)


class WorkspaceProviderRegistryLookup(BaseModel):
    """Trusted tenant-scoped Provider/model lookup from Workspace Core."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(..., min_length=1, max_length=128)
    provider_id: str = Field(..., min_length=1, max_length=128)
    model_id: str = Field(..., min_length=1, max_length=512)


class WorkspaceProviderRegistryDefaultLookup(BaseModel):
    """Trusted tenant default request from Workspace Core."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(..., min_length=1, max_length=128)


WorkspacePlanDispatchAction = Literal[
    "recover_stale_attempts",
    "trigger_next_iteration",
    "run_pipeline",
    "regenerate_delivery_contract",
]


class WorkspacePlanDispatchRequest(BaseModel):
    """One durable Plan outbox action accepted by the existing Agent Runtime."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(..., min_length=1, max_length=128)
    project_id: str = Field(..., min_length=1, max_length=128)
    workspace_id: str = Field(..., min_length=1, max_length=128)
    plan_id: str = Field(..., min_length=1, max_length=128)
    plan_node_id: str | None = Field(default=None, min_length=1, max_length=512)
    task_id: str | None = Field(default=None, min_length=1, max_length=512)
    attempt_id: str | None = Field(default=None, min_length=1, max_length=512)
    agent_id: str | None = Field(default=None, min_length=1, max_length=512)
    action: WorkspacePlanDispatchAction
    outbox_id: str = Field(..., min_length=1, max_length=512)
    correlation_id: str = Field(..., min_length=1, max_length=512)
    conversation_id: str = Field(..., min_length=1, max_length=512)
    payload: dict[str, Any]


@router.post(
    "/internal/v1/workspace-core/context-judge",
    include_in_schema=False,
    response_model=None,
)
async def judge_workspace_context(
    judgment_request: WorkspaceContextJudgeRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | JSONResponse:
    """Resolve an ambiguous Context selection through a structured Agent tool call."""
    if not _registry_authorized(request, authorization):
        return JSONResponse(status_code=401, content={"detail": _("Unauthorized")})
    judge = getattr(request.app.state, "workspace_core_context_judge", None)
    if not isinstance(judge, WorkspaceContextJudgePort):
        return _context_judge_unavailable()
    try:
        verdict = await judge.select(judgment_request)
    except WorkspaceContextJudgeUnavailable:
        return _context_judge_unavailable()
    return verdict.model_dump(mode="json")


@router.post(
    "/internal/v1/workspace-core/plan-judge",
    include_in_schema=False,
    response_model=None,
)
async def judge_workspace_plan(
    judgment_request: WorkspacePlanJudgeRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | JSONResponse:
    """Resolve one subjective Plan transition through a structured Agent tool call."""
    if not _registry_authorized(request, authorization):
        return JSONResponse(status_code=401, content={"detail": _("Unauthorized")})
    judge = getattr(request.app.state, "workspace_core_plan_judge", None)
    if not isinstance(judge, WorkspacePlanJudgePort):
        return _plan_judge_unavailable()
    try:
        verdict = await judge.judge(judgment_request)
    except WorkspacePlanJudgeUnavailable:
        return _plan_judge_unavailable()
    return verdict.model_dump(mode="json")


@router.post(
    "/internal/v1/workspace-core/autonomy-judge",
    include_in_schema=False,
    response_model=None,
)
async def judge_workspace_autonomy(
    judgment_request: WorkspaceAutonomyJudgeRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | JSONResponse:
    """Resolve one subjective Autonomy tick through a structured Agent tool call."""
    if not _registry_authorized(request, authorization):
        return JSONResponse(status_code=401, content={"detail": _("Unauthorized")})
    judge = getattr(request.app.state, "workspace_core_autonomy_judge", None)
    if not isinstance(judge, WorkspaceAutonomyJudgePort):
        return _autonomy_judge_unavailable()
    try:
        verdict = await judge.judge(judgment_request)
    except WorkspaceAutonomyJudgeUnavailable:
        return _autonomy_judge_unavailable()
    return verdict.model_dump(mode="json")


@router.post(
    "/internal/v1/workspace-core/provider",
    include_in_schema=False,
    response_model=None,
)
async def workspace_core_provider_webhook(
    provider_request: ProviderWebhookRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | JSONResponse:
    """Accept one structurally validated BCS-to-Provider frame."""
    settings = getattr(request.app.state, "workspace_core_settings", None)
    expected_secret = getattr(settings, "provider_webhook_token", None)
    if expected_secret is None or not _authorized(
        authorization,
        expected_secret.get_secret_value(),
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": _("Unauthorized")},
        )

    adapter = getattr(request.app.state, "workspace_core_provider_adapter", None)
    if not isinstance(adapter, AvernetProviderAdapter):
        return JSONResponse(
            status_code=503,
            content={"detail": _("Workspace Core Provider is unavailable")},
        )
    return await _dispatch_provider_request(adapter, provider_request)


@router.post(
    "/internal/v1/workspace-core/plan-dispatch",
    include_in_schema=False,
    response_model=None,
)
async def dispatch_workspace_plan(
    dispatch_request: WorkspacePlanDispatchRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | JSONResponse:
    """Translate one fenced Plan outbox action into an idempotent Agent Runtime send."""
    settings = getattr(request.app.state, "workspace_core_settings", None)
    expected_secret = getattr(settings, "provider_webhook_token", None)
    if expected_secret is None or not _authorized(
        authorization,
        expected_secret.get_secret_value(),
    ):
        return JSONResponse(status_code=401, content={"detail": _("Unauthorized")})
    adapter = getattr(request.app.state, "workspace_core_provider_adapter", None)
    if not isinstance(adapter, AvernetProviderAdapter):
        return _plan_dispatch_unavailable()
    actor_id = dispatch_request.payload.get("actor_id")
    if not isinstance(actor_id, str) or not actor_id.strip():
        return JSONResponse(
            status_code=400,
            content={"detail": _("Workspace Plan dispatch actor is required")},
        )
    provider_request = _plan_dispatch_provider_request(dispatch_request, actor_id.strip())
    result = await _dispatch_provider_request(adapter, provider_request)
    if isinstance(result, JSONResponse):
        return result
    if result.get("ok") is not True:
        return _plan_dispatch_unavailable()
    agent_id = dispatch_request.agent_id or _DEFAULT_PLAN_AGENT_ID
    return {
        "accepted": True,
        "provider_id": _PLAN_PROVIDER_ID,
        "provider_bot_ref": agent_id,
        "provider_run_id": str(
            uuid5(NAMESPACE_URL, f"memstack-workspace-plan:{dispatch_request.outbox_id}")
        ),
    }


@router.post(
    "/internal/v1/workspace-core/agent-registry/resolve",
    include_in_schema=False,
    response_model=None,
)
async def resolve_workspace_agent_definition(
    lookup: WorkspaceAgentRegistryLookup,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    """Resolve one tenant/project-scoped Agent through the external authority."""
    settings = getattr(request.app.state, "workspace_core_settings", None)
    configured_token = getattr(settings, "agent_registry_token", None)
    if configured_token is None or not _authorized(
        authorization,
        configured_token.get_secret_value(),
    ):
        return JSONResponse(status_code=401, content={"detail": _("Unauthorized")})

    try:
        agent = await SqlAgentRegistryRepository(db).get_by_id(
            lookup.agent_id,
            tenant_id=lookup.tenant_id,
            project_id=lookup.project_id,
        )
    except Exception:
        logger.exception(
            "Workspace Core Agent Registry lookup failed",
            extra={"tenant_id": lookup.tenant_id, "project_id": lookup.project_id},
        )
        return JSONResponse(
            status_code=503,
            content={"detail": _("Workspace Core Agent Registry is unavailable")},
        )
    if agent is None:
        return {
            "available": False,
            "agent_id": None,
            "name": None,
            "display_name": None,
            "enabled": None,
        }
    return {
        "available": True,
        "agent_id": agent.id,
        "name": agent.name,
        "display_name": agent.display_name,
        "enabled": agent.enabled,
    }


@router.post(
    "/internal/v1/workspace-core/provider-registry/resolve",
    include_in_schema=False,
    response_model=None,
)
async def resolve_workspace_provider_route(
    lookup: WorkspaceProviderRegistryLookup,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    """Validate one Provider/model pair through the tenant registry authority."""
    if not _registry_authorized(request, authorization):
        return JSONResponse(status_code=401, content={"detail": _("Unauthorized")})
    try:
        provider_id = UUID(lookup.provider_id)
    except ValueError:
        return _unavailable_provider_route()
    try:
        result = await db.execute(
            refresh_select_statement(
                select(LLMProvider)
                .join(TenantProviderMapping, TenantProviderMapping.provider_id == LLMProvider.id)
                .where(
                    TenantProviderMapping.tenant_id == lookup.tenant_id,
                    TenantProviderMapping.operation_type == "llm",
                    LLMProvider.id == provider_id,
                    LLMProvider.operation_type == "llm",
                    LLMProvider.is_active.is_(True),
                    LLMProvider.is_enabled.is_(True),
                )
            )
        )
        provider = result.scalar_one_or_none()
    except Exception:
        logger.exception(
            "Workspace Core Provider Registry lookup failed",
            extra={"tenant_id": lookup.tenant_id},
        )
        return JSONResponse(
            status_code=503,
            content={"detail": _("Workspace Core Provider Registry is unavailable")},
        )
    if provider is None or lookup.model_id not in _provider_models(provider):
        return _unavailable_provider_route()
    return {
        "available": True,
        "provider_id": str(provider.id),
        "model_id": lookup.model_id,
    }


@router.post(
    "/internal/v1/workspace-core/provider-registry/default",
    include_in_schema=False,
    response_model=None,
)
async def resolve_workspace_provider_default(
    lookup: WorkspaceProviderRegistryDefaultLookup,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    """Return the explicit tenant default chosen by Provider Registry configuration."""
    if not _registry_authorized(request, authorization):
        return JSONResponse(status_code=401, content={"detail": _("Unauthorized")})
    try:
        result = await db.execute(
            refresh_select_statement(
                select(LLMProvider)
                .join(TenantProviderMapping, TenantProviderMapping.provider_id == LLMProvider.id)
                .where(
                    TenantProviderMapping.tenant_id == lookup.tenant_id,
                    TenantProviderMapping.operation_type == "llm",
                    LLMProvider.operation_type == "llm",
                    LLMProvider.is_active.is_(True),
                    LLMProvider.is_enabled.is_(True),
                )
                .order_by(TenantProviderMapping.priority, LLMProvider.created_at, LLMProvider.id)
                .limit(1)
            )
        )
        provider = result.scalar_one_or_none()
    except Exception:
        logger.exception(
            "Workspace Core Provider Registry default lookup failed",
            extra={"tenant_id": lookup.tenant_id},
        )
        return JSONResponse(
            status_code=503,
            content={"detail": _("Workspace Core Provider Registry is unavailable")},
        )
    if provider is None or not provider.llm_model:
        return _unavailable_provider_route()
    return {
        "available": True,
        "provider_id": str(provider.id),
        "model_id": provider.llm_model,
    }


async def _dispatch_provider_request(
    adapter: AvernetProviderAdapter,
    provider_request: ProviderWebhookRequest,
) -> dict[str, Any] | JSONResponse:
    try:
        return await adapter.handle(provider_request)
    except PermissionError:
        return JSONResponse(
            status_code=403,
            content={"detail": _("Access denied")},
        )
    except LookupError:
        return JSONResponse(
            status_code=404,
            content={"detail": _("Conversation not found")},
        )
    except ValueError as exc:
        logger.info(
            "Rejected invalid Avernet Provider request",
            extra={"run_id": provider_request.id, "method": provider_request.method},
        )
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )
    except Exception:
        logger.exception(
            "Avernet Provider webhook failed",
            extra={"run_id": provider_request.id, "method": provider_request.method},
        )
        return JSONResponse(
            status_code=503,
            content={"detail": _("Workspace Core Provider is unavailable")},
        )


def _plan_dispatch_provider_request(
    request: WorkspacePlanDispatchRequest,
    actor_id: str,
) -> ProviderWebhookRequest:
    agent_id = request.agent_id or _DEFAULT_PLAN_AGENT_ID
    message = "\n".join(
        (
            "Execute the structured Workspace Plan runtime action.",
            "",
            f"Action: {request.action}",
            f"Plan: {request.plan_id}",
            f"Node: {request.plan_node_id or 'none'}",
            f"Task: {request.task_id or 'none'}",
            f"Attempt: {request.attempt_id or 'none'}",
            f"Correlation: {request.correlation_id}",
            f"Payload: {json.dumps(request.payload, sort_keys=True, separators=(',', ':'))}",
        )
    )
    return ProviderWebhookRequest(
        type="req",
        id=request.outbox_id,
        method="chat.send",
        session_id=request.conversation_id,
        bcn_group_id=f"workspace:{request.workspace_id}",
        to_bot=ProviderBotRef(
            provider_id=_WORKSPACE_PROVIDER_ID,
            provider_bot_ref=agent_id,
        ),
        message={"content": [{"type": "text", "text": message}]},
        timeout_ms=_PLAN_PROVIDER_TIMEOUT_MS,
        extensions={
            "tenant_id": request.tenant_id,
            "project_id": request.project_id,
            "workspace_id": request.workspace_id,
            "user_id": actor_id,
            "conversation_id": request.conversation_id,
            "task_id": request.task_id,
            "plan_id": request.plan_id,
            "plan_node_id": request.plan_node_id,
            "attempt_id": request.attempt_id,
            "correlation_id": request.correlation_id,
            "workspace_plan_outbox_id": request.outbox_id,
        },
    )


def _authorized(authorization: str | None, expected_token: str) -> bool:
    if authorization is None:
        return False
    scheme, separator, supplied_token = authorization.partition(" ")
    return (
        separator == " "
        and scheme.lower() == "bearer"
        and secrets.compare_digest(supplied_token, expected_token)
    )


def _registry_authorized(request: Request, authorization: str | None) -> bool:
    settings = getattr(request.app.state, "workspace_core_settings", None)
    configured_token = getattr(settings, "agent_registry_token", None)
    return configured_token is not None and _authorized(
        authorization,
        configured_token.get_secret_value(),
    )


def _provider_models(provider: LLMProvider) -> set[str]:
    models: set[str] = {provider.llm_model} if provider.llm_model else set()
    if provider.allowed_models:
        try:
            values: object = json.loads(provider.allowed_models)
        except json.JSONDecodeError:
            values = []
        if isinstance(values, list):
            models.update(str(value) for value in cast(list[object], values) if value)
    models.update(provider.secondary_models or [])
    return models


def _unavailable_provider_route() -> dict[str, object]:
    return {"available": False, "provider_id": None, "model_id": None}


def _context_judge_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": _("Workspace Context judge is unavailable")},
    )


def _plan_judge_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": _("Workspace Plan judge is unavailable")},
    )


def _autonomy_judge_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": _("Workspace Autonomy judge is unavailable")},
    )


def _plan_dispatch_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": _("Workspace Plan dispatch is unavailable")},
    )


__all__ = ["router"]
