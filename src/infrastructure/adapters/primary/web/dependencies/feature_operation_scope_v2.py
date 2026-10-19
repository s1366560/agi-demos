"""Structural operation arguments and persisted resource ancestry select feature scopes."""

from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence import models
from src.infrastructure.plugins.v2.feature_operations import FeatureOperationOwnerV2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error

_RESOURCE_MODELS_V2: dict[str, Any] = {
    "memory": models.Memory,
    "conversation": models.Conversation,
    "skill": models.Skill,
    "mcp": models.MCPServer,
    "instance": models.InstanceModel,
    "cluster": models.ClusterModel,
    "deploy": models.DeployRecordModel,
    "cron": models.CronJobModel,
    "task": models.TaskLog,
    "definition": models.AgentDefinitionModel,
    "binding": models.AgentBindingModel,
    "template": models.PromptTemplateModel,
    "pattern": models.WorkflowPattern,
}


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _merge_identifier(current: str | None, candidate: object) -> str | None:
    resolved = _identifier(candidate)
    if resolved is not None and current is not None and current != resolved:
        raise RuntimeV2Error(
            "scope_resource_unavailable", "operation scope disagrees with resource"
        )
    return resolved or current


def _scope_arguments(arguments: Mapping[str, Any]) -> tuple[str | None, str | None]:
    tenant_id = _identifier(arguments.get("tenant_id"))
    project_id = _identifier(arguments.get("project_id"))
    # Only validated, declared model fields participate. Unknown query/body fields
    # cannot redirect admission to a different tenant or project.
    for value in arguments.values():
        if isinstance(value, BaseModel):
            if "tenant_id" in type(value).model_fields:
                tenant_id = _merge_identifier(tenant_id, cast(Any, value).tenant_id)
            if "project_id" in type(value).model_fields:
                project_id = _merge_identifier(project_id, cast(Any, value).project_id)
    return tenant_id, project_id


async def _resource_scope(
    db: AsyncSession, kind: str, resource_id: str, arguments: Mapping[str, Any]
) -> tuple[str | None, str | None]:
    if kind in {"graph_entity", "graph_community"}:
        authority = arguments.get("graph_application")
        store = getattr(getattr(authority, "services", None), "graph_store", None)
        if store is None:
            raise RuntimeV2Error("feature_scope_unavailable", "graph scope is unavailable")
        props = await (
            store.get_entity(resource_id)
            if kind == "graph_entity"
            else store.get_community(resource_id)
        )
        if not isinstance(props, Mapping) or not _identifier(props.get("project_id")):
            raise RuntimeV2Error("scope_resource_unavailable", "graph resource is unavailable")
        return _identifier(props.get("tenant_id")), _identifier(props.get("project_id"))

    model = _RESOURCE_MODELS_V2[kind]
    resource = await db.scalar(
        refresh_select_statement(select(model).where(model.id == resource_id))
    )
    if resource is None:
        # Catalog-only builtins and missing IDs retain their endpoint's normal handling.
        return None, None
    if kind == "deploy":
        return await _resource_scope(db, "instance", resource.instance_id, arguments)
    if kind == "task":
        from src.infrastructure.adapters.primary.web.routers.tasks import _task_project_id

        return None, _task_project_id(resource)
    if kind == "skill" and resource.scope == "system":
        return None, None
    return _identifier(getattr(resource, "tenant_id", None)), _identifier(
        getattr(resource, "project_id", None)
    )


async def feature_operation_scopes_v2(
    *,
    db: AsyncSession,
    current_user: models.User,
    owner: FeatureOperationOwnerV2,
    arguments: Mapping[str, Any],
) -> tuple[ScopeV2, ...]:
    tenant_id, project_id = _scope_arguments(arguments)
    requested_tenant_id = tenant_id
    for kind, parameter in owner.resources:
        resource_id = _identifier(arguments.get(parameter))
        if resource_id is None:
            for value in arguments.values():
                if isinstance(value, BaseModel) and parameter in type(value).model_fields:
                    resource_id = _identifier(getattr(value, parameter))
                    break
        if resource_id is not None:
            resource_tenant, resource_project = await _resource_scope(
                db, kind, resource_id, arguments
            )
            tenant_id = _merge_identifier(tenant_id, resource_tenant)
            project_id = _merge_identifier(project_id, resource_project)
    if project_id is not None:
        project = await db.scalar(
            refresh_select_statement(select(models.Project).where(models.Project.id == project_id))
        )
        if project is None:
            raise RuntimeV2Error("scope_resource_unavailable", "project is unavailable")
        tenant_id = _merge_identifier(tenant_id, project.tenant_id)
        return (ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id=tenant_id, project_id=project_id),)

    if owner.project_aggregate:
        statement = select(models.Project)
        if not current_user.is_superuser:
            statement = statement.join(
                models.UserProject, models.UserProject.project_id == models.Project.id
            ).where(models.UserProject.user_id == current_user.id)
        if requested_tenant_id is not None:
            statement = statement.where(models.Project.tenant_id == requested_tenant_id)
        projects = (await db.scalars(refresh_select_statement(statement))).all()
        if projects:
            return tuple(
                ScopeV2(
                    kind=ScopeKindV2.PROJECT, tenant_id=project.tenant_id, project_id=project.id
                )
                for project in projects
            )
    return await _tenant_scopes(db, current_user, owner, arguments, tenant_id)


async def _tenant_scopes(
    db: AsyncSession,
    current_user: models.User,
    owner: FeatureOperationOwnerV2,
    arguments: Mapping[str, Any],
    tenant_id: str | None,
) -> tuple[ScopeV2, ...]:
    if owner.tenant_aggregate == "support_ticket" and tenant_id is None:
        return await _support_ticket_tenant_scopes(db, current_user, arguments)
    if tenant_id is None:
        tenant_id = await get_current_user_tenant(current_user=current_user, db=db)
    return (ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id),)


async def _support_ticket_tenant_scopes(
    db: AsyncSession, current_user: models.User, arguments: Mapping[str, Any]
) -> tuple[ScopeV2, ...]:
    # The unfiltered list returns user-owned tickets across tenants, including
    # tickets retained after membership changes. Admission must cover that same set.
    statement = (
        select(models.SupportTicket.tenant_id)
        .where(models.SupportTicket.user_id == current_user.id)
        .distinct()
    )
    status = _identifier(arguments.get("status"))
    if status is not None:
        statement = statement.where(models.SupportTicket.status == status)
    rows = (await db.scalars(refresh_select_statement(statement))).all()
    tenant_ids = {tenant_id for tenant_id in rows if tenant_id is not None}
    if not rows or None in rows:
        tenant_ids.add(await get_current_user_tenant(current_user=current_user, db=db))
    return tuple(
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id) for tenant_id in sorted(tenant_ids)
    )
