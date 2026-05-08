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
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
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

from ..plugins.selection_pipeline import ToolSelectionContext
from ..routing import ExecutionPath, RoutingDecision
from ..sisyphus.builtin_agent import BUILTIN_SISYPHUS_ID, build_builtin_sisyphus_agent
from ..skill import SkillProtocol
from ..workspace.runtime_role_contract import (
    WORKSPACE_ROLE_LEADER,
    WORKSPACE_SESSION_ROLE_KEY,
    WORKSPACE_TOOL_MODE_KEY,
    WORKSPACE_TURN_TYPE_KEY,
)
from ..workspace.workspace_metadata_keys import PREFERRED_LANGUAGE

# Runtime imports (not TYPE_CHECKING) — used to construct values inside ``stream``.
from .processor import ToolDefinition
from .react_agent_profile import (
    _infer_provider_from_model_name,
    _normalize_model_provider,
    _register_selected_agent_session,
)

if TYPE_CHECKING:
    from .processor import ProcessorConfig, SessionProcessor

logger = logging.getLogger(__name__)


def _normalize_preferred_language(value: object) -> str | None:
    return value if isinstance(value, str) and value in {"en-US", "zh-CN"} else None


def _preferred_language_from_payload(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    return _normalize_preferred_language(payload.get(PREFERRED_LANGUAGE))


def _workspace_runtime_forwarded_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Forward non-identity workspace runtime fields needed by tools."""
    forwarded: dict[str, Any] = {}
    additional_instructions = payload.get("additional_instructions")
    if isinstance(additional_instructions, str) and additional_instructions.strip():
        forwarded["additional_instructions"] = additional_instructions
    root_override = payload.get("workspace_root_override")
    if isinstance(root_override, Mapping):
        forwarded["workspace_root_override"] = dict(root_override)
    return forwarded


class _StreamAgent(Protocol):
    """Subset of ``ReActAgent`` state used by :class:`StreamMixin`."""

    skills: Any
    agent_mode: Any
    skill_match_threshold: Any
    subagents: Any
    permission_manager: Any
    context_facade: Any
    config: Any
    model: Any
    _plan_detector: Any
    _resource_sync_service: Any
    _llm_client: Any
    _last_tool_selection_trace: Any
    _tool_selection_max_tools: Any
    _use_dynamic_tools: Any
    _tool_provider: Any
    _processor_factory: Any
    _heartbeat_runner: Any
    _skill_mcp_manager: Any
    _skill_mcp_tools: Any
    _enable_subagent_as_tool: Any
    _tool_builder: Any

    # mutable stream-phase state set by these helpers and consumed by ``stream``
    _stream_skill_state: Any
    _stream_context_result: Any
    _stream_messages: Any
    _stream_cached_summary: Any
    _stream_tools_to_use: Any
    _stream_final_content: Any
    _stream_success: Any

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

    # Methods used by ``stream`` and ``_stream_inject_subagent_tools``;
    # live on ReActAgent or sibling mixins.
    def _reset_stream_state(self) -> None: ...

    async def _load_filesystem_skills(self, tenant_id: str, project_id: str) -> None: ...

    async def _load_selected_agent(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> Any: ...

    def _build_runtime_profile(
        self,
        *,
        tenant_id: str,
        tenant_agent_config_data: dict[str, Any] | None,
        selected_agent: Any,
        is_workspace_worker_runtime: bool,
    ) -> Any: ...

    def _with_workspace_leader_replan_tool_allowlist(self, runtime_profile: Any) -> Any: ...

    def _with_workspace_worker_tool_allowlist(self, runtime_profile: Any) -> Any: ...

    def _build_runtime_workspace_manager(self, selected_agent: Any) -> Any: ...

    async def _apply_before_prompt_build_hook(
        self,
        *,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        effective_mode: str,
        matched_skill: Skill | None,
        selected_agent: Any,
    ) -> tuple[Any, list[dict[str, Any]]]: ...

    def _build_primary_agent_prompt(
        self, *, runtime_profile: Any, selection_context: ToolSelectionContext
    ) -> str: ...

    async def _build_system_prompt(self, *args: Any, **kwargs: Any) -> str: ...

    @classmethod
    def _filter_workspace_root_tools(
        cls,
        tools_to_use: list[ToolDefinition],
        workspace_root_task: Any | None,
    ) -> list[ToolDefinition]: ...

    @staticmethod
    def _filter_tools_by_name_policy(
        tools_to_use: list[ToolDefinition],
        *,
        allow_tools: Any,
        deny_tools: Any,
    ) -> list[ToolDefinition]: ...

    @classmethod
    def _workspace_runtime_context(cls, conversation_context: Any) -> Any: ...

    @staticmethod
    def _is_workspace_leader_replan_context(payload: Any) -> bool: ...

    @staticmethod
    def _normalize_workspace_binding(raw: Any) -> dict[str, str] | None: ...

    @classmethod
    def _workspace_binding_from_text(cls, text: str | None) -> dict[str, str] | None: ...

    async def _inject_lane_jit_guidance(
        self,
        *,
        processor: Any,
        project_id: str,
        workspace_task: Any,
    ) -> None: ...

    def _execute_subagent(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...

    async def _launch_subagent_session(self, *args: Any, **kwargs: Any) -> Any: ...

    async def _cancel_subagent_session(self, run_id: str) -> bool: ...

    def _build_subagent_tool_definitions(
        self, *args: Any, **kwargs: Any
    ) -> list[ToolDefinition]: ...

    # Sibling helpers within ``StreamMixin`` itself (declared here so that
    # ``stream`` can call them through ``self: _StreamAgent`` under strict
    # type checking).
    def _stream_detect_plan_mode(
        self, user_message: str, conversation_id: str
    ) -> AsyncIterator[dict[str, Any]]: ...

    def _stream_parse_forced_subagent(self, user_message: str) -> tuple[str | None, str]: ...

    def _stream_decide_route(
        self, *args: Any, **kwargs: Any
    ) -> tuple[RoutingDecision, str, str, dict[str, Any], str | None, dict[str, Any]]: ...

    def _stream_match_skill(self, *args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]: ...

    async def _stream_sync_skill_resources(self, matched_skill: Skill) -> None: ...

    def _stream_resolve_mode(
        self, *args: Any, **kwargs: Any
    ) -> tuple[str, ToolSelectionContext]: ...

    def _stream_build_context(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...

    def _stream_prepare_tools(self, *args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]: ...

    def _stream_inject_subagent_tools(self, *args: Any, **kwargs: Any) -> list[ToolDefinition]: ...

    def _stream_create_processor_config(self, *args: Any, **kwargs: Any) -> ProcessorConfig: ...

    def _stream_process_events(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]: ...

    def _stream_post_process(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...

    def _stream_record_skill_usage(self, matched_skill: Any, success: bool) -> None: ...

    def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...


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

    def _stream_inject_subagent_tools(  # noqa: PLR0915
        self: _StreamAgent,
        tools_to_use: list[ToolDefinition],
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        workspace_root_task: Any | None = None,
        leader_agent_id: str | None = None,
        actor_user_id: str | None = None,
    ) -> list[ToolDefinition]:
        """Inject SubAgent-as-Tool delegation tools when enabled.

        Returns updated tools list with SubAgent tools appended.
        """
        if not self.subagents or not self._enable_subagent_as_tool:
            return tools_to_use

        enabled_subagents = [sa for sa in self.subagents if sa.enabled]
        if not enabled_subagents:
            return tools_to_use

        subagent_map = {sa.name: sa for sa in enabled_subagents}
        subagent_descriptions = {
            sa.name: (sa.trigger.description if sa.trigger else sa.display_name)
            for sa in enabled_subagents
        }

        async def _prepare_workspace_delegation(
            *,
            subagent_name: str,
            subagent_id: str,
            task: str,
            workspace_task_id: str | None = None,
        ) -> dict[str, str] | None:
            if workspace_root_task is None or not actor_user_id:
                return None
            from src.infrastructure.agent.workspace.orchestrator import (
                WorkspaceAutonomyOrchestrator,
            )

            return await WorkspaceAutonomyOrchestrator().prepare_subagent_delegation(
                workspace_id=getattr(workspace_root_task, "workspace_id", project_id),
                root_goal_task_id=getattr(workspace_root_task, "id", ""),
                actor_user_id=actor_user_id,
                delegated_task_text=task,
                subagent_name=subagent_name,
                subagent_id=subagent_id,
                leader_agent_id=leader_agent_id,
                workspace_task_id=workspace_task_id,
            )

        def _decorate_workspace_delegate_task(
            task: str,
            task_binding: dict[str, str] | None,
        ) -> str:
            if not task_binding:
                return task
            return (
                "[workspace-task-binding]\n"
                f"workspace_task_id={task_binding['workspace_task_id']}\n"
                f"attempt_id={task_binding.get('attempt_id', '')}\n"
                f"workspace_agent_binding_id={task_binding.get('workspace_agent_binding_id', '')}\n"
                f"root_goal_task_id={task_binding['root_goal_task_id']}\n"
                f"workspace_id={task_binding['workspace_id']}\n"
                "[/workspace-task-binding]\n\n"
                f"{task}"
            )

        async def _finalize_workspace_delegation(
            *,
            task_binding: dict[str, str] | None,
            report_type: str,
            summary: str,
            artifacts: list[str] | None = None,
        ) -> Any:
            if not task_binding or not actor_user_id:
                return None
            from src.infrastructure.agent.workspace.orchestrator import (
                WorkspaceAutonomyOrchestrator,
            )

            return await WorkspaceAutonomyOrchestrator().apply_worker_report(
                workspace_id=task_binding["workspace_id"],
                root_goal_task_id=task_binding["root_goal_task_id"],
                task_id=task_binding["workspace_task_id"],
                attempt_id=task_binding.get("attempt_id"),
                actor_user_id=actor_user_id,
                worker_agent_id=None,
                report_type=report_type,
                summary=summary,
                artifacts=artifacts,
                leader_agent_id=leader_agent_id,
            )

        def _format_workspace_delegate_result(
            *,
            subagent_name: str,
            task_binding: dict[str, str] | None,
            report_type: str,
            summary: str,
            tokens: int | None = None,
        ) -> str:
            if not task_binding:
                return summary

            lines = [
                f"[SubAgent '{subagent_name}' completed]",
                f"Candidate worker report stored for workspace_task_id={task_binding['workspace_task_id']}",
                f"Suggested report_type={report_type}",
                "Leader adjudication required: review the worker evidence, then use todoread/todowrite to decide whether this task should become completed, failed, remain in_progress, or be replanned.",
                f"Result: {summary}",
            ]
            if isinstance(tokens, int):
                lines.append(f"Tokens used: {tokens}")
            return "\n".join(lines)

        # Create delegation callback that captures stream-scoped context
        async def _delegate_callback(
            subagent_name: str,
            task: str,
            workspace_task_id: str | None = None,
            on_event: Callable[[dict[str, Any]], None] | None = None,
        ) -> str:
            target = subagent_map.get(subagent_name)
            if not target:
                return f"SubAgent '{subagent_name}' not found"

            task_binding = await _prepare_workspace_delegation(
                subagent_name=subagent_name,
                subagent_id=target.id,
                task=task,
                workspace_task_id=workspace_task_id,
            )
            delegated_task = _decorate_workspace_delegate_task(task, task_binding)
            events = []
            async for evt in self._execute_subagent(
                subagent=target,
                user_message=delegated_task,
                conversation_context=conversation_context,
                project_id=project_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                abort_signal=abort_signal,
            ):
                if on_event:
                    event_type = evt.get("type")
                    if event_type not in {"complete", "error"}:
                        on_event(evt)
                events.append(evt)

            complete_evt = next(
                (e for e in events if e.get("type") == "complete"),
                None,
            )
            if complete_evt:
                data = complete_evt.get("data", {})
                content = data.get("content", "")
                sa_result = data.get("subagent_result")
                if sa_result:
                    report_type = "completed" if sa_result.get("success", True) else "blocked"
                    summary = sa_result.get("summary", content)
                    result_summary = summary or content or f"SubAgent {subagent_name} finished"
                    tokens = sa_result.get("tokens_used", 0)
                    await _finalize_workspace_delegation(
                        task_binding=task_binding,
                        report_type=report_type,
                        summary=result_summary,
                    )
                    return _format_workspace_delegate_result(
                        subagent_name=subagent_name,
                        task_binding=task_binding,
                        report_type=report_type,
                        summary=result_summary,
                        tokens=tokens,
                    )
                await _finalize_workspace_delegation(
                    task_binding=task_binding,
                    report_type="completed",
                    summary=content or f"SubAgent {subagent_name} completed",
                )
                return _format_workspace_delegate_result(
                    subagent_name=subagent_name,
                    task_binding=task_binding,
                    report_type="completed",
                    summary=content or "SubAgent completed with no output",
                )

            await _finalize_workspace_delegation(
                task_binding=task_binding,
                report_type="blocked",
                summary=f"SubAgent {subagent_name} execution completed but no result returned",
            )
            return _format_workspace_delegate_result(
                subagent_name=subagent_name,
                task_binding=task_binding,
                report_type="blocked",
                summary="SubAgent execution completed but no result returned",
            )

        async def _spawn_callback(
            subagent_name: str,
            task: str,
            run_id: str,
            **spawn_options: Any,
        ) -> str:
            target = subagent_map.get(subagent_name)
            if not target:
                raise ValueError(f"SubAgent '{subagent_name}' not found")
            task_binding = await _prepare_workspace_delegation(
                subagent_name=subagent_name,
                subagent_id=target.id,
                task=task,
                workspace_task_id=(
                    str(spawn_options.get("workspace_task_id") or "").strip() or None
                ),
            )
            delegated_task = _decorate_workspace_delegate_task(task, task_binding)
            await self._launch_subagent_session(
                run_id=run_id,
                subagent=target,
                user_message=delegated_task,
                conversation_id=conversation_id,
                conversation_context=conversation_context,
                project_id=project_id,
                tenant_id=tenant_id,
                abort_signal=abort_signal,
                model_override=(str(spawn_options.get("model") or "").strip() or None),
                thinking_override=(str(spawn_options.get("thinking") or "").strip() or None),
                spawn_mode=str(spawn_options.get("spawn_mode") or "run"),
                thread_requested=bool(spawn_options.get("thread_requested")),
                cleanup=str(spawn_options.get("cleanup") or "keep"),
                run_metadata=task_binding,
            )
            return run_id

        async def _cancel_spawn_callback(run_id: str) -> bool:
            return await self._cancel_subagent_session(run_id)

        tools_to_use = self._build_subagent_tool_definitions(
            subagent_map=subagent_map,
            subagent_descriptions=subagent_descriptions,
            enabled_subagents=enabled_subagents,
            delegate_callback=_delegate_callback,
            spawn_callback=_spawn_callback,
            cancel_callback=_cancel_spawn_callback,
            conversation_id=conversation_id,
            tools_to_use=tools_to_use,
        )

        logger.info(
            f"[ReActAgent] Injected SubAgent delegation tools "
            f"({len(enabled_subagents)} SubAgents, "
            f"parallel={'yes' if len(enabled_subagents) >= 2 else 'no'}, "
            "sessions=yes)"
        )

        return tools_to_use

    def _build_subagent_tool_definitions(
        self: _StreamAgent,
        *,
        subagent_map: dict[str, Any],
        subagent_descriptions: dict[str, str],
        enabled_subagents: list[Any],
        delegate_callback: Any,
        spawn_callback: Any,
        cancel_callback: Any,
        conversation_id: str,
        tools_to_use: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """Build and append all SubAgent tool definitions to tools list."""
        return self._tool_builder.build_subagent_tool_definitions(
            subagent_map=subagent_map,
            subagent_descriptions=subagent_descriptions,
            enabled_subagents=enabled_subagents,
            delegate_callback=delegate_callback,
            spawn_callback=spawn_callback,
            cancel_callback=cancel_callback,
            conversation_id=conversation_id,
            tools_to_use=tools_to_use,
        )

    async def stream(  # noqa: PLR0913, PLR0912, PLR0915
        self: _StreamAgent,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        conversation_context: list[dict[str, str]] | None = None,
        message_id: str | None = None,
        attachment_content: list[dict[str, Any]] | None = None,
        attachment_metadata: list[dict[str, Any]] | None = None,
        abort_signal: asyncio.Event | None = None,
        forced_skill_name: str | None = None,
        context_summary_data: dict[str, Any] | None = None,
        plan_mode: bool = False,
        llm_overrides: dict[str, Any] | None = None,
        model_override: str | None = None,
        agent_id: str | None = None,
        tenant_agent_config_data: dict[str, Any] | None = None,
        preferred_language: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream agent response with ReAct loop.

        This is the main entry point for agent execution. It:
        1. Checks for Plan Mode triggering
        2. Checks for SubAgent routing (L3)
        3. Checks for Skill matching (L2)
        4. Builds messages from context
        5. Creates SessionProcessor
        6. Streams events back to caller

        Args:
            conversation_id: Conversation ID
            user_message: User's message
            project_id: Project ID
            user_id: User ID
            tenant_id: Tenant ID
            conversation_context: Optional conversation history
            message_id: Optional message ID for HITL request persistence
            forced_skill_name: Optional skill name to force direct execution

        Yields:
            Event dictionaries compatible with existing SSE format:
            - {"type": "plan_mode_triggered", "data": {...}}
            - {"type": "thought", "data": {...}}
            - {"type": "act", "data": {...}}
            - {"type": "observe", "data": {...}}
            - {"type": "complete", "data": {...}}
            - {"type": "error", "data": {...}}
        """
        conversation_context = conversation_context or []
        self._reset_stream_state()
        start_time = time.time()

        logger.info(
            f"[ReActAgent] Starting stream for conversation {conversation_id}, "
            f"user: {user_id}, message: {user_message[:50]}..."
        )

        # Phase 1: Plan mode detection
        async for event in self._stream_detect_plan_mode(user_message, conversation_id):
            yield event

        # Phase 2: Parse forced subagent from system instruction
        forced_subagent_name, processed_user_message = self._stream_parse_forced_subagent(
            user_message
        )

        # Phase 3: Routing decision
        routing_decision, _route_id, _trace_id, routing_metadata, forced_skill_name, route_event = (
            self._stream_decide_route(
                processed_user_message=processed_user_message,
                conversation_context=conversation_context,
                forced_subagent_name=forced_subagent_name,
                forced_skill_name=forced_skill_name,
                plan_mode=plan_mode,
            )
        )
        yield route_event

        # Phase 4b: Filesystem skill loading (lazy, once per agent instance)
        await self._load_filesystem_skills(tenant_id, project_id)

        resolved_agent_id = agent_id or BUILTIN_SISYPHUS_ID
        selected_agent = await self._load_selected_agent(
            agent_id=resolved_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if selected_agent is None:
            logger.warning(
                "[ReActAgent] Falling back to built-in Sisyphus for missing agent %s",
                resolved_agent_id,
            )
            selected_agent = build_builtin_sisyphus_agent(
                tenant_id=tenant_id,
                project_id=project_id,
            )
        await _register_selected_agent_session(
            conversation_id=conversation_id,
            project_id=project_id,
            selected_agent_id=selected_agent.id,
        )
        has_workspace_binding = False
        workspace_runtime_payload = self._workspace_runtime_context(conversation_context)
        runtime_preferred_language = _normalize_preferred_language(
            preferred_language
        ) or _preferred_language_from_payload(workspace_runtime_payload)
        workspace_replan_turn = self._is_workspace_leader_replan_context(workspace_runtime_payload)
        workspace_binding = self._normalize_workspace_binding(
            workspace_runtime_payload.get("workspace_binding")
            if isinstance(workspace_runtime_payload, Mapping)
            else None
        ) or self._workspace_binding_from_text(processed_user_message)
        if project_id and tenant_id and user_id:
            from src.infrastructure.agent.workspace.orchestrator import (
                WorkspaceAutonomyOrchestrator,
            )

            orchestrator = WorkspaceAutonomyOrchestrator()
            has_workspace_binding = workspace_binding is not None
            if orchestrator.should_activate(
                processed_user_message,
                has_workspace_binding=has_workspace_binding,
            ):
                if workspace_binding is not None:
                    workspace_root_task = SimpleNamespace(
                        id=workspace_binding.get("root_goal_task_id")
                        or workspace_binding.get("workspace_task_id")
                        or "",
                        workspace_id=workspace_binding["workspace_id"],
                    )
                else:
                    workspace_root_task = await orchestrator.materialize_goal_candidate(
                        project_id,
                        tenant_id,
                        user_id,
                        leader_agent_id=selected_agent.id,
                        user_query=processed_user_message,
                        preferred_language=runtime_preferred_language,
                    )
            else:
                workspace_root_task = None
        else:
            workspace_root_task = None
        runtime_profile = self._build_runtime_profile(
            tenant_id=tenant_id,
            tenant_agent_config_data=tenant_agent_config_data,
            selected_agent=selected_agent,
            is_workspace_worker_runtime=has_workspace_binding,
        )
        if workspace_replan_turn:
            runtime_profile = self._with_workspace_leader_replan_tool_allowlist(runtime_profile)
        elif has_workspace_binding:
            runtime_profile = self._with_workspace_worker_tool_allowlist(runtime_profile)
        self.config.runtime_hook_overrides = [
            runtime_hook.to_dict()
            for runtime_hook in runtime_profile.tenant_agent_config.runtime_hooks
        ]
        runtime_workspace_manager = self._build_runtime_workspace_manager(selected_agent)

        # Phase 5: Skill matching
        if workspace_root_task is not None and not forced_skill_name:
            self._stream_skill_state = {
                "matched_skill": None,
                "is_forced": False,
                "should_inject_prompt": False,
            }
            logger.info(
                "[ReActAgent] Skipping non-forced skill matching because workspace authority is active "
                "for conversation %s",
                conversation_id,
            )
        else:
            for event in self._stream_match_skill(
                processed_user_message,
                forced_skill_name,
                available_skills=cast("list[SkillProtocol]", runtime_profile.available_skills),
            ):
                yield event
        skill_state = self._stream_skill_state
        matched_skill: Skill | None = cast("Skill | None", skill_state["matched_skill"])
        is_forced: bool = cast(bool, skill_state["is_forced"])
        should_inject_prompt: bool = cast(bool, skill_state["should_inject_prompt"])

        # Phase 5b: Sync skill resources
        if should_inject_prompt and matched_skill:
            await self._stream_sync_skill_resources(matched_skill)

        # Phase 5c: Activate skill-embedded MCP servers
        self._skill_mcp_tools = []
        if matched_skill and matched_skill.metadata:
            mcp_servers_raw = matched_skill.metadata.get("mcp_servers")
            if mcp_servers_raw and isinstance(mcp_servers_raw, list):
                from ..mcp.skill_mcp_manager import SkillMCPConfig

                mcp_configs = [
                    SkillMCPConfig(
                        server_name=cfg["server_name"],
                        command=cfg["command"],
                        args=cfg.get("args", []),
                        env=cfg.get("env", {}),
                        auto_start=cfg.get("auto_start", True),
                    )
                    for cfg in mcp_servers_raw
                    if isinstance(cfg, dict) and "server_name" in cfg and "command" in cfg
                ]
                if mcp_configs:
                    try:
                        self._skill_mcp_manager.register_skill_mcps(matched_skill.name, mcp_configs)
                        mcp_tools = await self._skill_mcp_manager.activate_skill(matched_skill.name)
                        # Convert MCPTool objects to ToolDefinition for injection
                        for mcp_tool in mcp_tools:
                            if not mcp_tool.schema.is_model_visible:
                                continue
                            client = self._skill_mcp_manager.get_active_client(mcp_tool.server_name)

                            async def _make_mcp_exec(
                                _client: Any,
                                _tool_name: str,
                            ) -> Any:
                                async def _exec(**kwargs: Any) -> Any:
                                    if _client is None:
                                        return f"MCP server not available for tool {_tool_name}"
                                    result = await _client.call_tool(_tool_name, kwargs)
                                    if isinstance(result, dict):
                                        return result.get("content", str(result))
                                    return result

                                return _exec

                            td = ToolDefinition(
                                name=mcp_tool.schema.name,
                                description=(
                                    mcp_tool.schema.description
                                    or f"MCP tool: {mcp_tool.schema.name}"
                                ),
                                parameters=(
                                    mcp_tool.schema.input_schema
                                    or {
                                        "type": "object",
                                        "properties": {},
                                    }
                                ),
                                execute=await _make_mcp_exec(client, mcp_tool.schema.name),
                            )
                            self._skill_mcp_tools.append(td)
                        if self._skill_mcp_tools:
                            logger.info(
                                "[ReActAgent] Activated %d MCP tool(s) for skill '%s': %s",
                                len(self._skill_mcp_tools),
                                matched_skill.name,
                                [t.name for t in self._skill_mcp_tools],
                            )
                    except Exception:
                        logger.exception(
                            "[ReActAgent] Failed to activate MCP servers for skill '%s'",
                            matched_skill.name,
                        )

        # Phase 6: Mode/selection context setup
        effective_mode, selection_context = self._stream_resolve_mode(
            plan_mode=plan_mode,
            routing_decision=routing_decision,
            routing_metadata=routing_metadata,
            tenant_id=tenant_id,
            project_id=project_id,
            processed_user_message=processed_user_message,
            conversation_context=conversation_context,
            allow_tools=runtime_profile.allow_tools,
            deny_tools=runtime_profile.deny_tools,
        )

        # Phase 6b: Inject matched skill's declared tools into selection context
        # so the tool selection pipeline can pin them (survive semantic budget + deny lists)
        if matched_skill and matched_skill.tools:
            skill_pinned = list(matched_skill.tools)
            cast(dict[str, Any], selection_context.metadata)["skill_pinned_tools"] = skill_pinned
            logger.info(
                f"[ReActAgent] Skill '{matched_skill.name}' declares tools={skill_pinned}, "
                f"injecting into selection context for pipeline pinning"
            )

        # Phase 7: Memory runtime prompt augmentation
        memory_context, hook_events = await self._apply_before_prompt_build_hook(
            processed_user_message=processed_user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            effective_mode=effective_mode,
            matched_skill=matched_skill if should_inject_prompt else None,
            selected_agent=selected_agent,
        )
        for event in hook_events:
            yield event

        # Phase 7b: Heartbeat check
        heartbeat_prompt: str | None = None
        if self._heartbeat_runner and self._heartbeat_runner.check_due():
            hb_result = await self._heartbeat_runner.run_once()
            if hb_result.should_run:
                heartbeat_prompt = hb_result.prompt
                logger.info("[ReActAgent] Heartbeat due, injecting heartbeat prompt into context")

        # Phase 7c: Selected agent prompt resolution
        primary_agent_prompt = self._build_primary_agent_prompt(
            runtime_profile=runtime_profile,
            selection_context=selection_context,
        )

        # Phase 8: System prompt building
        system_prompt = await self._build_system_prompt(
            processed_user_message,
            conversation_context,
            matched_skill=matched_skill if should_inject_prompt else None,
            subagent=None,
            mode=effective_mode,
            current_step=1,
            project_id=project_id,
            tenant_id=tenant_id,
            force_execution=is_forced,
            memory_context=memory_context,
            selection_context=selection_context,
            heartbeat_prompt=heartbeat_prompt,
            agent_definition_prompt=runtime_profile.agent_definition_prompt,
            primary_agent_prompt=primary_agent_prompt,
            available_skills=runtime_profile.available_skills,
            model_name=(model_override or runtime_profile.effective_model),
            max_steps_override=runtime_profile.effective_max_steps,
            workspace_manager=runtime_workspace_manager,
            selected_agent_name=selected_agent.name,
        )

        # Phase 9: Context building
        async for event in self._stream_build_context(
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            processed_user_message=processed_user_message,
            attachment_metadata=attachment_metadata,
            attachment_content=attachment_content,
            context_summary_data=context_summary_data,
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
        ):
            yield event
        messages = self._stream_messages

        # Phase 10: Tool preparation
        for event in self._stream_prepare_tools(selection_context, is_forced, matched_skill):
            yield event
        tools_to_use = self._filter_workspace_root_tools(
            self._stream_tools_to_use,
            workspace_root_task,
        )

        # Phase 10b: Inject skill-embedded MCP tools
        if self._skill_mcp_tools:
            existing_names = {t.name for t in tools_to_use}
            for mcp_td in self._skill_mcp_tools:
                if mcp_td.name not in existing_names:
                    tools_to_use.append(mcp_td)
            logger.info(
                "[ReActAgent] Injected %d skill MCP tool(s) into tool set",
                len(self._skill_mcp_tools),
            )

        # Phase 11: SubAgent-as-Tool injection
        tools_to_use = self._stream_inject_subagent_tools(
            tools_to_use=tools_to_use,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            workspace_root_task=workspace_root_task,
            leader_agent_id=selected_agent.id,
            actor_user_id=user_id,
        )
        tools_to_use = self._filter_tools_by_name_policy(
            tools_to_use,
            allow_tools=runtime_profile.allow_tools,
            deny_tools=runtime_profile.deny_tools,
        )

        # Phase 12: Processor creation
        config = self._stream_create_processor_config(self.config, selection_context)
        config.model = runtime_profile.effective_model
        config.temperature = runtime_profile.effective_temperature
        config.max_tokens = runtime_profile.effective_max_tokens
        config.max_steps = runtime_profile.effective_max_steps
        config.skill_names = [skill.name for skill in runtime_profile.available_skills]
        config.runtime_context = {
            **dict(config.runtime_context),
            "selected_agent_id": selected_agent.id,
            "selected_agent_name": selected_agent.name,
            "allowed_skills": list(selected_agent.allowed_skills)
            if selected_agent.allowed_skills
            else [],
            "allowed_tools": list(runtime_profile.allow_tools),
            "denied_tools": list(runtime_profile.deny_tools),
            "route_id": selection_context.metadata.get("route_id"),
            "trace_id": selection_context.metadata.get("trace_id"),
        }
        if runtime_preferred_language:
            config.runtime_context[PREFERRED_LANGUAGE] = runtime_preferred_language
        if (
            workspace_root_task is not None
            or workspace_binding is not None
            or isinstance(workspace_runtime_payload, Mapping)
        ):
            from src.infrastructure.agent.workspace.runtime_role_contract import (
                derive_workspace_session_role,
            )

            workspace_session_role = derive_workspace_session_role(
                has_workspace_binding=has_workspace_binding
            )
            if workspace_replan_turn:
                workspace_session_role = WORKSPACE_ROLE_LEADER
            elif isinstance(workspace_runtime_payload, Mapping):
                runtime_role = workspace_runtime_payload.get(WORKSPACE_SESSION_ROLE_KEY)
                if isinstance(runtime_role, str) and runtime_role.strip():
                    workspace_session_role = runtime_role.strip()

            workspace_runtime_context: dict[str, Any] = {
                "task_authority": "workspace",
                WORKSPACE_SESSION_ROLE_KEY: workspace_session_role,
            }
            if runtime_preferred_language:
                workspace_runtime_context[PREFERRED_LANGUAGE] = runtime_preferred_language
            workspace_id_value = getattr(workspace_root_task, "workspace_id", None)
            if not workspace_id_value and workspace_binding is not None:
                workspace_id_value = workspace_binding.get("workspace_id")
            workspace_runtime_context["workspace_id"] = workspace_id_value or project_id

            root_goal_task_id = getattr(workspace_root_task, "id", None)
            if not root_goal_task_id and workspace_binding is not None:
                root_goal_task_id = workspace_binding.get("root_goal_task_id")
            workspace_runtime_context["root_goal_task_id"] = root_goal_task_id or ""
            if isinstance(workspace_runtime_payload, Mapping):
                for key in (WORKSPACE_TURN_TYPE_KEY, WORKSPACE_TOOL_MODE_KEY):
                    value = workspace_runtime_payload.get(key)
                    if isinstance(value, str) and value.strip():
                        workspace_runtime_context[key] = value.strip()
                code_context = workspace_runtime_payload.get("code_context")
                if isinstance(code_context, Mapping):
                    workspace_runtime_context["code_context"] = dict(code_context)
                    sandbox_code_root = code_context.get("sandbox_code_root")
                    if isinstance(sandbox_code_root, str) and sandbox_code_root.strip():
                        workspace_runtime_context["sandbox_code_root"] = sandbox_code_root.strip()
                workspace_runtime_context.update(
                    _workspace_runtime_forwarded_fields(workspace_runtime_payload)
                )
            if workspace_binding is not None:
                for key in ("workspace_task_id", "attempt_id", "leader_agent_id"):
                    value = workspace_binding.get(key)
                    if value:
                        workspace_runtime_context[key] = value
            config.runtime_context = {
                **dict(config.runtime_context),
                **workspace_runtime_context,
            }
        # Set session_id for announce message polling (P0.5)
        config.session_id = conversation_id
        # Pass forced skill context to processor for loop reinforcement (Fix 4)
        if is_forced and matched_skill:
            config.forced_skill_name = matched_skill.name
            config.forced_skill_tools = list(matched_skill.tools) if matched_skill.tools else None

        # Apply per-request model override before LLM parameter overrides.
        normalized_model_override = (model_override or "").strip() or None
        if normalized_model_override:
            from src.infrastructure.llm.model_catalog import get_model_catalog_service
            from src.infrastructure.llm.provider_factory import get_ai_service_factory
            from src.infrastructure.llm.reasoning_config import build_reasoning_config

            catalog = get_model_catalog_service()
            override_meta = catalog.get_model_fuzzy(normalized_model_override)
            current_meta = catalog.get_model_fuzzy(config.model)
            current_provider = _normalize_model_provider(
                current_meta.provider if current_meta is not None else None
            )
            override_provider = _normalize_model_provider(
                override_meta.provider if override_meta is not None else None
            )

            if current_provider is None:
                current_provider = _infer_provider_from_model_name(config.model)
            if override_provider is None:
                override_provider = _infer_provider_from_model_name(normalized_model_override)

            resolved_provider_config: Any | None = None
            resolved_provider: str | None = None
            if tenant_id:
                from src.domain.llm_providers.models import NoActiveProviderError, OperationType

                factory = get_ai_service_factory()
                try:
                    resolved_provider_config = await factory.resolve_provider(
                        tenant_id=tenant_id,
                        operation_type=OperationType.LLM,
                        model_id=normalized_model_override,
                    )
                except NoActiveProviderError:
                    logger.warning(
                        "[ReActAgent] Unable to resolve provider for model override '%s' (tenant=%s)",
                        normalized_model_override,
                        tenant_id,
                    )

                if resolved_provider_config is not None:
                    provider_type_raw = getattr(
                        resolved_provider_config.provider_type,
                        "value",
                        resolved_provider_config.provider_type,
                    )
                    resolved_provider = _normalize_model_provider(str(provider_type_raw))

            if tenant_id:
                # With tenant-scoped providers, fail closed unless resolution succeeds.
                should_apply_override = (
                    resolved_provider_config is not None
                    and resolved_provider_config.is_model_allowed(normalized_model_override)
                )
            elif resolved_provider_config is not None:
                should_apply_override = resolved_provider_config.is_model_allowed(
                    normalized_model_override
                )
            else:
                should_apply_override = override_meta is not None
                if should_apply_override:
                    if current_provider is None or override_provider is None:
                        should_apply_override = False
                    else:
                        should_apply_override = current_provider == override_provider

            if not should_apply_override:
                logger.warning(
                    "[ReActAgent] Ignoring invalid or cross-provider model override '%s' "
                    "(current model: '%s', current provider: '%s', override provider: '%s')",
                    normalized_model_override,
                    config.model,
                    current_provider,
                    override_provider,
                )
                yield {
                    "type": "model_override_rejected",
                    "data": {
                        "model": normalized_model_override,
                        "reason": (
                            f"Cross-provider switch not allowed: override provider "
                            f"'{override_provider}' != current '{current_provider}'"
                        ),
                        "current_model": config.model,
                        "current_provider": current_provider,
                    },
                }
            else:
                if resolved_provider_config is not None:
                    current_client_provider = getattr(config.llm_client, "provider_config", None)
                    current_provider_config_id = getattr(current_client_provider, "id", None)
                    resolved_provider_config_id = getattr(resolved_provider_config, "id", None)
                    should_refresh_llm_client = (
                        current_provider_config_id is None
                        or resolved_provider_config_id is None
                        or current_provider_config_id != resolved_provider_config_id
                    )
                    if should_refresh_llm_client:
                        resolved_provider_label = resolved_provider or _normalize_model_provider(
                            str(
                                getattr(
                                    resolved_provider_config.provider_type,
                                    "value",
                                    resolved_provider_config.provider_type,
                                )
                            )
                        )
                        config.base_url = resolved_provider_config.base_url
                        config.llm_client = get_ai_service_factory().create_llm_client(
                            resolved_provider_config
                        )
                        logger.info(
                            "[ReActAgent] Switched runtime provider for model override '%s': %s -> %s",
                            normalized_model_override,
                            current_provider,
                            resolved_provider_label,
                        )

                config.model = normalized_model_override
                provider_options = dict(config.provider_options)
                for key in (
                    "reasoning_effort",
                    "thinking",
                    "reasoning_split",
                    "__omit_temperature",
                    "__use_max_completion_tokens",
                    "__override_max_tokens",
                ):
                    provider_options.pop(key, None)

                reasoning_cfg = build_reasoning_config(normalized_model_override)
                if reasoning_cfg:
                    provider_options.update(reasoning_cfg.provider_options)
                    provider_options["__omit_temperature"] = reasoning_cfg.omit_temperature
                    provider_options["__use_max_completion_tokens"] = (
                        reasoning_cfg.use_max_completion_tokens
                    )
                    provider_options["__override_max_tokens"] = reasoning_cfg.override_max_tokens
                config.provider_options = provider_options

        # Apply per-request LLM overrides (F1.4)
        if llm_overrides:

            def _to_float(value: Any) -> float | None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            def _to_int(value: Any) -> int | None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            if "temperature" in llm_overrides:
                parsed = _to_float(llm_overrides["temperature"])
                if parsed is not None:
                    config.temperature = parsed
            if "max_tokens" in llm_overrides:
                parsed = _to_int(llm_overrides["max_tokens"])
                if parsed is not None:
                    config.max_tokens = parsed
            if "top_p" in llm_overrides:
                parsed = _to_float(llm_overrides["top_p"])
                if parsed is not None:
                    config.provider_options["top_p"] = parsed
            if "frequency_penalty" in llm_overrides:
                parsed = _to_float(llm_overrides["frequency_penalty"])
                if parsed is not None:
                    config.provider_options["frequency_penalty"] = parsed
            if "presence_penalty" in llm_overrides:
                parsed = _to_float(llm_overrides["presence_penalty"])
                if parsed is not None:
                    config.provider_options["presence_penalty"] = parsed

        if workspace_replan_turn:
            config.provider_options["tool_choice"] = "required"
        processor = self._processor_factory.create_for_main(
            config=config,
            tools=tools_to_use,
        )

        # Inject lane JIT guidance (friction signals + matched playbooks +
        # entry-gate checks) for workspace-scoped sessions. No-op for
        # non-workspace chats. Failures are logged and swallowed so this
        # cannot break the agent loop.
        await self._inject_lane_jit_guidance(
            processor=processor,
            project_id=project_id,
            workspace_task=workspace_root_task,
        )

        langfuse_context = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "message_id": message_id,
            "sandbox_id": self._extract_sandbox_id_from_tools(),
            "agent_name": selected_agent.name,
        }

        # Phase 13: Event processing
        async for event in self._stream_process_events(
            processor=processor,
            messages=messages,
            langfuse_context=langfuse_context,
            abort_signal=abort_signal,
            matched_skill=matched_skill,
            agent_id=agent_id,
        ):
            yield event

        # Phase 13b: Heartbeat reply processing
        if self._heartbeat_runner and heartbeat_prompt:
            hb_reply = self._heartbeat_runner.process_reply(self._stream_final_content)
            if hb_reply.should_suppress:
                logger.debug("[ReActAgent] Heartbeat reply acknowledged (HEARTBEAT_OK)")
            elif hb_reply.did_strip:
                self._stream_final_content = hb_reply.cleaned_text

        # Phase 14: Post-processing
        # Calculate execution time before post-process (post-process is
        # lightweight — just hook delivery — so this is accurate enough).
        execution_time_ms = int((time.time() - start_time) * 1000)
        # Count tool calls from conversation context for skill evolution capture.
        tool_call_count = sum(
            1 for msg in conversation_context if msg.get("role") in ("tool", "function")
        )
        async for event in self._stream_post_process(
            processed_user_message=processed_user_message,
            final_content=self._stream_final_content,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            matched_skill=matched_skill,
            success=self._stream_success,
            execution_time_ms=execution_time_ms,
            tool_call_count=tool_call_count,
            llm_client_override=config.llm_client if normalized_model_override else None,
        ):
            yield event

        # Finally: Record execution statistics
        end_time = time.time()
        execution_time_ms = int((end_time - start_time) * 1000)
        logger.debug(f"[ReActAgent] Stream finished in {execution_time_ms}ms")
        self._stream_record_skill_usage(matched_skill, self._stream_success)

        # Cleanup: Deactivate skill MCP servers
        if matched_skill and self._skill_mcp_manager.active_skills:
            try:
                await self._skill_mcp_manager.deactivate_skill(matched_skill.name)
            except Exception:
                logger.exception(
                    "[ReActAgent] Failed to deactivate MCP servers for skill '%s'",
                    matched_skill.name,
                )
        self._skill_mcp_tools = []

    async def astream_multi_level(
        self: _StreamAgent,
        conversation_id: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        user_query: str,
        conversation_context: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream with multi-level thinking (compatibility wrapper for ``stream``)."""
        async for event in self.stream(
            conversation_id=conversation_id,
            user_message=user_query,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_context=conversation_context,
        ):
            yield event
