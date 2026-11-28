"""Tenant dashboard authority. Runs in the host, called by the command guest."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from src.host.operations.agent_package.bridge import HostBridge
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


def _error(exc: HTTPException) -> OptionalBusinessError:
    code = {403: "forbidden", 404: "page_not_found", 409: "conflict", 422: "invalid_input"}
    return OptionalBusinessError(code.get(exc.status_code, "runtime_unavailable"), str(exc.detail))


def _authority(bridge: HostBridge) -> dict[str, Any]:
    if bridge.project_id:
        raise OptionalBusinessError("forbidden", "Tenant installation required")
    return {
        "tenant_id": bridge.tenant_id,
        "current_user": bridge.ctx.user,
        "db": bridge.ctx.db,
    }


async def perform(bridge: HostBridge, op: str, payload: dict[str, Any]) -> dict[str, Any]:  # noqa: C901, PLR0912
    from src.infrastructure.adapters.primary.web.routers import system
    from src.infrastructure.adapters.primary.web.routers.agent import config, trace_router

    authority = _authority(bridge)
    try:
        if op == "read":
            view = payload["view"]
            data: BaseModel | dict[str, Any]
            match view:
                case "runs":
                    data = await trace_router.list_tenant_runs(
                        request=bridge.ctx.request,
                        status=None,
                        limit=20,
                        **authority,
                    )
                case "active":
                    data = await trace_router.get_tenant_active_run_count(
                        request=bridge.ctx.request, **authority
                    )
                case "config":
                    data = await config.get_tenant_agent_config(
                        request=bridge.ctx.request, **authority
                    )
                case "revision":
                    data = await config.get_tenant_agent_config_authority_revision(
                        request=bridge.ctx.request, **authority
                    )
                case "catalog":
                    data = await config.get_hook_catalog(**authority)
                case "permission":
                    return await config.check_config_modify_permission(**authority)
                case "system":
                    return await system.get_system_info(bridge.ctx.user)
                case _:
                    raise OptionalBusinessError("forbidden", "unsupported dashboard view")
            return data.model_dump(mode="json")
        if op == "trace":
            from sqlalchemy import select

            from src.infrastructure.adapters.secondary.persistence.models import Conversation

            belongs = await bridge.ctx.db.scalar(
                select(Conversation.id).where(
                    Conversation.id == payload["conversation_id"],
                    Conversation.tenant_id == bridge.tenant_id,
                )
            )
            if belongs is None:
                raise OptionalBusinessError("page_not_found", "Conversation unavailable")
            trace = await trace_router.get_trace_chain(
                payload["conversation_id"],
                payload["trace_id"],
                bridge.ctx.request,
                None,
                bridge.ctx.user,
                bridge.ctx.db,
            )
            return trace.model_dump(mode="json")
        if op == "configure":
            from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
                UpdateTenantAgentConfigRequest,
            )

            result = await config.update_tenant_agent_config(
                UpdateTenantAgentConfigRequest.model_validate(payload["config"]),
                bridge.ctx.request,
                expected_revision=payload["expected_revision"],
                **authority,
            )
            return {"status": 200, "config": result.model_dump(mode="json")}
    except HTTPException as exc:
        if op == "configure" and exc.status_code == 409:
            return {"status": 409}
        raise _error(exc) from exc
    raise OptionalBusinessError("forbidden", "unsupported dashboard operation")
