"""SubAgent chain execution engine.

Supports sequential (pipeline) and conditional (branching) SubAgent chains
where the output of one SubAgent feeds into the next.

Usage:
    chain = SubAgentChain(steps=[
        ChainStep(subagent=researcher, task_template="{input}"),
        ChainStep(subagent=writer, task_template="Write a report: {input}\n\nResearch: {prev}"),
    ])
    async for event in chain.execute(user_message="Analyze market trends", ...):
        yield event
    result = chain.result
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.agent.processor.factory import ProcessorFactory

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult

from .context_bridge import ContextBridge
from .process import SubAgentProcess

logger = logging.getLogger(__name__)


@dataclass
class ChainStep:
    """A single step in a SubAgent chain.

    Attributes:
        subagent: The SubAgent to execute at this step.
        task_template: Template for the task message. Supports placeholders:
            {input} - original user message
            {prev} - previous step's summary
            {prev_full} - previous step's full content
            {step_N} - output from step N (0-indexed)
        condition: Optional callable that receives the previous result and
            returns True if this step should execute.
        name: Optional display name for this step (defaults to SubAgent name).
    """

    subagent: SubAgent
    task_template: str = "{input}"
    condition: Callable[[SubAgentResult | None], bool] | None = None
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.subagent.display_name


@dataclass(frozen=True)
class ChainResult:
    """Aggregated result from a SubAgent chain execution.

    Attributes:
        steps_completed: Number of steps that ran.
        total_steps: Total steps in the chain.
        results: Ordered list of results from each executed step.
        final_summary: Summary from the last executed step.
        success: True if all executed steps succeeded.
        skipped_steps: Names of steps skipped by conditions.
        total_tokens: Sum of tokens across all steps.
        total_tool_calls: Sum of tool calls across all steps.
        execution_time_ms: Total wall-clock time.
    """

    steps_completed: int
    total_steps: int
    results: tuple[Any, ...] = ()
    final_summary: str = ""
    success: bool = True
    skipped_steps: tuple[str, ...] = ()
    total_tokens: int = 0
    total_tool_calls: int = 0
    execution_time_ms: int = 0

    def to_event_data(self) -> dict[str, Any]:
        return {
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "final_summary": self.final_summary,
            "success": self.success,
            "skipped_steps": list(self.skipped_steps),
            "total_tokens": self.total_tokens,
            "total_tool_calls": self.total_tool_calls,
            "execution_time_ms": self.execution_time_ms,
        }


class SubAgentChain:
    """Executes a sequence of SubAgents as a pipeline.

    Each step receives the output of the previous step via template variables.
    Steps with conditions are only executed if the condition returns True.
    """

    def __init__(self, steps: list[ChainStep]) -> None:
        if not steps:
            raise ValueError("Chain must have at least one step")
        self._steps = steps
        self._result: ChainResult | None = None
        self._step_results: dict[int, SubAgentResult] = {}

    @property
    def result(self) -> ChainResult | None:
        return self._result

    async def execute(
        self,
        user_message: str,
        tools: list[Any],
        base_model: str,
        base_api_key: str | None = None,
        base_url: str | None = None,
        llm_client: LLMClient | None = None,
        conversation_context: list[dict[str, str]] | None = None,
        main_token_budget: int = 200000,
        project_id: str = "",
        tenant_id: str = "",
        abort_signal: asyncio.Event | None = None,
        factory: ProcessorFactory | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute the chain sequentially.

        Yields SSE events from each step, plus chain lifecycle events.

        Args:
            user_message: Original user message ({input} in templates).
            tools: Available tool definitions.
            base_model: Default model for SubAgents.
            base_api_key: API key for LLM calls.
            base_url: Base URL for LLM API.
            llm_client: Shared LLM client instance.
            conversation_context: Main agent's conversation context.
            main_token_budget: Main agent's token budget.
            project_id: Project scope.
            tenant_id: Tenant scope.
            abort_signal: Cancellation signal.
        """

        start_time = time.time()
        results: list[SubAgentResult] = []
        skipped: list[str] = []
        all_success = True
        prev_result: SubAgentResult | None = None

        yield self._make_event(
            "chain_started",
            {
                "total_steps": len(self._steps),
                "step_names": [s.name for s in self._steps],
            },
        )

        for idx, step in enumerate(self._steps):
            # Check abort signal
            if abort_signal and abort_signal.is_set():
                logger.info(f"[SubAgentChain] Aborted at step {idx}")
                break

            # Evaluate condition
            if step.condition is not None:
                should_run = step.condition(prev_result)
                if not should_run:
                    skipped.append(step.name)
                    yield self._make_event(
                        "chain_step_skipped",
                        {
                            "step_index": idx,
                            "step_name": step.name,
                            "reason": "condition not met",
                        },
                    )
                    continue

            # Build task message from template
            task_message = self._render_template(
                step.task_template,
                user_message,
                prev_result,
                idx,
            )

            yield self._make_event(
                "chain_step_started",
                {
                    "step_index": idx,
                    "step_name": step.name,
                    "task_preview": task_message[:200],
                },
            )

            # Build context and process
            bridge = ContextBridge()
            context = bridge.build_subagent_context(
                user_message=task_message,
                subagent_system_prompt=step.subagent.system_prompt,
                conversation_context=conversation_context,
                main_token_budget=main_token_budget,
                project_id=project_id,
                tenant_id=tenant_id,
            )

            process = SubAgentProcess(
                subagent=step.subagent,
                context=context,
                tools=tools,
                base_model=base_model,
                base_api_key=base_api_key,
                base_url=base_url,
                llm_client=llm_client,
                abort_signal=abort_signal,
                factory=factory,
            )

            # Execute and relay events
            async for event in process.execute():
                yield event

            step_result = process.result
            if step_result:
                results.append(step_result)
                self._step_results[idx] = step_result
                prev_result = step_result

                if not step_result.success:
                    all_success = False
                    yield self._make_event(
                        "chain_step_failed",
                        {
                            "step_index": idx,
                            "step_name": step.name,
                            "error": step_result.error or "Unknown error",
                        },
                    )
                    break
            else:
                all_success = False
                break

            yield self._make_event(
                "chain_step_completed",
                {
                    "step_index": idx,
                    "step_name": step.name,
                    "summary": step_result.summary[:200] if step_result else "",
                },
            )

        end_time = time.time()
        execution_time_ms = int((end_time - start_time) * 1000)

        final_summary = results[-1].summary if results else "No steps completed."

        self._result = ChainResult(
            steps_completed=len(results),
            total_steps=len(self._steps),
            results=tuple(results),
            final_summary=final_summary,
            success=all_success,
            skipped_steps=tuple(skipped),
            total_tokens=sum(r.tokens_used for r in results),
            total_tool_calls=sum(r.tool_calls_count for r in results),
            execution_time_ms=execution_time_ms,
        )

        yield self._make_event("chain_completed", self._result.to_event_data())

    def _render_template(
        self,
        template: str,
        user_message: str,
        prev_result: SubAgentResult | None,
        current_step: int,
    ) -> str:
        """Render a task template with variable substitution.

        Supported variables:
        - {input}: original user message
        - {prev}: previous step's summary
        - {prev_full}: previous step's full content
        - {step_N}: output from step N
        """
        rendered = template.replace("{input}", user_message)

        if prev_result:
            rendered = rendered.replace("{prev}", prev_result.summary)
            rendered = rendered.replace("{prev_full}", prev_result.final_content)
        else:
            rendered = rendered.replace("{prev}", "")
            rendered = rendered.replace("{prev_full}", "")

        # Replace {step_N} references
        for idx, result in self._step_results.items():
            rendered = rendered.replace(f"{{step_{idx}}}", result.summary)

        return rendered

    def _make_event(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }
