"""Actor manager utilities for Ray-based agent runtime."""

from __future__ import annotations

import logging
from typing import Any, Optional

import ray

from src.configuration.ray_config import get_ray_settings
from src.infrastructure.adapters.secondary.ray.client import (
    await_ray,
    init_ray_if_needed,
    is_ray_available,
    mark_ray_unavailable,
)
from src.infrastructure.agent.actor.hitl_router_actor import HITLStreamRouterActor
from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor
from src.infrastructure.agent.actor.types import ProjectAgentActorConfig

logger = logging.getLogger(__name__)

ROUTER_ACTOR_NAME = "hitl-router"


async def ensure_router_actor() -> Optional[Any]:  # noqa: ANN401
    """Ensure the HITL stream router actor is running.

    Returns None if Ray is not available.
    """
    if not await init_ray_if_needed():
        return None

    settings = get_ray_settings()

    try:
        return ray.get_actor(ROUTER_ACTOR_NAME, namespace=settings.ray_namespace)
    except ValueError:
        try:
            actor = HITLStreamRouterActor.options(
                name=ROUTER_ACTOR_NAME,
                namespace=settings.ray_namespace,
                lifetime="detached",
            ).remote()
            await await_ray(actor.start.remote())
            return actor
        except Exception as e:
            logger.warning("[ActorManager] Failed to create router actor: %s", e)
            mark_ray_unavailable()
            return None
    except Exception as e:
        logger.warning("[ActorManager] Ray runtime error in ensure_router_actor: %s", e)
        mark_ray_unavailable()
        return None


async def get_or_create_actor(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
    config: ProjectAgentActorConfig,
) -> Optional[Any]:  # noqa: ANN401
    """Get or create a project agent actor.

    Returns None if Ray is not available.
    """
    if not await init_ray_if_needed():
        return None

    settings = get_ray_settings()
    actor_id = ProjectAgentActor.actor_id(tenant_id, project_id, agent_mode)

    try:
        try:
            actor = ray.get_actor(actor_id, namespace=settings.ray_namespace)
        except ValueError:
            actor = ProjectAgentActor.options(
                name=actor_id,
                namespace=settings.ray_namespace,
                lifetime="detached",
            ).remote()
            await await_ray(actor.initialize.remote(config, False))

        return actor
    except Exception as e:
        logger.warning(
            "[ActorManager] Ray runtime error in get_or_create_actor: %s. "
            "Falling back to local execution.",
            e,
        )
        mark_ray_unavailable()
        return None


async def get_actor_if_exists(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
) -> Optional[Any]:  # noqa: ANN401
    """Get an existing project agent actor if available."""
    if not is_ray_available():
        return None

    settings = get_ray_settings()
    actor_id = ProjectAgentActor.actor_id(tenant_id, project_id, agent_mode)

    try:
        return ray.get_actor(actor_id, namespace=settings.ray_namespace)
    except ValueError:
        return None
    except Exception as e:
        logger.warning("[ActorManager] Ray runtime error in get_actor_if_exists: %s", e)
        mark_ray_unavailable()
        return None


async def register_project(tenant_id: str, project_id: str) -> None:
    """Register a project stream with the HITL router actor.

    Falls back to a local HITL resume consumer when Ray is unavailable.
    """
    try:
        router = await ensure_router_actor()
        if router is None:
            from src.infrastructure.agent.hitl.local_resume_consumer import (
                register_project_local,
            )

            await register_project_local(tenant_id, project_id)
            return
        await await_ray(router.add_project.remote(tenant_id, project_id))
    except Exception as e:
        logger.warning("[ActorManager] Failed to register project: %s", e)
        mark_ray_unavailable()
