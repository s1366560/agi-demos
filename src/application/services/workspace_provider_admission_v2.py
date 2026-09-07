"""Authorize Provider scope against local membership and the Workspace Core authority."""

from collections.abc import Callable

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.services.workspace_access_verifier_port import WorkspaceAccessRequest
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import (
    AGENT_WORKSPACE_REQUIRED_SERVICES_V2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeReservationV2
from src.infrastructure.workspace_core.agent_runtime_provider import ProviderWorkspaceScope
from src.infrastructure.workspace_core.client import WorkspaceCoreClient


class WorkspaceProviderAdmissionV2:
    def __init__(self, client: WorkspaceCoreClient, runtime_provider: Callable[[], object]) -> None:
        super().__init__()
        self._client = client
        self._runtime_provider = runtime_provider

    async def authorize(self, db: AsyncSession, scope: ProviderWorkspaceScope) -> None:
        statement = select(Project.id).where(
            Project.id == scope.project_id,
            Project.tenant_id == scope.tenant_id,
            exists(
                select(UserProject.id).where(
                    UserProject.user_id == scope.user_id,
                    UserProject.project_id == scope.project_id,
                )
            ),
            exists(
                select(UserTenant.id).where(
                    UserTenant.user_id == scope.user_id,
                    UserTenant.tenant_id == scope.tenant_id,
                )
            ),
        )
        if (await db.execute(refresh_select_statement(statement))).one_or_none() is None:
            raise _access_denied()
        allowed = await self._client.has_workspace_access(
            WorkspaceAccessRequest(
                tenant_id=scope.tenant_id, user_id=scope.user_id, workspace_id=scope.workspace_id
            )
        )
        if not allowed:
            raise _access_denied()
        profile = await self._client.read_workspace_profile(
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            workspace_id=scope.workspace_id,
            user_id=scope.user_id,
            is_superuser=False,
        )
        if (profile.id, profile.tenant_id, profile.project_id) != (
            scope.workspace_id,
            scope.tenant_id,
            scope.project_id,
        ):
            raise _access_denied()

    async def acquire(
        self, db: AsyncSession, scope: ProviderWorkspaceScope
    ) -> ScopedRuntimeReservationV2:
        # Deferred to avoid the ROOT resource / scoped application startup dependency cycle.
        from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
            ScopedProfileRuntimeV2,
        )

        await self.authorize(db, scope)
        runtime = self._runtime_provider()
        if not isinstance(runtime, ScopedProfileRuntimeV2):
            raise RuntimeV2Error(
                "scoped_runtime_missing", _("Scoped Provider runtime is unavailable")
            )
        session_scope = ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            session_id=scope.conversation_id,
        )
        result = await runtime.prepare_current(
            session_scope,
            actor_id=scope.user_id,
            required_services=AGENT_WORKSPACE_REQUIRED_SERVICES_V2,
        )
        if not result.publication.accepted:
            raise RuntimeV2Error(
                "scoped_publication_rejected", _("Scoped Provider configuration was rejected")
            )
        await self.authorize(db, scope)
        return await runtime.acquire(session_scope)


def _access_denied() -> RuntimeV2Error:
    return RuntimeV2Error("WORKSPACE_ACCESS_DENIED", _("You do not have access to this workspace"))
