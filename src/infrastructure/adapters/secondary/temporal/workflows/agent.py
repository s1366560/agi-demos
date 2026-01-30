"""
Temporal Workflow for Agent Execution.

This module provides the workflow definition for executing ReAct agents
through Temporal, enabling:
- Long-running agent operations
- Automatic retry and recovery
- Checkpoint-based resumption
- Event persistence to database
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activity definitions using workflow-safe imports
with workflow.unsafe.imports_passed_through():
    from src.infrastructure.adapters.secondary.temporal.activities.agent import (
        clear_agent_running,
        execute_react_agent_activity,  # New: uses ReActAgent (recommended)
        execute_react_step_activity,  # Legacy: hardcoded logic
        save_checkpoint_activity,
        set_agent_running,
    )

logger = logging.getLogger(__name__)


@dataclass
class AgentInput:
    """Input data for agent execution workflow."""

    conversation_id: str
    message_id: str
    user_message: str
    project_id: str
    user_id: str
    tenant_id: str
    agent_config: Dict[str, Any]
    conversation_context: List[Dict[str, Any]]
    max_steps: int = 50
    # Callback info for sending events
    event_callback_url: Optional[str] = None
    # Use new ReActAgent-based Activity (recommended for full feature support)
    use_react_agent: bool = True


@dataclass
class AgentState:
    """Mutable state for agent execution workflow."""

    current_step: int = 0
    sequence_number: int = 0  # Global event sequence number
    thoughts: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)  # To maintain context
    final_content: str = ""
    is_complete: bool = False
    error: Optional[str] = None
    checkpoints_created: List[str] = field(default_factory=list)


@workflow.defn
class AgentExecutionWorkflow:
    """
    Workflow for executing ReAct agent through Temporal.

    This workflow manages the complete agent execution lifecycle:
    1. LLM reasoning (thought generation)
    2. Tool execution (with retries)
    3. Observation collection
    4. Iteration until completion

    Benefits:
    - Automatic retry on failure
    - Checkpoint-based recovery
    - Long-running operation support
    - Event persistence
    """

    @workflow.run
    async def run(self, input: AgentInput) -> Dict[str, Any]:
        """
        Execute the ReAct agent workflow.

        Args:
            input: Agent execution input

        Returns:
            Final execution result with content and metadata
        """
        state = AgentState()

        try:
            # Mark agent as running in Redis
            await workflow.execute_activity(
                set_agent_running,
                args=[input.conversation_id, input.message_id, 300],  # 5 minute TTL
                start_to_close_timeout=timedelta(seconds=10),
            )

            # Choose execution mode
            if input.use_react_agent:
                # New mode: Use ReActAgent (single call, internal loop)
                result = await self._execute_with_react_agent(input, state)
                state.final_content = result.get("content", "")
                state.sequence_number = result.get("sequence_number", 0)
                state.current_step = 1  # Single execution

                if result.get("type") == "error":
                    state.error = result.get("error", "Unknown error")
                    await self._handle_error(input, state, state.error)
                else:
                    state.is_complete = True
            else:
                # Legacy mode: Step-by-step execution (external loop)
                while not state.is_complete and state.current_step < input.max_steps:
                    # Increment step counter
                    state.current_step += 1

                    # Execute one ReAct step
                    step_result = await self._execute_step(input, state)

                    # Update state from result
                    state.sequence_number = step_result.get(
                        "sequence_number", state.sequence_number
                    )

                    # Update messages context if returned (to keep history for next step)
                    if "messages" in step_result:
                        state.messages = step_result["messages"]

                    # Process step result
                    if step_result["type"] == "complete":
                        state.is_complete = True
                        state.final_content = step_result.get("content", "")
                        break
                    elif step_result["type"] == "compact":
                        # Handle compaction (not implemented yet, just continue)
                        continue
                    elif step_result["type"] == "error":
                        state.error = step_result.get("error", "Unknown error")
                        await self._handle_error(input, state, state.error)
                        break
                    elif step_result["type"] == "continue":
                        # Collect thoughts and tool calls (optional, mainly for summary)
                        # Real data is in messages
                        continue

            # Mark complete
            await self._on_complete(input, state)

            return {
                "conversation_id": input.conversation_id,
                "message_id": input.message_id,
                "status": "completed" if not state.error else "error",
                "content": state.final_content,
                "steps_taken": state.current_step,
                "error": state.error,
            }

        except Exception as e:
            logger.error(f"Agent workflow failed: {e}", exc_info=True)
            # Clear running state on error
            await workflow.execute_activity(
                clear_agent_running,
                args=[input.conversation_id],
                start_to_close_timeout=timedelta(seconds=10),
            )
            raise

    async def _execute_with_react_agent(
        self, input: AgentInput, state: AgentState
    ) -> Dict[str, Any]:
        """
        Execute using the new ReActAgent-based Activity.

        This method calls execute_react_agent_activity which internally
        runs the complete ReAct loop using the self-developed ReActAgent.

        Benefits over legacy mode:
        - 30+ event types vs 7
        - Permission management, doom loop detection, cost tracking
        - Skill system (L2) and SubAgent routing (L3)
        - Unified AgentTool interface

        Args:
            input: Agent execution input
            state: Current execution state

        Returns:
            Execution result dictionary
        """
        # Prepare activity input
        activity_input = {
            "conversation_id": input.conversation_id,
            "message_id": input.message_id,
            "user_message": input.user_message,
            "conversation_context": input.conversation_context,
            "agent_config": input.agent_config,
            "project_id": input.project_id,
            "user_id": input.user_id,
            "tenant_id": input.tenant_id,
        }

        # Prepare activity state
        activity_state = {
            "sequence_number": state.sequence_number,
        }

        return await workflow.execute_activity(
            execute_react_agent_activity,
            args=[activity_input, activity_state],
            start_to_close_timeout=timedelta(minutes=10),  # Longer timeout for full execution
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=2,  # Fewer retries since full execution is expensive
            ),
        )

    async def _execute_step(self, input: AgentInput, state: AgentState) -> Dict[str, Any]:
        """
        Execute one ReAct step.

        Args:
            input: Agent execution input
            state: Current execution state

        Returns:
            Step result dictionary
        """
        # Prepare activity input
        activity_input = {
            "conversation_id": input.conversation_id,
            "message_id": input.message_id,
            "user_message": input.user_message,
            "conversation_context": input.conversation_context,
            "agent_config": input.agent_config,
            "project_id": input.project_id,
            "user_id": input.user_id,
            "tenant_id": input.tenant_id,
        }

        # Prepare activity state
        activity_state = {
            "current_step": state.current_step,
            "sequence_number": state.sequence_number,
            "messages": state.messages,
        }

        return await workflow.execute_activity(
            execute_react_step_activity,
            args=[activity_input, activity_state],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
                maximum_attempts=3,
            ),
        )

    async def _handle_error(self, input: AgentInput, state: AgentState, error: str) -> None:
        """Handle execution error."""
        logger.error(f"Agent execution error: {error}")

        # Save error checkpoint
        await self._save_checkpoint(
            input,
            state,
            "error",
            {"error": error, "step": state.current_step},
        )

    async def _on_complete(self, input: AgentInput, state: AgentState) -> None:
        """Handle workflow completion."""
        logger.info(f"Agent execution completed for {input.conversation_id}")

        # Clear running state
        await workflow.execute_activity(
            clear_agent_running,
            args=[input.conversation_id],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Save final checkpoint
        await self._save_checkpoint(
            input,
            state,
            "complete",
            {"content": state.final_content, "step": state.current_step},
        )

    async def _save_checkpoint(
        self,
        input: AgentInput,
        state: AgentState,
        checkpoint_type: str,
        checkpoint_data: Dict[str, Any],
    ) -> None:
        """Save execution checkpoint."""
        execution_state = {
            "step": state.current_step,
            "sequence_number": state.sequence_number,
            "messages": state.messages,
            "data": checkpoint_data,
        }

        await workflow.execute_activity(
            save_checkpoint_activity,
            args=[
                input.conversation_id,
                input.message_id,
                checkpoint_type,
                execution_state,
                state.current_step,
            ],
            start_to_close_timeout=timedelta(seconds=10),
        )
