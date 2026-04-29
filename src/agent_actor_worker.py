"""Ray Actor worker entry point for Agent execution.

This worker must connect to a Ray cluster and create the HITL router actor.
It retries with exponential backoff until the cluster is available.
"""

import asyncio
import contextlib
import logging
import traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("src.agent_actor_worker")


async def _reset_ray_init_failed() -> None:
    """Reset Ray availability flags so retries start from a clean client state."""
    import ray

    import src.infrastructure.adapters.secondary.ray as ray_pkg

    ray_pkg._ray_init_failed = False
    with contextlib.suppress(Exception):
        ray.shutdown()


async def _cleanup_stale_actors() -> None:
    """Kill stale detached actors that may block actor creation."""
    try:
        import ray

        from src.configuration.ray_config import get_ray_settings
        from src.infrastructure.agent.actor.actor_manager import ROUTER_ACTOR_NAME

        settings = get_ray_settings()
        try:
            actor = ray.get_actor(ROUTER_ACTOR_NAME, namespace=settings.ray_namespace)
            ray.kill(actor, no_restart=True)
            logger.info("Killed stale router actor '%s'", ROUTER_ACTOR_NAME)
            await asyncio.sleep(2)  # Wait for actor to be fully removed
        except ValueError:
            pass  # Actor doesn't exist, nothing to clean up
    except Exception as exc:
        logger.warning("Failed to clean up stale actors: %s", exc)


async def main() -> None:
    from src.infrastructure.adapters.secondary.ray.client import init_ray_if_needed
    from src.infrastructure.agent.actor.actor_manager import ensure_router_actor

    backoff_seconds = 2
    max_backoff = 30
    sentinel_count = 0

    while True:
        try:
            # Reset the module-level flag so we actually retry the connection
            await _reset_ray_init_failed()

            connected = await init_ray_if_needed()
            if not connected:
                logger.warning(
                    "Ray cluster not reachable yet. Retrying in %ss",
                    backoff_seconds,
                )
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, max_backoff)
                continue

            router = await ensure_router_actor(mark_unavailable_on_failure=False)
            if router is None:
                logger.warning(
                    "Router actor creation returned None. Retrying in %ss",
                    backoff_seconds,
                )
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, max_backoff)
                continue

            logger.info("Agent Actor worker initialized -- router actor is ready")
            break

        except Exception as exc:
            exc_str = str(exc)
            logger.error(
                "Agent Actor worker initialization failed: %s. Retrying in %ss\n%s",
                exc,
                backoff_seconds,
                traceback.format_exc(),
            )

            # InProgressSentinel means actor scheduling failed
            if "InProgressSentinel" in exc_str:
                sentinel_count += 1
                if sentinel_count >= 3:
                    logger.warning(
                        "Persistent InProgressSentinel error (%d times). "
                        "Attempting to clean up stale detached actors.",
                        sentinel_count,
                    )
                    await _cleanup_stale_actors()
                    sentinel_count = 0

            await asyncio.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, max_backoff)

    await asyncio.Event().wait()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
