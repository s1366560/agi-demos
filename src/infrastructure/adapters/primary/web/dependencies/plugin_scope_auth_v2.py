"""Resolve publication write authority from persisted resources and memberships."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scope import validate_scope_v2


async def resolve_plugin_publication_scope_v2(
    db: AsyncSession, *, current_user: User, requested_scope: ScopeV2
) -> ScopeV2:
    """Authorize writes; the caller must authenticate current_user before calling.

    Project management follows projects.update_project (UserProject owner/admin).
    Publication writes additionally require current tenant membership. Session writes
    require project management and conversation ownership; this is a publication-specific
    contract, not the existing conversation read/config permission. Do not use this
    resolver for ordinary execution or reads. The session_id is
    Conversation.id as passed by agent_runtime_provider to pin_agent_turn_operation_v2.
    Administrator privilege never substitutes for persisted resource ancestry.
    """
    scope = validate_scope_v2(requested_scope)
    if scope.kind is ScopeKindV2.ROOT:
        if not current_user.is_superuser:
            raise RuntimeV2Error("scope_write_forbidden", "scope publication write is forbidden")
        return scope

    tenant = await db.scalar(
        refresh_select_statement(select(Tenant).where(Tenant.id == scope.tenant_id))
    )
    if tenant is None:
        raise RuntimeV2Error("scope_resource_unavailable", "scope resource is unavailable")
    if scope.kind is ScopeKindV2.TENANT:
        membership = await db.scalar(
            refresh_select_statement(
                select(UserTenant).where(
                    UserTenant.user_id == current_user.id,
                    UserTenant.tenant_id == tenant.id,
                    UserTenant.role.in_(("admin", "owner")),
                )
            )
        )
        if not current_user.is_superuser and membership is None:
            raise RuntimeV2Error("scope_write_forbidden", "scope publication write is forbidden")
        return validate_scope_v2(ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant.id))

    project = await db.scalar(
        refresh_select_statement(select(Project).where(Project.id == scope.project_id))
    )
    if project is None or project.tenant_id != tenant.id:
        raise RuntimeV2Error("scope_resource_unavailable", "scope resource is unavailable")
    if scope.kind is ScopeKindV2.PROJECT:
        await _require_project_publication_manager(db, current_user.id, tenant.id, project.id)
        return validate_scope_v2(
            ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id=tenant.id, project_id=project.id)
        )

    conversation = await db.scalar(
        refresh_select_statement(select(Conversation).where(Conversation.id == scope.session_id))
    )
    if (
        conversation is None
        or conversation.project_id != project.id
        or conversation.tenant_id != tenant.id
    ):
        raise RuntimeV2Error("scope_resource_unavailable", "scope resource is unavailable")
    await _require_project_publication_manager(db, current_user.id, tenant.id, project.id)
    if conversation.user_id != current_user.id:
        raise RuntimeV2Error("scope_write_forbidden", "scope publication write is forbidden")
    return validate_scope_v2(
        ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id=tenant.id,
            project_id=project.id,
            session_id=conversation.id,
        )
    )


async def _require_project_publication_manager(
    db: AsyncSession, user_id: str, tenant_id: str, project_id: str
) -> None:
    tenant_member = await db.scalar(
        refresh_select_statement(
            select(UserTenant.id).where(
                UserTenant.user_id == user_id,
                UserTenant.tenant_id == tenant_id,
            )
        )
    )
    project_manager = await db.scalar(
        refresh_select_statement(
            select(UserProject.id).where(
                UserProject.user_id == user_id,
                UserProject.project_id == project_id,
                UserProject.role.in_(("owner", "admin")),
            )
        )
    )
    if tenant_member is None or project_manager is None:
        raise RuntimeV2Error("scope_write_forbidden", "scope publication write is forbidden")
