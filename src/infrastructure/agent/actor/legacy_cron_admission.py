"""Validate legacy scheduler authority and acknowledge actual execution completion."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, cast

from src.domain.model.agent.hitl.hitl_types import HITLPendingException
from src.infrastructure.agent.actor.types import ProjectChatRequest

if TYPE_CHECKING:
    from src.infrastructure.agent.actor.types import ProjectChatResult
    from src.infrastructure.agent.hitl.state_store import HITLAgentState

from src.domain.model.cron.legacy_admission import (
    LegacyCronAdmissionIdentity,
    LegacyCronExecutionTicket,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
    SqlLegacyCronAdmissionRepository,
)

logger = logging.getLogger(__name__)

_HITL_WAIT_EVENTS = frozenset(
    {
        "clarification_asked",
        "decision_asked",
        "env_var_requested",
        "permission_asked",
        "a2ui_action_asked",
        "elicitation_asked",
    }
)
_HITL_ANSWER_EVENTS = frozenset(
    {
        "clarification_answered",
        "decision_answered",
        "env_var_provided",
        "permission_replied",
        "a2ui_action_answered",
        "elicitation_answered",
    }
)


async def project_legacy_cron_hitl(
    ticket: LegacyCronExecutionTicket | None, event: Mapping[str, object]
) -> None:
    """Project typed protocol events while a coordinator Future keeps execution alive."""
    if ticket is None:
        return
    kind = event.get("type")
    if not isinstance(kind, str):
        return
    if kind not in _HITL_WAIT_EVENTS and kind not in _HITL_ANSWER_EVENTS:
        return
    data = event.get("data")
    if not isinstance(data, Mapping):
        return
    request_id = cast(Mapping[str, object], data).get("request_id")
    if not isinstance(request_id, str) or not request_id:
        return
    try:
        async with async_session_factory() as session:
            matched = await SqlLegacyCronAdmissionRepository(session).project_hitl(
                ticket, request_id, waiting=kind in _HITL_WAIT_EVENTS
            )
            if matched:
                await session.commit()
    except Exception:
        logger.warning("Legacy cron HITL projection failed; admission remains unresolved")


async def validate_legacy_cron_admission(
    value: Mapping[str, object] | None,
    *,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    message_id: str,
    resume: bool = False,
) -> LegacyCronExecutionTicket | None:
    """No metadata means ordinary chat; supplied metadata must match an active DB row."""
    if value is None:
        return None
    identity = LegacyCronAdmissionIdentity.from_wire(value)
    if not identity.matches_request(
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
    ):
        raise ValueError("legacy cron admission request scope mismatch")
    async with async_session_factory() as session:
        ticket = await SqlLegacyCronAdmissionRepository(session).claim_execution(
            identity, resume=resume
        )
        if ticket is None:
            raise ValueError("legacy cron admission execution unavailable")
        await session.commit()
    return ticket


async def complete_legacy_cron_admission(
    identity: LegacyCronExecutionTicket | None, outcome: str
) -> None:
    """Only real success/failure releases the blocker; uncertain outcomes stay active."""
    if identity is None or outcome not in {"success", "failed"}:
        return
    try:
        async with async_session_factory() as session:
            matched = await SqlLegacyCronAdmissionRepository(session).complete(identity, outcome)
            if not matched:
                logger.warning("Legacy cron terminal identity did not match an active admission")
                return
            await session.commit()
    except Exception:
        # Do not emit payloads, tokens, or database errors; failed persistence remains blocking.
        logger.warning("Legacy cron terminal persistence failed; admission remains unresolved")


async def complete_legacy_cron_stream(
    identity: LegacyCronExecutionTicket | None,
    events: Sequence[Mapping[str, object]],
    is_error: bool,
) -> None:
    """A stream ending without a successful completion event is not drain proof."""
    if any(event.get("type") == "complete" for event in events):
        await complete_legacy_cron_admission(identity, "failed" if is_error else "success")


async def park_legacy_cron_admission(ticket: LegacyCronExecutionTicket | None) -> None:
    """Called only after the old execution exits and its HITL snapshot is durable."""
    if ticket is None:
        return
    async with async_session_factory() as session:
        if not await SqlLegacyCronAdmissionRepository(session).park_for_hitl(ticket):
            raise ValueError("legacy cron admission cannot enter waiting phase")
        await session.commit()


async def maybe_park_legacy_hitl(
    ticket: LegacyCronExecutionTicket | None,
    error: Exception,
    persist: Callable[[HITLPendingException], Awaitable[ProjectChatResult]],
) -> ProjectChatResult | None:
    """The generator has exited; persist its snapshot before permitting one resume."""
    if ticket is None or not isinstance(error, HITLPendingException):
        return None
    result = await persist(error)
    await park_legacy_cron_admission(ticket)
    return result


def request_for_legacy_hitl_resume(state: HITLAgentState) -> ProjectChatRequest:
    """Carry trusted admission and generation identity when a resumed turn pauses again."""
    return ProjectChatRequest(
        conversation_id=state.conversation_id,
        message_id=state.message_id,
        user_message=state.user_message,
        user_id=state.user_id,
        conversation_context=state.messages,
        correlation_id=state.correlation_id,
        legacy_cron_admission=state.legacy_cron_admission,
        automation_run_id=state.automation_run_id,
        canonical_run_id=state.canonical_run_id,
        agent_id=state.agent_id,
        parent_session_id=state.parent_session_id,
        plugin_generation=state.plugin_generation,
        plugin_distribution=state.plugin_distribution,
    )
