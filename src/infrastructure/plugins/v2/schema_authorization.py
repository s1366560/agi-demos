"""Live SQL membership authorization bound to one exact schema operation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.domain.model.project_schema.commands import ProjectSchemaAction, ProjectSchemaScope
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeGenerationV2

_SERVICE = "service:application.schema-services"
_DB = "service:operation.db-session"
_IDENTITY = "service:operation.identity"
_WRITE_ROLES = frozenset({"owner", "admin", "member"})


@dataclass(frozen=True, kw_only=True)
class SqlProjectSchemaAuthorizationV2:
    """No admission from caller-supplied scope or stale ORM membership objects."""

    operation: OperationContextV2
    session: AsyncSession
    actor_id: str
    scope: ScopeV2
    _generation: RuntimeGenerationV2 = field(init=False, repr=False)
    _descriptor: PluginGenerationDescriptorV2 = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_generation", self.operation.generation)
        object.__setattr__(self, "_descriptor", self.operation.descriptor)
        self.ensure_live()

    def ensure_live(self) -> None:
        operation = self.operation
        if (
            operation.generation is not self._generation
            or operation.descriptor != self._descriptor
            or operation.context.scope != self.scope
        ):
            raise ProjectSchemaError("project_schema_access_denied")
        _ = self._generation.resolve(_SERVICE, self.scope)
        raw_identity = operation.require(_IDENTITY)
        identity = cast(Mapping[str, object], raw_identity)
        if (
            operation.require(_DB) is not self.session
            or not isinstance(raw_identity, Mapping)
            or identity.get("user_id") != self.actor_id
            or identity.get("tenant_id") != self.scope.tenant_id
            or identity.get("project_id") != self.scope.project_id
        ):
            raise ProjectSchemaError("project_schema_access_denied")

    async def discover_scope(self, project_id: str) -> ProjectSchemaScope:
        self.ensure_live()
        if self.scope.kind is not ScopeKindV2.ROOT:
            raise ProjectSchemaError("project_schema_access_denied")
        tenant_id, _ = await self._membership(project_id)
        return ProjectSchemaScope(
            tenant_id=tenant_id, project_id=project_id, actor_id=self.actor_id
        )

    async def authorize(self, scope: ProjectSchemaScope, action: ProjectSchemaAction) -> None:
        self.ensure_live()
        if (
            self.scope.kind is not ScopeKindV2.PROJECT
            or (scope.tenant_id, scope.project_id, scope.actor_id)
            != (self.scope.tenant_id, self.scope.project_id, self.actor_id)
            or action not in ProjectSchemaAction
        ):
            raise ProjectSchemaError("project_schema_access_denied")
        tenant_id, role = await self._membership(scope.project_id)
        if tenant_id != scope.tenant_id or (
            action is not ProjectSchemaAction.READ and role not in _WRITE_ROLES
        ):
            raise ProjectSchemaError("project_schema_access_denied")

    async def _membership(self, project_id: str) -> tuple[str, str]:
        self.ensure_live()
        statement = (
            select(Project.tenant_id, UserProject.role)
            .join(UserProject, UserProject.project_id == Project.id)
            .join(User, User.id == UserProject.user_id)
            .join(
                UserTenant,
                (UserTenant.tenant_id == Project.tenant_id) & (UserTenant.user_id == User.id),
            )
            .where(Project.id == project_id, User.id == self.actor_id, User.is_active.is_(True))
        )
        with self.session.no_autoflush:
            result = await self.session.execute(statement)
        self.ensure_live()
        row = result.one_or_none()
        if row is None:
            raise ProjectSchemaError("project_schema_access_denied")
        return row[0], row[1]
