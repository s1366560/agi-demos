# pyright: reportUninitializedInstanceVariable=false
"""Stream-pipeline mixin extracted from ``react_agent.py``.

Hosts the private ``_stream_*`` orchestration helpers that the public
:meth:`ReActAgent.stream` coroutine drives. Pure code move — no behavior
change. ``ReActAgent`` composes this mixin via multiple inheritance.

Out of scope (deferred):
- ``stream`` itself (HIGH risk, requires dedicated commit)
- ``_stream_inject_subagent_tools`` (strongly coupled to subagent runner;
  belongs with PR-7d)
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast
from uuid import uuid4

from src.domain.events.agent_events import (
    AgentCompleteEvent,
    AgentContextCompressedEvent,
    AgentContextStatusEvent,
    AgentContextSummaryGeneratedEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentPlanSuggestedEvent,
    AgentPolicyFilteredEvent,
    AgentSelectionTraceEvent,
    AgentSkillMatchedEvent,
    AgentThoughtEvent,
)
from src.domain.model.agent.skill import Skill
from src.domain.ports.agent.context_manager_port import ContextBuildRequest

from ..plugins.selection_pipeline import ToolSelectionContext, ToolSelectionTraceStep
from ..routing import ExecutionPath, RoutingDecision
from ..skill import SkillProtocol

if TYPE_CHECKING:
    from .processor import ProcessorConfig, SessionProcessor, ToolDefinition

logger = logging.getLogger(__name__)


class _StreamAgent(Protocol):
    """Subset of ``ReActAgent`` state used by :class:`StreamMixin`."""

    skills: list[Skill]
    agent_mode: str
    skill_match_threshold: float
    subagents: list[Any]
    permission_manager: Any
    context_facade: Any
    _plan_detector: Any
    _resource_sync_service: Any
    _llm_client: Any
    _last_tool_selection_trace: tuple[ToolSelectionTraceStep, ...]
    _tool_selection_max_tools: int
    _use_dynamic_tools: bool
    _tool_provider: Callable[..., Any] | None

    # mutable stream-phase state set by these helpers and consumed by ``stream``
    _stream_skill_state: dict[str, Any]
    _stream_context_result: Any
    _stream_messages: list[dict[str, Any]]
    _stream_cached_summary: Any
    _stream_tools_to_use: list[Any]
    _stream_final_content: str
    _stream_success: bool

    # delegated methods (live on ReActAgent or sibling mixins)
    def _match_skill(
        self,
        query: str,
        available_skills: list[SkillProtocol] | None = None,
    ) -> tuple[SkillProtocol | None, float]: ...

    def _get_current_tools(
        self,
        selection_context: ToolSelectionContext | None = None,
    ) -> tuple[dict[str, Any], list[ToolDefinition]]: ...

    def _decide_execution_path(
        self,
        *,
        message: str,
        conversation_context: list[dict[str, str]],
        forced_subagent_name: str | None = ...,
        forced_skill_name: str | None = ...,
        plan_mode_requested: bool = ...,
    ) -> RoutingDecision: ...

    def _build_tool_selection_context(
        self,
        *,
        tenant_id: str,
        project_id: str,
        user_message: str,
        conversation_context: list[dict[str, str]],
        effective_mode: str,
        routing_metadata: Any = ...,
        allow_tools: list[str] | None = ...,
        deny_tools: list[str] | None = ...,
    ) -> ToolSelectionContext: ...

    def _extract_sandbox_id_from_tools(self) -> str | None: ...

    def _convert_domain_event(
        self,
        domain_event: AgentDomainEvent | dict[str, Any],
        *,
        agent_id: str | None = ...,
    ) -> dict[str, Any] | None: ...

    async def _notify_context_overflow_hook(
        self,
        *,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        context_result: Any,
    ) -> list[dict[str, Any]]: ...

    async def _notify_after_turn_complete_hook(
        self,
        *,
        processed_user_message: str,
        final_content: str,
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        matched_skill: Skill | None,
        success: bool,
        execution_time_ms: int = ...,
        tool_call_count: int = ...,
        llm_client_override: Any | None = ...,
    ) -> list[dict[str, Any]]: ...


class StreamMixin:
    """Stream-pipeline orchestration helpers."""

    async def _stream_detect_plan_mode(
        self: _StreamAgent,
        user_message: str,
        conversation_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Detect plan mode and yield suggestion event if appropriate."""
        suggestion = self._plan_detector.detect(user_message)
        if suggestion.should_suggest:
            yield cast(
                dict[str, Any],
                AgentPlanSuggestedEvent(
                    plan_id="",
                    conversation_id=conversation_id,
                    reason=suggestion.reason,
                    confidence=suggestion.confidence,
                ).to_event_dict(),
            )
            logger.info(
                f"[ReActAgent] Plan Mode suggested (confidence={suggestion.confidence:.2f})"
            )

    def _stream_parse_forced_subagent(
        self: _StreamAgent,
        user_message: str,
    ) -> tuple[str | None, str]:
        """Parse forced SubAgent delegation from system instruction prefix.

        Returns:
            Tuple of (forced_subagent_name or None, processed_user_message).
        """
        forced_prefix = '[System Instruction: Delegate this task strictly to SubAgent "'
        if not user_message.startswith(forced_prefix):
            return None, user_message

        try:
            match = re.match(
                r'^\[System Instruction: Delegate this task strictly to SubAgent "([^"]+)"\]',
                user_message,
            )
            if match:
                forced_name = match.group(1)
                processed = user_message.replace(match.group(0), "", 1).strip()
                return forced_name, processed if processed else user_message
        except Exception as e:
            logger.warning(f"[ReActAgent] Failed to parse forced subagent instruction: {e}")

        return None, user_message

    def _resolve_subagent_by_name(self: _StreamAgent, name: str) -> Any | None:
        """Find a SubAgent by name or display_name."""
        for sa in self.subagents or []:
            if sa.enabled and (sa.name == name or sa.display_name == name):
                return sa
        return None

    def _stream_match_skill(
        self: _StreamAgent,
        processed_user_message: str,
        forced_skill_name: str | None,
        available_skills: list[SkillProtocol] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Match skill and yield skill_matched event.

        Sets self._stream_skill_state with matched_skill info.
        """
        is_forced = False
        matched_skill = None
        skill_score = 0.0
        should_inject_prompt = False

        if forced_skill_name:
            # Inline find_by_name: case-insensitive name lookup (Wave 5.1)
            name_lower = forced_skill_name.strip().lower()
            found_skill: SkillProtocol | None = None
            for skill in available_skills or cast("list[SkillProtocol]", self.skills or []):
                if skill.name.lower() == name_lower and skill.status.value == "active":
                    found_skill = skill
                    break
            if found_skill is not None:
                matched_skill = found_skill
                skill_score = 1.0
                is_forced = True
                logger.info(f"[ReActAgent] Forced skill found: {found_skill.name}")
            else:
                yield cast(
                    dict[str, Any],
                    AgentThoughtEvent(
                        content=(
                            f"Forced skill '{forced_skill_name}'"
                            f" not found, falling back to"
                            f" normal matching"
                        ),
                    ).to_event_dict(),
                )
                matched_skill, skill_score = self._match_skill(
                    processed_user_message,
                    available_skills=available_skills,
                )
        else:
            matched_skill, skill_score = self._match_skill(
                processed_user_message,
                available_skills=available_skills,
            )

        should_inject_prompt = matched_skill is not None and (
            is_forced or skill_score >= self.skill_match_threshold
        )

        if not is_forced and matched_skill and skill_score < self.skill_match_threshold:
            matched_skill = None
            skill_score = 0.0

        if matched_skill:
            execution_mode = "forced" if is_forced else "prompt"
            logger.info(
                f"[ReActAgent] Skill matched: name={matched_skill.name}, "
                f"mode={execution_mode}, score={skill_score}, "
                f"prompt_len={len(matched_skill.prompt_template or '')}, "
                f"tools={list(matched_skill.tools)}"
            )
            yield cast(
                dict[str, Any],
                AgentSkillMatchedEvent(
                    skill_id=matched_skill.id,
                    skill_name=matched_skill.name,
                    tools=list(matched_skill.tools),
                    match_score=skill_score,
                    execution_mode=execution_mode,
                ).to_event_dict(),
            )

        self._stream_skill_state = {
            "matched_skill": matched_skill,
            "skill_score": skill_score,
            "is_forced": is_forced,
            "should_inject_prompt": should_inject_prompt,
        }

    async def _stream_sync_skill_resources(
        self: _StreamAgent,
        matched_skill: Skill,
    ) -> None:
        """Sync skill resources to sandbox before prompt injection."""
        if not self._resource_sync_service:
            return
        sandbox_id = self._extract_sandbox_id_from_tools()
        if not sandbox_id:
            return
        try:
            await self._resource_sync_service.sync_for_skill(
                skill_name=matched_skill.name,
                sandbox_id=sandbox_id,
                skill_content=matched_skill.prompt_template,
            )
        except Exception as e:
            logger.warning(
                f"Skill resource sync failed for INJECT mode (skill={matched_skill.name}): {e}"
            )

    async def _stream_build_context(
        self: _StreamAgent,
        *,
        system_prompt: str,
        conversation_context: list[dict[str, str]],
        processed_user_message: str,
        attachment_metadata: list[dict[str, Any]] | None,
        attachment_content: list[dict[str, Any]] | None,
        context_summary_data: dict[str, Any] | None,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Build context via ContextFacade, yield compression/flush events.

        Sets self._stream_context_result and self._stream_messages.
        """
        cached_summary = None
        if context_summary_data:
            from src.domain.model.agent.conversation.context_summary import ContextSummary

            try:
                cached_summary = ContextSummary.from_dict(context_summary_data)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[ReActAgent] Invalid context summary data: {e}")

        context_request = ContextBuildRequest(
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            user_message=processed_user_message,
            attachment_metadata=attachment_metadata,
            attachment_content=attachment_content,
            is_hitl_resume=False,
            context_summary=cached_summary,
            llm_client=self._llm_client,
        )
        context_result = await self.context_facade.build_context(context_request)
        self._stream_context_result = context_result
        self._stream_messages = context_result.messages
        self._stream_cached_summary = cached_summary

        if attachment_metadata:
            logger.info(
                f"[ReActAgent] Context built with {len(attachment_metadata)} attachments: "
                f"{[m.get('filename') for m in attachment_metadata]}"
            )
        if attachment_content:
            logger.info(f"[ReActAgent] Added {len(attachment_content)} multimodal attachments")

        # Emit context_compressed event if compression occurred
        if context_result.was_compressed:
            yield cast(
                dict[str, Any],
                AgentContextCompressedEvent(**context_result.to_event_data()).to_event_dict(),
            )
            logger.info(
                f"Context compressed: {context_result.original_message_count} -> "
                f"{context_result.final_message_count} messages, "
                f"strategy: {context_result.compression_strategy.value}"
            )

            if context_result.summary and not cached_summary:
                yield cast(
                    dict[str, Any],
                    AgentContextSummaryGeneratedEvent(
                        summary_text=context_result.summary,
                        summary_tokens=(context_result.estimated_tokens),
                        messages_covered_count=(context_result.summarized_message_count),
                        compression_level=(context_result.compression_strategy.value),
                    ).to_event_dict(),
                )

            hook_events = await self._notify_context_overflow_hook(
                tenant_id=tenant_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_context=conversation_context,
                context_result=context_result,
            )
            for event in hook_events:
                yield event

        # Emit initial context_status
        compression_level = context_result.metadata.get("compression_level", "none")
        yield cast(
            dict[str, Any],
            AgentContextStatusEvent(
                current_tokens=(context_result.estimated_tokens),
                token_budget=context_result.token_budget,
                occupancy_pct=round(
                    context_result.budget_utilization_pct,
                    1,
                ),
                compression_level=compression_level,
                token_distribution={},
                compression_history_summary=(
                    context_result.metadata.get("compression_history", {})
                ),
                from_cache=cached_summary is not None,
                messages_in_summary=(
                    cached_summary.messages_covered_count if cached_summary else 0
                ),
            ).to_event_dict(),
        )

    def _stream_prepare_tools(
        self: _StreamAgent,
        selection_context: ToolSelectionContext,
        is_forced: bool,
        matched_skill: Skill | None,
    ) -> Iterator[dict[str, Any]]:
        """Prepare tools with selection trace and policy filtering events.

        Sets self._stream_tools_to_use.
        """
        _current_raw_tools, current_tool_definitions = self._get_current_tools(
            selection_context=selection_context
        )
        if self._last_tool_selection_trace:
            removed_total = sum(len(step.removed_tools) for step in self._last_tool_selection_trace)
            route_id = selection_context.metadata.get("route_id")
            trace_id = selection_context.metadata.get("trace_id", route_id)
            trace_data = [
                {
                    "stage": step.stage,
                    "before_count": step.before_count,
                    "after_count": step.after_count,
                    "removed_count": len(step.removed_tools),
                    "duration_ms": step.duration_ms,
                    "explain": dict(step.explain),
                }
                for step in self._last_tool_selection_trace
            ]
            semantic_stage = next(
                (stage for stage in trace_data if stage["stage"] == "semantic_ranker_stage"),
                None,
            )
            tool_budget_value = (
                semantic_stage.get("explain", {}).get("max_tools") if semantic_stage else None  # type: ignore[attr-defined]
            )
            tool_budget = (
                int(tool_budget_value)
                if isinstance(tool_budget_value, (int, float))
                else self._tool_selection_max_tools
            )
            budget_exceeded_stages = [
                stage["stage"]
                for stage in trace_data
                if isinstance(stage.get("explain"), dict)
                and stage["explain"].get("budget_exceeded")  # type: ignore[attr-defined]
            ]
            yield cast(
                dict[str, Any],
                AgentSelectionTraceEvent(
                    route_id=route_id,
                    trace_id=trace_id,
                    initial_count=cast(int, trace_data[0]["before_count"]),
                    final_count=cast(int, trace_data[-1]["after_count"]),
                    removed_total=removed_total,
                    domain_lane=(selection_context.metadata.get("domain_lane")),
                    tool_budget=tool_budget,
                    budget_exceeded_stages=[str(s) for s in budget_exceeded_stages],
                    stages=trace_data,
                ).to_event_dict(),
            )
            if removed_total > 0:
                yield cast(
                    dict[str, Any],
                    AgentPolicyFilteredEvent(
                        route_id=route_id,
                        trace_id=trace_id,
                        removed_total=removed_total,
                        stage_count=len(trace_data),
                        domain_lane=(selection_context.metadata.get("domain_lane")),
                        tool_budget=tool_budget,
                        budget_exceeded_stages=[str(s) for s in budget_exceeded_stages],
                    ).to_event_dict(),
                )
        tools_to_use = list(current_tool_definitions)

        # When a forced skill is active, keep all core tools available
        # but remove skill_loader to prevent loading other skills.
        # The skill's prompt template is already injected into the system prompt,
        # so the agent can use any core tool to fulfill the skill's instructions.
        if is_forced and matched_skill:
            tools_to_use = [t for t in tools_to_use if t.name != "skill_loader"]
            skill_tools = set(matched_skill.tools) if matched_skill.tools else set()
            logger.info(
                f"[ReActAgent] Forced skill '{matched_skill.name}' active: "
                f"removed skill_loader, keeping {len(tools_to_use)} tools. "
                f"Skill declared tools={list(skill_tools)}"
            )

        self._stream_tools_to_use = tools_to_use

    def _stream_create_processor_config(
        self: _StreamAgent,
        config: ProcessorConfig,
        selection_context: ToolSelectionContext,
    ) -> ProcessorConfig:
        """Create request-scoped processor config, optionally with dynamic tool provider."""
        from .processor import ProcessorConfig as _ProcessorConfig

        tool_provider: Callable[[], list[ToolDefinition]] | None = config.tool_provider
        if self._use_dynamic_tools and self._tool_provider is not None:

            def _tool_provider_wrapper() -> list[ToolDefinition]:
                _, tool_defs = self._get_current_tools(selection_context=selection_context)
                return list(tool_defs)

            tool_provider = _tool_provider_wrapper

        new_config = _ProcessorConfig(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            max_steps=config.max_steps,
            max_tool_calls_per_step=config.max_tool_calls_per_step,
            enable_parallel_tool_execution=config.enable_parallel_tool_execution,
            parallel_tool_batch_size=config.parallel_tool_batch_size,
            doom_loop_threshold=config.doom_loop_threshold,
            max_no_progress_steps=config.max_no_progress_steps,
            max_attempts=config.max_attempts,
            initial_delay_ms=config.initial_delay_ms,
            permission_timeout=config.permission_timeout,
            continue_on_deny=config.continue_on_deny,
            context_limit=config.context_limit,
            max_cost_per_request=config.max_cost_per_request,
            max_cost_per_session=config.max_cost_per_session,
            llm_client=config.llm_client,
            plugin_registry=config.plugin_registry,
            runtime_hook_overrides=[dict(item) for item in config.runtime_hook_overrides],
            runtime_context=dict(config.runtime_context),
            tool_provider=tool_provider,
            forced_skill_name=config.forced_skill_name,
            forced_skill_tools=(
                list(config.forced_skill_tools) if config.forced_skill_tools else None
            ),
            skill_names=list(config.skill_names),
            provider_options=dict(config.provider_options),
            message_bus=config.message_bus,
            control_channel=config.control_channel,
            run_id=config.run_id,
        )
        if tool_provider is not None:
            logger.debug(
                "[ReActAgent] Created processor config with tool_provider for dynamic tools"
            )
        return new_config

    async def _stream_process_events(
        self: _StreamAgent,
        processor: SessionProcessor,
        messages: list[dict[str, Any]],
        langfuse_context: dict[str, Any],
        abort_signal: asyncio.Event | None,
        matched_skill: Skill | None,
        agent_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Process events from SessionProcessor and yield converted events.

        Sets self._stream_final_content and self._stream_success.
        """
        from .processor import RunContext as _RunContext

        self._stream_final_content = ""
        self._stream_success = True

        try:
            run_ctx = _RunContext(
                abort_signal=abort_signal,
                langfuse_context=langfuse_context,
                conversation_id=langfuse_context.get("conversation_id")
                if langfuse_context
                else None,
                agent_id=agent_id,
            )
            async for domain_event in processor.process(
                session_id=langfuse_context["conversation_id"],
                messages=messages,
                run_ctx=run_ctx,
            ):
                event = self._convert_domain_event(domain_event, agent_id=agent_id)
                if event:
                    if event.get("type") == "text_delta":
                        self._stream_final_content += event.get("data", {}).get("delta", "")
                    elif event.get("type") == "text_end":
                        text_end_content = event.get("data", {}).get("full_text", "")
                        if text_end_content:
                            self._stream_final_content = text_end_content

                    yield event

        except Exception as e:
            logger.error(f"[ReActAgent] Error in stream: {e}", exc_info=True)
            self._stream_success = False
            yield cast(
                dict[str, Any],
                AgentErrorEvent(
                    message=str(e),
                    code=type(e).__name__,
                ).to_event_dict(),
            )

    async def _stream_post_process(
        self: _StreamAgent,
        *,
        processed_user_message: str,
        final_content: str,
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        matched_skill: Skill | None,
        success: bool,
        execution_time_ms: int = 0,
        tool_call_count: int = 0,
        llm_client_override: Any | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Post-process: memory capture, conversation indexing, final complete event."""
        hook_events = await self._notify_after_turn_complete_hook(
            processed_user_message=processed_user_message,
            final_content=final_content,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            matched_skill=matched_skill,
            success=success,
            execution_time_ms=execution_time_ms,
            tool_call_count=tool_call_count,
            llm_client_override=llm_client_override,
        )
        for event in hook_events:
            yield event

        # Yield final complete event
        yield cast(
            dict[str, Any],
            AgentCompleteEvent(
                content=final_content,
                skill_used=(matched_skill.name if matched_skill else None),
            ).to_event_dict(),
        )

    def _stream_decide_route(
        self: _StreamAgent,
        *,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
        forced_subagent_name: str | None,
        forced_skill_name: str | None,
        plan_mode: bool,
    ) -> tuple[RoutingDecision, str, str, dict[str, Any], str | None, dict[str, Any]]:
        """Compute routing decision and build the execution_path_decided event.

        Returns:
            (routing_decision, route_id, trace_id, routing_metadata,
             forced_skill_name, event_dict)
        """
        routing_decision = self._decide_execution_path(
            message=processed_user_message,
            conversation_context=conversation_context,
            forced_subagent_name=forced_subagent_name,
            forced_skill_name=forced_skill_name,
            plan_mode_requested=plan_mode,
        )
        route_id = uuid4().hex
        trace_id = route_id
        routing_metadata = dict(routing_decision.metadata or {})
        routing_metadata["route_id"] = route_id
        routing_metadata["trace_id"] = trace_id
        event_dict = {
            "type": "execution_path_decided",
            "data": {
                "route_id": route_id,
                "trace_id": trace_id,
                "path": routing_decision.path.value,
                "confidence": routing_decision.confidence,
                "reason": routing_decision.reason,
                "target": routing_decision.target,
                "metadata": routing_metadata,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if (
            not forced_skill_name
            and routing_decision.path == ExecutionPath.DIRECT_SKILL
            and routing_decision.target
        ):
            forced_skill_name = routing_decision.target
        return routing_decision, route_id, trace_id, routing_metadata, forced_skill_name, event_dict

    def _stream_resolve_mode(
        self: _StreamAgent,
        *,
        plan_mode: bool,
        routing_decision: RoutingDecision,
        routing_metadata: dict[str, Any],
        tenant_id: str,
        project_id: str,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
        allow_tools: list[str] | None = None,
        deny_tools: list[str] | None = None,
    ) -> tuple[str, ToolSelectionContext]:
        """Resolve effective mode and build selection context.

        Returns:
            (effective_mode, selection_context)
        """
        from src.infrastructure.agent.permission.manager import AgentPermissionMode

        plan_mode = plan_mode or routing_decision.path == ExecutionPath.PLAN_MODE
        effective_mode = (
            "plan"
            if plan_mode
            else (self.agent_mode if self.agent_mode in ["build", "plan"] else "build")
        )
        selection_context = self._build_tool_selection_context(
            tenant_id=tenant_id,
            project_id=project_id,
            user_message=processed_user_message,
            conversation_context=conversation_context,
            effective_mode=effective_mode,
            routing_metadata=routing_metadata,
            allow_tools=allow_tools,
            deny_tools=deny_tools,
        )
        if effective_mode == "plan":
            self.permission_manager.set_mode(AgentPermissionMode.PLAN)
        else:
            self.permission_manager.set_mode(AgentPermissionMode.BUILD)
        return effective_mode, selection_context

    def _stream_determine_mode_and_permissions(
        self: _StreamAgent,
        plan_mode: bool,
        routing_decision: RoutingDecision,
    ) -> str:
        """Determine effective execution mode and set permission mode.

        Returns:
            effective_mode: "plan" or "build"
        """
        from src.infrastructure.agent.permission.manager import AgentPermissionMode

        resolved_plan_mode = plan_mode or routing_decision.path == ExecutionPath.PLAN_MODE
        effective_mode = (
            "plan"
            if resolved_plan_mode
            else (self.agent_mode if self.agent_mode in ["build", "plan"] else "build")
        )

        if effective_mode == "plan":
            self.permission_manager.set_mode(AgentPermissionMode.PLAN)
        else:
            self.permission_manager.set_mode(AgentPermissionMode.BUILD)

        return effective_mode

    def _stream_record_skill_usage(self: _StreamAgent, matched_skill: Any, success: bool) -> None:
        """Record skill usage statistics after stream completion."""
        if matched_skill:
            matched_skill.record_usage(success)
            logger.info(
                f"[ReActAgent] Skill {matched_skill.name} usage recorded: success={success}"
            )
