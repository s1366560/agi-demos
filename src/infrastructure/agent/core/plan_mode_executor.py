"""
Plan Mode Executor for ReAct Agent.

Encapsulates the Plan Mode execution workflow:
1. Generate execution plan using PlanGenerator
2. Execute plan steps using PlanExecutor
3. Reflect and optionally adjust using PlanReflector
4. Emit events for frontend updates
"""

import logging
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from .processor import ToolDefinition

logger = logging.getLogger(__name__)


class PlanModeExecutor:
    """Executes Plan Mode workflows, extracted from ReActAgent."""

    class SessionProcessorWrapper:
        """Simple session processor wrapper for tool execution in Plan Mode."""

        def __init__(self, tools, permission_manager):
            self.tools = tools
            self.permission_manager = permission_manager

        async def execute_tool(
            self, tool_name: str, tool_input: Dict, conversation_id: str
        ) -> str:
            """Execute a tool by name."""
            if tool_name == "__think__":
                return f"Thought: {tool_input.get('thought', '')}"

            # Find the tool
            tool = None
            for t in self.tools:
                if t.name == tool_name:
                    tool = t
                    break

            if not tool:
                return f"Error: Tool '{tool_name}' not found"

            # Execute the tool
            try:
                result = await tool.execute(**tool_input)
                return str(result) if result else ""
            except Exception as e:
                return f"Error executing {tool_name}: {e!s}"

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        permission_manager: Optional[Any] = None,
        llm_client: Optional[Any] = None,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.permission_manager = permission_manager
        self._llm_client = llm_client

    async def execute_plan_mode(
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        conversation_context: List[Dict[str, str]],
        detection_result: Any,
        get_current_tools_fn: Callable[[], Tuple[Dict[str, Any], List[ToolDefinition]]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute Plan Mode workflow.

        Args:
            conversation_id: Conversation ID
            user_message: User's query
            project_id: Project ID
            user_id: User ID
            tenant_id: Tenant ID
            conversation_context: Conversation history
            detection_result: Detection result from detector
            get_current_tools_fn: Callable returning (raw_tools, tool_definitions)

        Yields:
            Event dictionaries for Plan Mode execution
        """
        from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient

        from ..planning.plan_adjuster import PlanAdjuster
        from ..planning.plan_executor import PlanExecutor
        from ..planning.plan_generator import PlanGenerator
        from ..planning.plan_mode_orchestrator import PlanModeOrchestrator
        from ..planning.plan_reflector import PlanReflector

        logger.info("[PlanModeExecutor] Executing Plan Mode workflow")

        # Emit plan_mode_entered event
        yield {
            "type": "plan_mode_entered",
            "data": {
                "conversation_id": conversation_id,
                "method": detection_result.method,
                "confidence": detection_result.confidence,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Create LLM client for Plan Mode components
        llm_client = LiteLLMClient(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
        )

        # Get current tools (hot-plug support)
        _, current_tool_definitions = get_current_tools_fn()

        # Create Plan Mode components
        generator = PlanGenerator(
            llm_client=llm_client,
            available_tools=current_tool_definitions,
        )

        # Create wrapper instance
        session_processor = self.SessionProcessorWrapper(
            current_tool_definitions, self.permission_manager
        )

        # Event emitter for Plan Mode events
        plan_events = []

        def event_emitter(event):
            plan_events.append(event)
            logger.debug(f"[PlanMode] Event emitted: {event['type']}")

        # Create executor with event emitter
        executor = PlanExecutor(
            session_processor=session_processor,
            event_emitter=event_emitter,
            parallel_execution=False,  # Sequential execution for stability
            max_parallel_steps=1,
        )

        reflector = PlanReflector(
            llm_client=llm_client,
            max_tokens=2048,
        )

        adjuster = PlanAdjuster()

        # Create orchestrator
        orchestrator = PlanModeOrchestrator(
            plan_generator=generator,
            plan_executor=executor,
            plan_reflector=reflector,
            plan_adjuster=adjuster,
            event_emitter=event_emitter,
            max_reflection_cycles=3,
        )

        try:
            # Generate plan
            logger.info("[PlanModeExecutor] Generating execution plan")
            yield {
                "type": "plan_generation_started",
                "data": {
                    "conversation_id": conversation_id,
                    "query": user_message[:100],
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            plan = await generator.generate_plan(
                conversation_id=conversation_id,
                query=user_message,
                context=conversation_context,
                reflection_enabled=True,
                max_reflection_cycles=3,
            )

            # Emit plan_generated event
            yield {
                "type": "plan_generated",
                "data": {
                    "plan_id": plan.id,
                    "title": f"Plan for: {user_message[:50]}...",
                    "status": plan.status.value,
                    "steps": [
                        {
                            "step_id": step.step_id,
                            "description": step.description,
                            "tool_name": step.tool_name,
                            "status": step.status.value,
                            "dependencies": step.dependencies,
                        }
                        for step in plan.steps
                    ],
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Execute plan with orchestrator
            logger.info(f"[PlanModeExecutor] Executing plan with {len(plan.steps)} steps")
            yield {
                "type": "plan_execution_started",
                "data": {
                    "plan_id": plan.id,
                    "step_count": len(plan.steps),
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Stream plan events during execution
            for event in plan_events:
                yield self._convert_plan_event(event)
            plan_events.clear()

            # Execute the plan
            final_plan = await orchestrator.execute_plan(plan=plan)

            # Emit any remaining events
            for event in plan_events:
                yield self._convert_plan_event(event)

            # Emit plan_complete event
            completed_steps = sum(
                1 for s in final_plan.steps if s.status.value == "completed"
            )
            failed_steps = sum(1 for s in final_plan.steps if s.status.value == "failed")

            yield {
                "type": "plan_complete",
                "data": {
                    "plan_id": final_plan.id,
                    "status": final_plan.status.value,
                    "summary": f"Plan execution completed. "
                    f"Completed: {completed_steps}, Failed: {failed_steps}",
                    "completed_steps": completed_steps,
                    "failed_steps": failed_steps,
                    "total_steps": len(final_plan.steps),
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(
                f"[PlanModeExecutor] Plan Mode execution failed: {e}", exc_info=True
            )
            yield {
                "type": "plan_execution_failed",
                "data": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

    def _convert_plan_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert internal Plan Mode event to SSE event format.

        Args:
            event: Internal event from Plan Mode components

        Returns:
            SSE-compatible event dict
        """
        event_type = event.get("type", "unknown")

        # Map internal event types to SSE types
        type_mapping = {
            "PLAN_EXECUTION_START": "plan_execution_start",
            "PLAN_STEP_READY": "plan_step_ready",
            "PLAN_STEP_COMPLETE": "plan_step_complete",
            "PLAN_STEP_SKIPPED": "plan_step_skipped",
            "PLAN_EXECUTION_COMPLETE": "plan_execution_complete",
            "REFLECTION_COMPLETE": "reflection_complete",
            "ADJUSTMENT_APPLIED": "adjustment_applied",
        }

        return {
            "type": type_mapping.get(event_type, event_type.lower()),
            "data": event.get("data", {}),
            "timestamp": datetime.utcnow().isoformat(),
        }
