"""Authenticate persisted chat scope before preparing and admitting its private runtime."""

from sqlalchemy import exists, select

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    ScopedProfileRuntimeV2,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import (
    AGENT_TURN_REQUIRED_SERVICES_V2,
    AGENT_WORKSPACE_REQUIRED_SERVICES_V2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeReservationV2


async def acquire_scoped_chat_turn_v2(
    context: MessageContext, *, conversation_id: str, project_id: str
) -> ScopedRuntimeReservationV2:
    """Called in the detached task's DB context, never trusting connection session IDs."""
    statement = select(Conversation.id, Conversation.workspace_id).where(
        Conversation.id == conversation_id,
        Conversation.user_id == context.user_id,
        Conversation.tenant_id == context.tenant_id,
        Conversation.project_id == project_id,
        exists(
            select(Project.id).where(
                Project.id == project_id,
                Project.tenant_id == context.tenant_id,
            )
        ),
        exists(
            select(UserProject.id).where(
                UserProject.user_id == context.user_id,
                UserProject.project_id == project_id,
            )
        ),
        exists(
            select(UserTenant.id).where(
                UserTenant.user_id == context.user_id,
                UserTenant.tenant_id == context.tenant_id,
            )
        ),
    )
    row = (await context.db.execute(refresh_select_statement(statement))).one_or_none()
    if row is None:
        raise RuntimeV2Error(
            "CONVERSATION_ACCESS_DENIED",
            _("You do not have permission to access this conversation"),
        )
    runtime = context.scoped_profile_runtime_v2
    if not isinstance(runtime, ScopedProfileRuntimeV2):
        raise RuntimeV2Error("scoped_runtime_missing", _("Scoped chat runtime is unavailable"))
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=context.tenant_id,
        project_id=project_id,
        session_id=conversation_id,
    )
    requirements = (
        AGENT_WORKSPACE_REQUIRED_SERVICES_V2
        if row.workspace_id
        else AGENT_TURN_REQUIRED_SERVICES_V2
    )
    result = await runtime.prepare_current(
        scope, actor_id=context.user_id, required_services=requirements
    )
    if not result.publication.accepted:
        raise RuntimeV2Error(
            "scoped_publication_rejected", _("Scoped chat configuration was rejected")
        )
    # Archive loading may await network IO. Recheck membership before acquiring a lease.
    if (await context.db.execute(refresh_select_statement(statement))).one_or_none() is None:
        raise RuntimeV2Error(
            "CONVERSATION_ACCESS_DENIED",
            _("You do not have permission to access this conversation"),
        )
    return await runtime.acquire(scope)
