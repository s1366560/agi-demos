"""Subprocess entry point for local agent chat execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.infrastructure.agent.actor.execution import execute_project_chat
from src.infrastructure.agent.actor.types import ProjectAgentActorConfig, ProjectChatRequest
from src.infrastructure.agent.core.project_react_agent import (
    ProjectAgentConfig,
    ProjectReActAgent,
)

logger = logging.getLogger(__name__)


async def _run(request_file: Path) -> int:
    payload = _load_payload(request_file)
    config = ProjectAgentActorConfig(**payload["config"])
    request = ProjectChatRequest(**payload["request"])

    try:
        request_file.unlink(missing_ok=True)
    except Exception:
        logger.debug("Failed to remove local chat request file %s", request_file, exc_info=True)

    try:
        bootstrapper = AgentRuntimeBootstrapper()
        await bootstrapper._ensure_local_runtime_bootstrapped()
        agent = ProjectReActAgent(_agent_config_from_actor_config(config))
        await agent.initialize()
        _attach_plan_repository(agent)
        result = await execute_project_chat(agent, request, abort_signal=None)
        if result.is_error:
            logger.warning(
                "Local chat subprocess completed with error: conversation=%s error=%s",
                request.conversation_id,
                result.error_message,
            )
            return 1
        return 0
    except Exception as exc:
        logger.exception(
            "Local chat subprocess crashed: conversation=%s error=%s",
            request.conversation_id,
            exc,
        )
        try:
            from src.infrastructure.agent.actor.execution import _publish_error_event

            await _publish_error_event(
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                error_message=f"Agent subprocess crashed: {exc}",
                correlation_id=request.correlation_id,
            )
        except Exception:
            logger.warning("Failed to publish local chat subprocess crash", exc_info=True)
        return 1


def _load_payload(request_file: Path) -> dict[str, Any]:
    with request_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError("Local chat request payload must be an object")
    if not isinstance(payload.get("config"), dict):
        raise ValueError("Local chat request payload missing config")
    if not isinstance(payload.get("request"), dict):
        raise ValueError("Local chat request payload missing request")
    return payload


def _agent_config_from_actor_config(config: ProjectAgentActorConfig) -> ProjectAgentConfig:
    return ProjectAgentConfig(
        tenant_id=config.tenant_id,
        project_id=config.project_id,
        agent_mode=config.agent_mode,
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        max_steps=config.max_steps,
        persistent=False,
        idle_timeout_seconds=config.idle_timeout_seconds,
        max_concurrent_chats=config.max_concurrent_chats,
        mcp_tools_ttl_seconds=config.mcp_tools_ttl_seconds,
        enable_skills=config.enable_skills,
        enable_subagents=config.enable_subagents,
    )


def _attach_plan_repository(agent: ProjectReActAgent) -> None:
    try:
        from src.configuration.di_container import get_container  # type: ignore[attr-defined]

        container = get_container()
        agent._plan_repo = container._agent.plan_repository()
    except Exception:
        logger.debug("Plan repository unavailable for local subprocess", exc_info=True)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("request_file")
    args = parser.parse_args()
    return asyncio.run(_run(Path(args.request_file)))


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
