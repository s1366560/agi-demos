"""
Skill Executor - Executes Skills as tool compositions.

Skills encapsulate domain knowledge and tool compositions for specific task patterns.
This executor handles the execution of matched skills within the ReAct agent loop.

The executor uses SkillResourcePort to abstract resource access, allowing
uniform handling of both System (local) and Sandbox (container) environments.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

from src.domain.events.agent_events import (
    AgentActEvent,
    AgentDomainEvent,
    AgentObserveEvent,
    AgentSkillExecutionCompleteEvent,
    AgentThoughtEvent,
)
from src.domain.model.agent.skill import Skill
from src.domain.ports.services.skill_resource_port import (
    ResourceEnvironment,
    SkillResourceContext,
    SkillResourcePort,
)

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort
    from src.infrastructure.agent.skill.skill_resource_injector import SkillResourceInjector

logger = logging.getLogger(__name__)


@dataclass
class SkillExecutionResult:
    """Result of skill execution."""

    skill_id: str
    skill_name: str
    success: bool
    result: Any
    tool_results: List[Dict[str, Any]]
    execution_time_ms: int
    error: Optional[str] = None


class SkillExecutor:
    """
    Executes Skills as coordinated tool compositions.

    Skills define which tools to use and in what order for specific task patterns.
    The executor handles the orchestration of these tool calls.

    Uses SkillResourcePort to abstract resource access between System and Sandbox
    environments. The ReActAgent doesn't need to know whether it's running locally
    or in a container - the executor handles resource synchronization transparently.
    """

    def __init__(
        self,
        tools: Dict[str, Any],  # Tool name -> Tool definition with execute method
        skill_resource_port: Optional[SkillResourcePort] = None,
        # Legacy support - will be removed in future version
        resource_injector: Optional["SkillResourceInjector"] = None,
        sandbox_adapter: Optional["SandboxPort"] = None,
        # Context for resource operations
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        project_path: Optional[Path] = None,
    ):
        """
        Initialize skill executor.

        Args:
            tools: Dictionary of available tools
            skill_resource_port: Unified resource port (preferred)
            resource_injector: Legacy resource injector (deprecated)
            sandbox_adapter: Legacy sandbox adapter (deprecated)
            tenant_id: Tenant ID for resource context
            project_id: Project ID for resource context
            project_path: Project path for local resource lookup
        """
        self.tools = tools
        self._skill_resource_port = skill_resource_port
        # Legacy support
        self._resource_injector = resource_injector
        self._sandbox_adapter = sandbox_adapter
        # Context
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._project_path = project_path

    async def execute(
        self,
        skill: Skill,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        sandbox_id: Optional[str] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Execute a skill by running its tool composition.

        Args:
            skill: Skill to execute
            query: User query that triggered the skill
            context: Optional execution context
            sandbox_id: Optional Sandbox ID for resource injection

        Yields:
            AgentDomainEvent objects for real-time updates
        """
        start_time = time.time()
        context = context or {}
        tool_results = []

        # Emit skill start event
        yield AgentThoughtEvent(
            content=f"Executing skill: {skill.name}",
            thought_level="skill",
        )

        # Synchronize SKILL resources to execution environment
        # Uses unified SkillResourcePort - no need to distinguish System vs Sandbox
        try:
            await self._sync_skill_resources(skill, sandbox_id)
        except Exception as e:
            # Log error but continue execution - skill may still work
            logger.warning(f"Resource sync failed for skill {skill.name}: {e}")

        # Execute each tool in the skill's tool list
        accumulated_context = {"query": query, **context}
        success = True
        error_msg = None

        for tool_name in skill.tools:
            if tool_name not in self.tools:
                logger.warning(f"Tool {tool_name} not found in skill {skill.name}")
                continue

            tool = self.tools[tool_name]

            # Emit tool start
            yield AgentActEvent(
                tool_name=tool_name,
                tool_input=accumulated_context,
                status="running",
            )

            try:
                tool_start = time.time()

                # Execute tool
                if hasattr(tool, "execute"):
                    result = tool.execute(**accumulated_context)
                    if hasattr(result, "__await__"):
                        result = await result
                elif hasattr(tool, "ainvoke"):
                    result = await tool.ainvoke(accumulated_context)
                elif hasattr(tool, "_arun"):
                    result = await tool._arun(**accumulated_context)
                elif hasattr(tool, "_run"):
                    result = tool._run(**accumulated_context)
                else:
                    result = f"Tool {tool_name} has no execute method"

                tool_end = time.time()
                duration_ms = int((tool_end - tool_start) * 1000)

                tool_results.append(
                    {
                        "tool": tool_name,
                        "result": result,
                        "success": True,
                        "duration_ms": duration_ms,
                    }
                )

                # Add result to accumulated context for next tool
                accumulated_context[f"{tool_name}_result"] = result

                # Emit tool result
                yield AgentObserveEvent(
                    tool_name=tool_name,
                    result=result,
                    duration_ms=duration_ms,
                    status="completed",
                )

            except Exception as e:
                logger.error(f"Tool {tool_name} execution error: {e}", exc_info=True)

                tool_results.append(
                    {
                        "tool": tool_name,
                        "error": str(e),
                        "success": False,
                    }
                )

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error=str(e),
                    status="error",
                )

                success = False
                error_msg = f"Tool {tool_name} failed: {str(e)}"
                break

        end_time = time.time()
        execution_time_ms = int((end_time - start_time) * 1000)

        # Emit skill completion
        yield AgentThoughtEvent(
            content=f"Skill {skill.name} {'completed' if success else 'failed'}",
            thought_level="skill_complete",
        )

        # Final result event with all tool outputs
        yield AgentSkillExecutionCompleteEvent(
            skill_id=skill.id,
            skill_name=skill.name,
            success=success,
            tool_results=tool_results,
            execution_time_ms=execution_time_ms,
            error=error_msg,
        )

    async def _sync_skill_resources(
        self,
        skill: Skill,
        sandbox_id: Optional[str] = None,
    ) -> None:
        """
        Synchronize SKILL resources to execution environment.

        Uses unified SkillResourcePort when available, falls back to legacy
        injector for backwards compatibility.

        Args:
            skill: Skill whose resources to sync
            sandbox_id: Optional Sandbox ID (if in sandbox environment)

        Raises:
            Exception: Propagates sync errors for caller to handle
        """
        # Prefer unified SkillResourcePort
        if self._skill_resource_port:
            resource_context = SkillResourceContext(
                skill_name=skill.name,
                skill_content=skill.prompt_template,
                tenant_id=self._tenant_id,
                project_id=self._project_id,
                sandbox_id=sandbox_id,
                project_path=self._project_path,
            )

            # Sync resources (no-op for local, injects for sandbox)
            sync_result = await self._skill_resource_port.sync_resources(resource_context)

            if not sync_result.success:
                errors_str = "; ".join(sync_result.errors[:3])
                raise RuntimeError(f"Resource sync failed: {errors_str}")

            # Setup environment
            await self._skill_resource_port.setup_environment(resource_context)

            logger.debug(
                f"Skill {skill.name} resources synced via {self._skill_resource_port.environment.value} adapter"
            )
            return

        # Legacy fallback: use resource_injector + sandbox_adapter
        if sandbox_id and self._resource_injector and self._sandbox_adapter:
            await self._inject_skill_resources_legacy(skill, sandbox_id)

    async def _inject_skill_resources_legacy(
        self,
        skill: Skill,
        sandbox_id: str,
    ) -> None:
        """
        Legacy method: Inject SKILL resources into Sandbox.

        Deprecated: Use SkillResourcePort instead.

        Args:
            skill: Skill whose resources to inject
            sandbox_id: Target Sandbox ID

        Raises:
            Exception: Propagates injection errors for caller to handle
        """
        logger.warning(
            f"Using legacy resource injection for skill {skill.name}. "
            "Consider upgrading to SkillResourcePort."
        )

        await self._resource_injector.inject_skill(
            self._sandbox_adapter,
            sandbox_id=sandbox_id,
            skill_name=skill.name,
            skill_content=skill.prompt_template,
        )

        await self._resource_injector.setup_skill_environment(
            self._sandbox_adapter,
            sandbox_id=sandbox_id,
            skill_name=skill.name,
        )

    def get_skill_tools_description(self, skill: Skill) -> str:
        """
        Get description of tools in a skill.

        Args:
            skill: Skill to describe

        Returns:
            Human-readable tool composition description
        """
        tool_descs = []
        for tool_name in skill.tools:
            if tool_name in self.tools:
                tool = self.tools[tool_name]
                desc = getattr(tool, "description", f"Tool: {tool_name}")
                tool_descs.append(f"  - {tool_name}: {desc}")

        return "\n".join(tool_descs)

    def get_resource_port(self) -> Optional[SkillResourcePort]:
        """Get the configured SkillResourcePort."""
        return self._skill_resource_port

    @property
    def environment(self) -> Optional[ResourceEnvironment]:
        """Get the current resource environment type."""
        if self._skill_resource_port:
            return self._skill_resource_port.environment
        return None
