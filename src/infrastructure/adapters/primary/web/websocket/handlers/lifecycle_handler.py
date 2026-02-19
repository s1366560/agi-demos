"""
Lifecycle Handlers for WebSocket

Handles agent lifecycle control messages:
- subscribe_lifecycle_state / unsubscribe_lifecycle_state
- start_agent / stop_agent / restart_agent
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext

logger = logging.getLogger(__name__)


class SubscribeLifecycleStateHandler(WebSocketMessageHandler):
    """Handle subscribe_lifecycle_state: Subscribe to agent lifecycle state updates."""

    @property
    def message_type(self) -> str:
        return "subscribe_lifecycle_state"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Subscribe to agent lifecycle state updates and send current state."""
        from src.infrastructure.adapters.secondary.ray.client import await_ray
        from src.infrastructure.agent.actor.actor_manager import get_actor_if_exists

        project_id = message.get("project_id")

        if not project_id:
            await context.send_error("Missing project_id")
            return

        try:
            # Subscribe to lifecycle state updates for this project
            await context.connection_manager.subscribe_lifecycle_state(
                context.session_id, context.tenant_id, project_id
            )

            await context.send_ack("subscribe_lifecycle_state", project_id=project_id)

            # Query current agent state and send immediately
            try:
                actor = await get_actor_if_exists(
                    tenant_id=context.tenant_id,
                    project_id=project_id,
                    agent_mode="default",
                )
                if not actor:
                    await context.send_json(
                        {
                            "type": "lifecycle_state_change",
                            "project_id": project_id,
                            "data": {
                                "lifecycle_state": "uninitialized",
                                "is_active": False,
                                "is_initialized": False,
                            },
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    logger.debug(
                        f"[WS] Agent actor not found for {project_id}, sent uninitialized"
                    )
                    return

                status = await await_ray(actor.status.remote())
                lifecycle_state = "ready"
                if not status.is_initialized:
                    lifecycle_state = "initializing"
                elif status.is_executing:
                    lifecycle_state = "executing"

                await context.send_json(
                    {
                        "type": "lifecycle_state_change",
                        "project_id": project_id,
                        "data": {
                            "lifecycle_state": lifecycle_state,
                            "is_active": status.is_active,
                            "is_initialized": status.is_initialized,
                            "tool_count": status.tool_count or 0,
                            "skill_count": status.skill_count or 0,
                            "subagent_count": status.subagent_count or 0,
                            "error_message": None,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                logger.debug(
                    f"[WS] Sent current lifecycle state for {project_id}: "
                    f"lifecycle={lifecycle_state}, is_active={status.is_active}"
                )

            except Exception as state_err:
                logger.warning(f"[WS] Could not query current agent state: {state_err}")

        except Exception as e:
            logger.error(f"[WS] Error subscribing to lifecycle state: {e}", exc_info=True)
            await context.send_error(str(e))


class UnsubscribeLifecycleStateHandler(WebSocketMessageHandler):
    """Handle unsubscribe_lifecycle_state: Stop receiving lifecycle state updates."""

    @property
    def message_type(self) -> str:
        return "unsubscribe_lifecycle_state"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Unsubscribe from lifecycle state updates."""
        project_id = message.get("project_id")

        if not project_id:
            await context.send_error("Missing project_id")
            return

        await context.connection_manager.unsubscribe_lifecycle_state(
            context.session_id, context.tenant_id, project_id
        )
        await context.send_ack("unsubscribe_lifecycle_state", project_id=project_id)


class StartAgentHandler(WebSocketMessageHandler):
    """Handle start_agent: Start the Agent Actor for a project."""

    @property
    def message_type(self) -> str:
        return "start_agent"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Start the Agent Actor for a project."""
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.ray.client import await_ray
        from src.infrastructure.agent.actor.actor_manager import (
            get_actor_if_exists,
            get_or_create_actor,
            register_project,
        )
        from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor
        from src.infrastructure.agent.actor.types import ProjectAgentActorConfig
        from src.infrastructure.llm.provider_factory import get_ai_service_factory
        from src.infrastructure.security.encryption_service import get_encryption_service

        project_id = message.get("project_id")
        if not project_id:
            await context.send_error("Missing project_id")
            return

        try:
            # Ensure sandbox exists before starting agent
            await _ensure_sandbox_exists(context, project_id)

            settings = get_settings()
            agent_mode = "default"

            existing = await get_actor_if_exists(
                tenant_id=context.tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
            )
            if existing:
                await context.send_json(
                    {
                        "type": "agent_lifecycle_ack",
                        "action": "start_agent",
                        "project_id": project_id,
                        "status": "already_running",
                        "workflow_id": ProjectAgentActor.actor_id(
                            context.tenant_id,
                            project_id,
                            agent_mode,
                        ),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                return

            # Resolve provider config from DB
            factory = get_ai_service_factory()
            provider_config = await factory.resolve_provider(context.tenant_id)
            
            # Decrypt API key for the actor
            encryption_service = get_encryption_service()
            api_key = encryption_service.decrypt(provider_config.api_key_encrypted)

            config = ProjectAgentActorConfig(
                tenant_id=context.tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
                model=provider_config.llm_model,
                api_key=api_key,
                base_url=provider_config.base_url,
                temperature=0.7,
                max_tokens=settings.agent_max_tokens,
                max_steps=settings.agent_max_steps,
                persistent=True,
                mcp_tools_ttl_seconds=300,
            )

            await register_project(context.tenant_id, project_id)
            actor = await get_or_create_actor(
                tenant_id=context.tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
                config=config,
            )
            await await_ray(actor.status.remote())

            actor_id = ProjectAgentActor.actor_id(context.tenant_id, project_id, agent_mode)
            logger.info(f"[WS] Started Project Agent Actor: {actor_id}")

            await context.send_json(
                {
                    "type": "agent_lifecycle_ack",
                    "action": "start_agent",
                    "project_id": project_id,
                    "status": "started",
                    "workflow_id": actor_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            # Notify lifecycle state change
            await context.connection_manager.broadcast_lifecycle_state(
                tenant_id=context.tenant_id,
                project_id=project_id,
                state={
                    "lifecycleState": "initializing",
                    "isActive": True,
                    "isInitialized": False,
                },
            )

        except Exception as e:
            logger.error(f"[WS] Error starting agent: {e}", exc_info=True)
            await context.send_error(f"Failed to start agent: {str(e)}")


class StopAgentHandler(WebSocketMessageHandler):
    """Handle stop_agent: Stop the Agent Actor for a project."""

    @property
    def message_type(self) -> str:
        return "stop_agent"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Stop the Agent Actor for a project."""
        import ray

        from src.infrastructure.adapters.secondary.ray.client import await_ray
        from src.infrastructure.agent.actor.actor_manager import get_actor_if_exists
        from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor

        project_id = message.get("project_id")
        if not project_id:
            await context.send_error("Missing project_id")
            return

        try:
            actor_id = ProjectAgentActor.actor_id(context.tenant_id, project_id, "default")
            actor = await get_actor_if_exists(
                tenant_id=context.tenant_id,
                project_id=project_id,
                agent_mode="default",
            )
            if not actor:
                await context.send_json(
                    {
                        "type": "agent_lifecycle_ack",
                        "action": "stop_agent",
                        "project_id": project_id,
                        "status": "not_found",
                        "workflow_id": actor_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                return

            await await_ray(actor.shutdown.remote())
            ray.kill(actor, no_restart=True)

            logger.info(f"[WS] Stopped Project Agent Actor: {actor_id}")

            await context.send_json(
                {
                    "type": "agent_lifecycle_ack",
                    "action": "stop_agent",
                    "project_id": project_id,
                    "status": "stopping",
                    "workflow_id": actor_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            # Notify lifecycle state change
            await context.connection_manager.broadcast_lifecycle_state(
                tenant_id=context.tenant_id,
                project_id=project_id,
                state={
                    "lifecycleState": "shutting_down",
                    "isActive": False,
                    "isInitialized": True,
                },
            )

        except Exception as e:
            logger.error(f"[WS] Error stopping agent: {e}", exc_info=True)
            await context.send_error(f"Failed to stop agent: {str(e)}")


class RestartAgentHandler(WebSocketMessageHandler):
    """Handle restart_agent: Restart the Agent Actor for a project."""

    @property
    def message_type(self) -> str:
        return "restart_agent"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Restart the Agent Actor for a project."""
        import ray

        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.ray.client import await_ray
        from src.infrastructure.agent.actor.actor_manager import (
            get_actor_if_exists,
            get_or_create_actor,
            register_project,
        )
        from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor
        from src.infrastructure.agent.actor.types import ProjectAgentActorConfig

        project_id = message.get("project_id")
        if not project_id:
            await context.send_error("Missing project_id")
            return

        try:
            # Ensure sandbox exists and is healthy before restarting
            await _sync_and_repair_sandbox(context, project_id)

            settings = get_settings()
            agent_mode = "default"
            actor_id = ProjectAgentActor.actor_id(context.tenant_id, project_id, agent_mode)

            # First, notify restarting state
            await context.connection_manager.broadcast_lifecycle_state(
                tenant_id=context.tenant_id,
                project_id=project_id,
                state={
                    "lifecycleState": "shutting_down",
                    "isActive": False,
                    "isInitialized": True,
                },
            )

            existing = await get_actor_if_exists(
                tenant_id=context.tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
            )
            if existing:
                await await_ray(existing.shutdown.remote())
                ray.kill(existing, no_restart=True)
                await asyncio.sleep(1)

            # Resolve provider config from DB
            factory = get_ai_service_factory()
            provider_config = await factory.resolve_provider(context.tenant_id)
            
            # Decrypt API key for the actor
            encryption_service = get_encryption_service()
            api_key = encryption_service.decrypt(provider_config.api_key_encrypted)

            config = ProjectAgentActorConfig(
                tenant_id=context.tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
                model=provider_config.llm_model,
                api_key=api_key,
                base_url=provider_config.base_url,
                temperature=0.7,
                max_tokens=settings.agent_max_tokens,
                max_steps=settings.agent_max_steps,
                persistent=True,
                mcp_tools_ttl_seconds=300,
            )

            await register_project(context.tenant_id, project_id)
            actor = await get_or_create_actor(
                tenant_id=context.tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
                config=config,
            )
            await await_ray(actor.initialize.remote(config, True))

            logger.info(f"[WS] Restarted Project Agent Actor: {actor_id}")

            await context.send_json(
                {
                    "type": "agent_lifecycle_ack",
                    "action": "restart_agent",
                    "project_id": project_id,
                    "status": "restarted",
                    "workflow_id": actor_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            # Notify initializing state
            await context.connection_manager.broadcast_lifecycle_state(
                tenant_id=context.tenant_id,
                project_id=project_id,
                state={
                    "lifecycleState": "initializing",
                    "isActive": True,
                    "isInitialized": False,
                },
            )

        except Exception as e:
            logger.error(f"[WS] Error restarting agent: {e}", exc_info=True)
            await context.send_error(f"Failed to restart agent: {str(e)}")


# =============================================================================
# Helper Functions
# =============================================================================


async def _ensure_sandbox_exists(context: MessageContext, project_id: str) -> Any:
    """Ensure sandbox exists for the project before starting agent."""
    try:
        from src.application.services.project_sandbox_lifecycle_service import (
            ProjectSandboxLifecycleService,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
            SqlProjectSandboxRepository,
        )
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        sandbox_repo = SqlProjectSandboxRepository(context.db)
        sandbox_adapter = MCPSandboxAdapter()
        lifecycle_service = ProjectSandboxLifecycleService(
            repository=sandbox_repo,
            sandbox_adapter=sandbox_adapter,
        )

        # Ensure sandbox exists (will create if not exists, or verify/repair if exists)
        sandbox_info = await lifecycle_service.get_or_create_sandbox(
            project_id=project_id,
            tenant_id=context.tenant_id,
        )
        logger.info(
            f"[WS] Sandbox ensured for project {project_id}: "
            f"sandbox_id={sandbox_info.sandbox_id}, status={sandbox_info.status}"
        )

        # Broadcast sandbox state to frontend via WebSocket
        await context.connection_manager.broadcast_sandbox_state(
            tenant_id=context.tenant_id,
            project_id=project_id,
            state={
                "event_type": "created" if sandbox_info.status == "running" else "status_changed",
                "sandbox_id": sandbox_info.sandbox_id,
                "status": sandbox_info.status,
                "endpoint": sandbox_info.endpoint,
                "websocket_url": sandbox_info.websocket_url,
                "mcp_port": sandbox_info.mcp_port,
                "desktop_port": sandbox_info.desktop_port,
                "terminal_port": sandbox_info.terminal_port,
                "is_healthy": sandbox_info.is_healthy,
            },
        )
        return sandbox_info

    except Exception as e:
        logger.warning(
            f"[WS] Failed to ensure sandbox for project {project_id}: {e}. "
            f"Agent will start but may have limited sandbox tools."
        )
        return None


async def _sync_and_repair_sandbox(context: MessageContext, project_id: str) -> Any:
    """Sync and repair sandbox on agent restart."""
    try:
        from src.application.services.project_sandbox_lifecycle_service import (
            ProjectSandboxLifecycleService,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
            SqlProjectSandboxRepository,
        )
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        sandbox_repo = SqlProjectSandboxRepository(context.db)
        sandbox_adapter = MCPSandboxAdapter()
        lifecycle_service = ProjectSandboxLifecycleService(
            repository=sandbox_repo,
            sandbox_adapter=sandbox_adapter,
        )

        # Sync and repair sandbox on restart (handles container recreation if needed)
        sandbox_info = await lifecycle_service.sync_and_repair_sandbox(project_id)
        if sandbox_info:
            logger.info(
                f"[WS] Sandbox synced for agent restart: project={project_id}, "
                f"sandbox_id={sandbox_info.sandbox_id}, status={sandbox_info.status}"
            )
        else:
            # If no existing sandbox, ensure one is created
            sandbox_info = await lifecycle_service.get_or_create_sandbox(
                project_id=project_id,
                tenant_id=context.tenant_id,
            )
            logger.info(
                f"[WS] Sandbox ensured for agent restart: project={project_id}, "
                f"sandbox_id={sandbox_info.sandbox_id}, status={sandbox_info.status}"
            )

        # Broadcast sandbox state to frontend via WebSocket
        if sandbox_info:
            await context.connection_manager.broadcast_sandbox_state(
                tenant_id=context.tenant_id,
                project_id=project_id,
                state={
                    "event_type": "restarted",
                    "sandbox_id": sandbox_info.sandbox_id,
                    "status": sandbox_info.status,
                    "endpoint": sandbox_info.endpoint,
                    "websocket_url": sandbox_info.websocket_url,
                    "mcp_port": sandbox_info.mcp_port,
                    "desktop_port": sandbox_info.desktop_port,
                    "terminal_port": sandbox_info.terminal_port,
                    "is_healthy": sandbox_info.is_healthy,
                },
            )
        return sandbox_info

    except Exception as e:
        logger.warning(
            f"[WS] Failed to ensure sandbox for project {project_id}: {e}. "
            f"Agent will restart but may have limited sandbox tools."
        )
        return None
