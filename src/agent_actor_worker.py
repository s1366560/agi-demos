"""Ray Actor worker entry point for Agent execution."""

import asyncio
import logging

from src.infrastructure.adapters.secondary.ray.client import init_ray_if_needed
from src.infrastructure.agent.actor.actor_manager import ensure_router_actor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("src.agent_actor_worker")


async def main() -> None:
    backoff_seconds = 1
    max_backoff = 30
    while True:
        try:
            await init_ray_if_needed()
            await ensure_router_actor()
            logger.info("Agent Actor worker initialized")
            break
        except Exception as exc:
            logger.error(
                "Agent Actor worker initialization failed: %s. Retrying in %ss",
                exc,
                backoff_seconds,
            )
            await asyncio.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, max_backoff)

    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
