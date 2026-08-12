"""Shared cancellation for every Agent Runtime execution substrate."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.domain.model.agent.conversation.conversation import Conversation

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class AgentRuntimeCancellationResult:
    ray_cancelled: bool
    local_worker_cancelled: bool
    ray_error: Exception | None = None

    @property
    def cancelled(self) -> bool:
        return self.ray_cancelled or self.local_worker_cancelled


async def cancel_conversation_runtime(
    conversation: Conversation,
) -> AgentRuntimeCancellationResult:
    """Cancel Ray and local workers without returning after the first result."""
    from src.application.services.agent.runtime_bootstrapper import (
        AgentRuntimeBootstrapper,
    )
    from src.infrastructure.adapters.secondary.ray.client import await_ray
    from src.infrastructure.agent.actor.actor_manager import get_actor_if_exists

    ray_cancelled = False
    ray_error: Exception | None = None
    actor = await get_actor_if_exists(
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        agent_mode="default",
    )
    if actor is not None:
        try:
            ray_cancelled = bool(await await_ray(actor.cancel.remote(conversation.id)))
        except Exception as exc:
            ray_error = exc
            logger.error(
                "Failed to cancel Ray actor for conversation %s",
                conversation.id,
                exc_info=True,
            )

    local_worker_cancelled = await AgentRuntimeBootstrapper.cancel_local_chat(conversation.id)
    return AgentRuntimeCancellationResult(
        ray_cancelled=ray_cancelled,
        local_worker_cancelled=local_worker_cancelled,
        ray_error=ray_error,
    )
