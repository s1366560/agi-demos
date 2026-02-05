"""Actor manager utilities for Ray-based agent runtime."""

from __future__ import annotations

from typing import Any

import ray

from src.configuration.ray_config import get_ray_settings
from src.infrastructure.adapters.secondary.ray.client import await_ray, init_ray_if_needed
from src.infrastructure.agent.actor.hitl_router_actor import HITLStreamRouterActor
from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor
from src.infrastructure.agent.actor.types import ProjectAgentActorConfig

ROUTER_ACTOR_NAME = "hitl-router"


async def ensure_router_actor() -> Any:
    """Ensure the HITL stream router actor is running."""
    await init_ray_if_needed()
    settings = get_ray_settings()

    try:
        return ray.get_actor(ROUTER_ACTOR_NAME, namespace=settings.ray_namespace)
    except ValueError:
        actor = HITLStreamRouterActor.options(
            name=ROUTER_ACTOR_NAME,
            namespace=settings.ray_namespace,
            lifetime="detached",
        ).remote()
        await await_ray(actor.start.remote())
        return actor


async def get_or_create_actor(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
    config: ProjectAgentActorConfig,
) -> Any:
    """Get or create a project agent actor."""
    await init_ray_if_needed()
    settings = get_ray_settings()
    actor_id = ProjectAgentActor.actor_id(tenant_id, project_id, agent_mode)

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


async def get_actor_if_exists(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
) -> Any | None:
    """Get an existing project agent actor if available."""
    await init_ray_if_needed()
    settings = get_ray_settings()
    actor_id = ProjectAgentActor.actor_id(tenant_id, project_id, agent_mode)

    try:
        return ray.get_actor(actor_id, namespace=settings.ray_namespace)
    except ValueError:
        return None


async def register_project(tenant_id: str, project_id: str) -> None:
    """Register a project stream with the HITL router actor."""
    router = await ensure_router_actor()
    await await_ray(router.add_project.remote(tenant_id, project_id))
