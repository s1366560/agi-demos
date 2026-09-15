"""Freeze the authoritative workspace model route for a canonical conversation run."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.agent.model_route import ModelRouteRef
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


def route_from_policy(policy: dict[str, Any], capability_mode: str) -> ModelRouteRef:
    """Use the same structural capability-to-role contract as task-session creation."""
    if capability_mode not in {"work", "code"}:
        raise RuntimeV2Error(
            "workspace_model_route_missing", "Workspace capability mode is missing"
        )
    roles = policy.get("roles")
    route_raw = (
        cast(dict[str, object], roles).get("coding" if capability_mode == "code" else "default")
        if isinstance(roles, dict)
        else None
    )
    route = cast(dict[str, object], route_raw) if isinstance(route_raw, dict) else {}
    provider_id, model_id = route.get("provider_id"), route.get("model_id")
    if (
        not isinstance(provider_id, str)
        or not provider_id.strip()
        or not isinstance(model_id, str)
        or not model_id.strip()
    ):
        raise RuntimeV2Error(
            "workspace_model_route_missing", "Workspace policy has no explicit model route"
        )
    return ModelRouteRef(provider_id=provider_id, model_id=model_id)


async def load_workspace_policy(conversation: Conversation) -> dict[str, Any]:
    from src.infrastructure.adapters.primary.web.routers.workspace_agent_policy import (
        WorkspaceAgentPolicyResponse,
    )
    from src.infrastructure.adapters.primary.web.workspace_core_runtime_resolver import (
        workspace_core_runtime_service_v2_from_current_generation,
    )

    workspace_id = conversation.workspace_id
    if not workspace_id:
        raise RuntimeV2Error("workspace_model_policy_missing", "Workspace scope is missing")
    client = workspace_core_runtime_service_v2_from_current_generation().client
    response = await client.proxy_request(
        method="GET",
        path=f"/api/v1/tenants/{conversation.tenant_id}/projects/{conversation.project_id}/workspaces/{conversation.workspace_id}/agent-policy",
        query=b"",
        body=b"",
        headers=[
            ("Accept", "application/json"),
            ("X-MemStack-Tenant-ID", conversation.tenant_id),
            ("X-MemStack-Project-ID", conversation.project_id),
            ("X-MemStack-Workspace-ID", workspace_id),
            ("X-MemStack-User-ID", conversation.user_id),
        ],
    )
    payload = b"".join([chunk async for chunk in response.aiter_raw()])
    if response.status_code != 200:
        raise RuntimeV2Error(
            "workspace_model_policy_unavailable", "Workspace model policy is unavailable"
        )
    policy = WorkspaceAgentPolicyResponse.model_validate_json(payload)
    if (policy.tenant_id, policy.project_id, policy.workspace_id) != (
        conversation.tenant_id,
        conversation.project_id,
        conversation.workspace_id,
    ):
        raise RuntimeV2Error(
            "workspace_model_policy_scope_mismatch", "Workspace model policy scope mismatch"
        )
    return policy.model_dump()


async def freeze_run_model_route(
    db: AsyncSession,
    *,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    run_id: str,
) -> ModelRouteRef | None:
    """Bind ordinary workspace turns to a durable route, preserving approved snapshots."""
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.project_id == project_id,
        )
    )
    if conversation is None:
        raise RuntimeV2Error(
            "workspace_model_route_scope_denied", "Run conversation scope mismatch"
        )
    if not conversation.workspace_id or conversation.linked_workspace_task_id:
        return None
    run = await db.scalar(
        select(AgentRunAuthorityModel)
        .where(
            AgentRunAuthorityModel.id == run_id,
            AgentRunAuthorityModel.tenant_id == tenant_id,
            AgentRunAuthorityModel.project_id == project_id,
            AgentRunAuthorityModel.conversation_id == conversation_id,
        )
        .with_for_update()
    )
    if run is None or run.status not in {"queued", "running"}:
        raise RuntimeV2Error(
            "workspace_model_run_unavailable", "Canonical run is not active in this scope"
        )
    snapshot = dict(run.authorization_snapshot or {})
    frozen = snapshot.get("model_route")
    if isinstance(frozen, dict):
        return route_from_policy({"roles": {"default": frozen}}, "work")
    if run.run_kind == "plan":
        policy = snapshot.get("policy")
        if not isinstance(policy, dict):
            raise RuntimeV2Error(
                "workspace_model_policy_missing", "Approved policy snapshot is missing"
            )
    else:
        policy = await load_workspace_policy(conversation)
    policy = cast(dict[str, Any], policy)
    config = conversation.agent_config or {}
    route = route_from_policy(policy, config.get("capability_mode", ""))
    snapshot["model_route"] = {"provider_id": route.provider_id, "model_id": route.model_id}
    snapshot["model_policy_revision"] = policy.get("revision")
    run.authorization_snapshot = snapshot
    await db.commit()
    return route


async def resolve_run_model_route(
    *,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    run_id: str,
) -> ModelRouteRef | None:
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

    async with async_session_factory() as session:
        return await freeze_run_model_route(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            run_id=run_id,
        )
