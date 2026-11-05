"""Authorize existing session consumers without publishing a new configuration."""

from sqlalchemy import and_, exists, or_, select

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    ScopedProfileRuntimeV2,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    Conversation,
    HITLRequest,
    Project,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeReservationV2


async def scoped_session_has_only_terminal_runs_v2(
    context: MessageContext,
    *,
    conversation_id: str,
    project_id: str,
) -> bool:
    """Preflight an authorized subscription without restoring a retired runtime."""
    runs = (
        await context.db.execute(
            refresh_select_statement(
                select(AgentRunAuthorityModel.message_id, AgentRunAuthorityModel.status).where(
                    AgentRunAuthorityModel.conversation_id == conversation_id,
                    AgentRunAuthorityModel.tenant_id == context.tenant_id,
                    AgentRunAuthorityModel.project_id == project_id,
                )
            )
        )
    ).all()
    terminal_statuses = {"completed", "ready_review", "failed", "cancelled"}
    if not runs or any(run.status not in terminal_statuses for run in runs):
        return False
    # Legacy producers may not have a canonical run. Their latest persisted
    # activity must still use the pinned recovery path, even after an older
    # canonical run finished in this conversation.
    latest_event = (
        await context.db.execute(
            refresh_select_statement(
                select(AgentExecutionEvent.message_id)
                .where(AgentExecutionEvent.conversation_id == conversation_id)
                .order_by(
                    AgentExecutionEvent.event_time_us.desc(),
                    AgentExecutionEvent.event_counter.desc(),
                )
                .limit(1)
            )
        )
    ).one_or_none()
    return latest_event is None or latest_event.message_id in {run.message_id for run in runs}


async def authorize_existing_scoped_session_v2(
    context: MessageContext,
    *,
    conversation_id: str,
    project_id: str,
    hitl_request_id: str | None = None,
) -> ScopeV2:
    actor_access = Conversation.user_id == context.user_id
    if hitl_request_id is not None:
        actor_access = exists(
            select(HITLRequest.id).where(
                HITLRequest.id == hitl_request_id,
                HITLRequest.conversation_id == conversation_id,
                HITLRequest.tenant_id == context.tenant_id,
                HITLRequest.project_id == project_id,
                HITLRequest.status.in_(("pending", "answered")),
                or_(
                    HITLRequest.user_id == context.user_id,
                    and_(
                        HITLRequest.user_id.is_(None),
                        Conversation.user_id == context.user_id,
                    ),
                ),
            )
        )
    statement = select(Conversation.id).where(
        Conversation.id == conversation_id,
        actor_access,
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
    if (await context.db.execute(refresh_select_statement(statement))).one_or_none() is None:
        raise RuntimeV2Error(
            "CONVERSATION_ACCESS_DENIED",
            _("You do not have permission to access this conversation"),
        )
    return ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=context.tenant_id,
        project_id=project_id,
        session_id=conversation_id,
    )


async def acquire_existing_scoped_session_v2(
    context: MessageContext,
    *,
    conversation_id: str,
    project_id: str,
    hitl_request_id: str | None = None,
) -> ScopedRuntimeReservationV2:
    scope = await authorize_existing_scoped_session_v2(
        context,
        conversation_id=conversation_id,
        project_id=project_id,
        hitl_request_id=hitl_request_id,
    )
    runtime = context.scoped_profile_runtime_v2
    if not isinstance(runtime, ScopedProfileRuntimeV2):
        raise RuntimeV2Error("scoped_runtime_missing", _("Scoped session runtime is unavailable"))
    reservation = await runtime.acquire(scope)
    try:
        _authorized_scope = await authorize_existing_scoped_session_v2(
            context,
            conversation_id=conversation_id,
            project_id=project_id,
            hitl_request_id=hitl_request_id,
        )
    except BaseException:
        await reservation.lease.release()
        raise
    return reservation
