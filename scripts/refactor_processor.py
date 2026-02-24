"""Refactor processor.py to fix ruff complexity violations.

Applies transformations to 6 functions:
1. process() - 27 branches, 83 stmts -> extract helpers
2. _evaluate_llm_goal() - 13 branches -> extract helpers
3. _extract_goal_json() - 15 branches -> extract _find_json_in_text
4. _process_step() - 28 branches, 122 stmts -> extract helpers
5. _execute_tool() - 13 returns, 63 branches, 236 stmts -> extract helpers
6. _process_tool_artifacts() - 9 returns, 23 branches, 120 stmts -> extract helpers
"""

import sys
from pathlib import Path


def main() -> None:
    fpath = Path("src/infrastructure/agent/processor/processor.py")
    lines = fpath.read_text().splitlines(keepends=True)

    # Build a list of (start_0idx, end_0idx_exclusive, replacement_lines) tuples.
    # Apply bottom-up so indices don't shift.
    replacements: list[tuple[int, int, list[str]]] = []

    # ---------- 1. process() (lines 497-673, 1-indexed) ----------
    replacements.append((496, 673, PROCESS_REPLACEMENT))

    # ---------- 2. _evaluate_llm_goal (lines 776-842, 1-indexed) ----------
    replacements.append((775, 842, EVALUATE_LLM_GOAL_REPLACEMENT))

    # ---------- 3. _extract_goal_json (lines 947-994, 1-indexed) ----------
    replacements.append((946, 994, EXTRACT_GOAL_JSON_REPLACEMENT))

    # ---------- 4. _process_step (lines 1090-1412, 1-indexed) ----------
    replacements.append((1089, 1412, PROCESS_STEP_REPLACEMENT))

    # ---------- 5. _execute_tool (lines 1414-2050, 1-indexed) ----------
    replacements.append((1413, 2050, EXECUTE_TOOL_REPLACEMENT))

    # ---------- 6. _process_tool_artifacts (lines 2079-2506, 1-indexed) ----------
    replacements.append((2078, 2506, PROCESS_TOOL_ARTIFACTS_REPLACEMENT))

    # Sort by start index descending so we can apply bottom-up
    replacements.sort(key=lambda x: x[0], reverse=True)

    for start, end, repl in replacements:
        lines[start:end] = [line + "\n" for line in repl]

    fpath.write_text("".join(lines))
    print(f"Wrote {len(lines)} lines")


# ============================================================
# Replacement blocks (each is a list of strings WITHOUT newlines)
# ============================================================

PROCESS_REPLACEMENT = """\
    async def process(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        abort_signal: asyncio.Event | None = None,
        langfuse_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"
        Process a conversation turn.

        Runs the ReAct loop:
        1. Call LLM with messages
        2. Process response (text, reasoning, tool calls)
        3. Execute tool calls if any
        4. Continue until complete or blocked

        Args:
            session_id: Session identifier
            messages: Conversation messages in OpenAI format
            abort_signal: Optional abort signal
            langfuse_context: Optional context for Langfuse tracing containing:
                - conversation_id: Unique conversation identifier
                - user_id: User identifier
                - tenant_id: Tenant identifier for multi-tenant isolation
                - project_id: Project identifier
                - extra: Additional metadata dict

        Yields:
            AgentDomainEvent objects and dict passthrough events for real-time streaming
        \"\"\"
        self._abort_event = abort_signal or asyncio.Event()
        self._step_count = 0
        self._no_progress_steps = 0
        self._langfuse_context = langfuse_context  # Store for use in _process_step

        # Emit start event
        yield AgentStartEvent()
        self._state = ProcessorState.THINKING

        try:
            result = ProcessorResult.CONTINUE

            while result == ProcessorResult.CONTINUE:
                # Check abort and step limit
                error_event = self._check_abort_and_step_limit()
                if error_event:
                    yield error_event
                    self._state = ProcessorState.ERROR
                    return

                # Process one step and classify events
                had_tool_calls = False
                async for event in self._process_step(session_id, messages):
                    yield event
                    result, had_tool_calls = self._classify_step_event(
                        event, result, had_tool_calls
                    )
                    if result in (ProcessorResult.STOP, ProcessorResult.COMPACT):
                        break

                # If no stop/compact, determine result from tool calls
                if result == ProcessorResult.CONTINUE:
                    if had_tool_calls:
                        self._no_progress_steps = 0
                    else:
                        result, events = await self._evaluate_no_tool_result(
                            session_id, messages
                        )
                        for ev in events:
                            yield ev

                # Append tool results to messages for next iteration
                if result == ProcessorResult.CONTINUE:
                    self._append_tool_results_to_messages(messages)

            # Emit final events
            async for ev in self._emit_final_events(result, session_id, messages):
                yield ev

        except Exception as e:
            logger.error(f"Processor error: {e}", exc_info=True)
            yield AgentErrorEvent(message=str(e), code=type(e).__name__)
            self._state = ProcessorState.ERROR

    def _check_abort_and_step_limit(self) -> AgentErrorEvent | None:
        \"\"\"Check abort signal and step limit. Returns error event or None.\"\"\"
        if self._abort_event.is_set():
            return AgentErrorEvent(message="Processing aborted", code="ABORTED")
        self._step_count += 1
        if self._step_count > self.config.max_steps:
            return AgentErrorEvent(
                message=f"Maximum steps ({self.config.max_steps}) exceeded",
                code="MAX_STEPS_EXCEEDED",
            )
        return None

    def _classify_step_event(
        self,
        event: ProcessorEvent,
        current_result: ProcessorResult,
        had_tool_calls: bool,
    ) -> tuple[ProcessorResult, bool]:
        \"\"\"Classify a step event and update result/tool_calls state.\"\"\"
        event_type_raw = (
            event.get("type")
            if isinstance(event, dict)
            else getattr(event, "event_type", None)
        )
        event_type = (
            event_type_raw.value
            if isinstance(event_type_raw, AgentEventType)
            else event_type_raw
        )
        if event_type == AgentEventType.ERROR.value:
            return ProcessorResult.STOP, had_tool_calls
        if event_type == AgentEventType.ACT.value:
            return current_result, True
        if event_type == AgentEventType.COMPACT_NEEDED.value:
            return ProcessorResult.COMPACT, had_tool_calls
        return current_result, had_tool_calls

    async def _evaluate_no_tool_result(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> tuple[ProcessorResult, list[ProcessorEvent]]:
        \"\"\"Evaluate goal completion when no tool calls were made.\"\"\"
        events: list[ProcessorEvent] = []
        goal_check = await self._evaluate_goal_completion(session_id, messages)

        if goal_check.achieved:
            self._no_progress_steps = 0
            events.append(AgentStatusEvent(status=f"goal_achieved:{goal_check.source}"))
            return ProcessorResult.COMPLETE, events

        if self._is_conversational_response():
            self._no_progress_steps = 0
            events.append(AgentStatusEvent(status="goal_achieved:conversational_response"))
            return ProcessorResult.COMPLETE, events

        if goal_check.should_stop:
            events.append(
                AgentErrorEvent(
                    message=goal_check.reason or "Goal cannot be completed",
                    code="GOAL_NOT_ACHIEVED",
                )
            )
            self._state = ProcessorState.ERROR
            return ProcessorResult.STOP, events

        return self._handle_no_progress(goal_check, events)

    def _handle_no_progress(
        self,
        goal_check: Any,
        events: list[ProcessorEvent],
    ) -> tuple[ProcessorResult, list[ProcessorEvent]]:
        \"\"\"Handle no-progress path: increment counter and check limits.\"\"\"
        self._no_progress_steps += 1
        events.append(AgentStatusEvent(status=f"goal_pending:{goal_check.source}"))
        if self._no_progress_steps > 1:
            events.append(AgentStatusEvent(status="planning_recheck"))
        if self._no_progress_steps >= self.config.max_no_progress_steps:
            events.append(
                AgentErrorEvent(
                    message=(
                        "Goal not achieved after "
                        f"{self._no_progress_steps} no-progress turns. "
                        f"{goal_check.reason or 'Replan required.'}"
                    ),
                    code="GOAL_NOT_ACHIEVED",
                )
            )
            self._state = ProcessorState.ERROR
            return ProcessorResult.STOP, events
        return ProcessorResult.CONTINUE, events

    def _append_tool_results_to_messages(self, messages: list[dict[str, Any]]) -> None:
        \"\"\"Append assistant message and tool results to the message list.\"\"\"
        if not self._current_message:
            return
        messages.append(self._current_message.to_llm_format())
        for part in self._current_message.get_tool_parts():
            if part.status == ToolState.COMPLETED:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": part.call_id,
                        "content": part.output or "",
                    }
                )
            elif part.status == ToolState.ERROR:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": part.call_id,
                        "content": f"Error: {part.error}",
                    }
                )

    async def _emit_final_events(
        self,
        result: ProcessorResult,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Emit completion or compact events based on final result.\"\"\"
        if result == ProcessorResult.COMPLETE:
            suggestions_event = await self._generate_suggestions(messages)
            if suggestions_event:
                yield suggestions_event
            trace_url = self._build_trace_url(session_id)
            yield AgentCompleteEvent(trace_url=trace_url)
            self._state = ProcessorState.COMPLETED
        elif result == ProcessorResult.COMPACT:
            yield AgentStatusEvent(status="compact_needed")

    def _build_trace_url(self, session_id: str) -> str | None:
        \"\"\"Build Langfuse trace URL if context is available.\"\"\"
        if not self._langfuse_context:
            return None
        from src.configuration.config import get_settings

        settings = get_settings()
        if not (settings.langfuse_enabled and settings.langfuse_host):
            return None
        trace_id = self._langfuse_context.get("conversation_id", session_id)
        return f"{settings.langfuse_host}/trace/{trace_id}\"""".split("\n")


EVALUATE_LLM_GOAL_REPLACEMENT = """\
    async def _evaluate_llm_goal(self, messages: list[dict[str, Any]]) -> GoalCheckResult:
        \"\"\"Evaluate completion using explicit LLM self-check in no-task mode.\"\"\"
        fallback = self._evaluate_goal_from_latest_text()
        if self._llm_client is None:
            return fallback

        context_summary = self._build_goal_check_context(messages)
        if not context_summary:
            return fallback

        try:
            response = await self._llm_client.generate(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict completion checker. "
                            "Return ONLY JSON object: "
                            '{"goal_achieved": boolean, "reason": string}. '
                            "Use goal_achieved=true only when user objective is fully satisfied."
                        ),
                    },
                    {"role": "user", "content": context_summary},
                ],
                temperature=0.0,
                max_tokens=120,
            )
        except Exception as exc:
            logger.warning(f"[Processor] LLM goal self-check failed: {exc}")
            return fallback

        content = self._extract_llm_response_content(response)
        parsed = self._extract_goal_json(content)
        if parsed is None:
            parsed = self._extract_goal_from_plain_text(content)
        if parsed is None:
            logger.debug(
                "[Processor] Goal self-check payload not parseable, using fallback: %s",
                content[:200],
            )
            return fallback

        achieved = self._coerce_goal_achieved_bool(parsed.get("goal_achieved"))
        if achieved is None:
            logger.debug("[Processor] Goal self-check missing boolean goal_achieved")
            return fallback

        reason = str(parsed.get("reason", "")).strip()
        return GoalCheckResult(
            achieved=achieved,
            reason=reason or ("Goal achieved" if achieved else "Goal not achieved"),
            source="llm_self_check",
        )

    @staticmethod
    def _extract_llm_response_content(response: Any) -> str:
        \"\"\"Extract string content from an LLM response.\"\"\"
        if isinstance(response, dict):
            return str(response.get("content", "") or "")
        if isinstance(response, str):
            return response
        return str(response)

    @staticmethod
    def _coerce_goal_achieved_bool(value: Any) -> bool | None:
        \"\"\"Coerce a goal_achieved value to bool, returning None if not parseable.\"\"\"
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        return None""".split("\n")


EXTRACT_GOAL_JSON_REPLACEMENT = """\
    def _extract_goal_json(self, text: str) -> dict[str, Any] | None:
        \"\"\"Extract goal-check JSON object from model text.\"\"\"
        stripped = text.strip()
        if not stripped:
            return None

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        return self._find_json_in_text(stripped)

    @staticmethod
    def _find_json_in_text(text: str) -> dict[str, Any] | None:
        \"\"\"Scan text for a valid JSON object using brace-depth tracking.\"\"\"
        start_idx = text.find("{")
        while start_idx >= 0:
            depth = 0
            in_string = False
            escape_next = False
            for index in range(start_idx, len(text)):
                char = text[index]

                if in_string:
                    if escape_next:
                        escape_next = False
                    elif char == "\\\\":
                        escape_next = True
                    elif char == '"':
                        in_string = False
                    continue

                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start_idx : index + 1]
                        try:
                            parsed = json.loads(candidate)
                        except json.JSONDecodeError:
                            break
                        if isinstance(parsed, dict):
                            return parsed
                        break
            start_idx = text.find("{", start_idx + 1)

        return None""".split("\n")


# For _process_step, we need to find the exact line range. Let me handle it.
# Lines 1090-1412 (1-indexed) in the original file.

PROCESS_STEP_REPLACEMENT = """\
    async def _process_step(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"
        Process a single step in the ReAct loop.

        Args:
            session_id: Session identifier
            messages: Current messages

        Yields:
            AgentDomainEvent objects and dict passthrough events
        \"\"\"
        logger.debug(f"[Processor] _process_step: session={session_id}, step={self._step_count}")

        # Create new assistant message
        self._current_message = Message(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
        )

        # Reset pending tool calls
        self._pending_tool_calls = {}
        self._pending_tool_args = {}

        # Prepare tools for LLM
        tools_for_llm = [t.to_openai_format() for t in self.tools.values()]

        # Create stream config
        stream_config = StreamConfig(
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            tools=tools_for_llm if tools_for_llm else None,
        )

        # Create LLM stream with optional client (provides circuit breaker + rate limiter)
        llm_stream = LLMStream(stream_config, llm_client=self._llm_client)

        # Track state for this step
        text_buffer = ""
        reasoning_buffer = ""
        tool_calls_completed = []
        step_tokens = TokenUsage()
        step_cost = 0.0
        finish_reason = "stop"

        # Process LLM stream with retry
        attempt = 0
        while True:
            try:
                step_langfuse_context = self._build_step_langfuse_context()

                logger.debug(f"[Processor] Calling llm_stream.generate(), step={self._step_count}")
                async for event in llm_stream.generate(
                    messages, langfuse_context=step_langfuse_context
                ):
                    # Check abort
                    if self._abort_event and self._abort_event.is_set():
                        raise asyncio.CancelledError("Aborted")

                    # Dispatch stream event to handler
                    async for proc_event in self._handle_stream_event(
                        event, text_buffer, reasoning_buffer, tool_calls_completed,
                        step_tokens, session_id,
                    ):
                        yield proc_event

                    # Update local buffers from stream event
                    text_buffer, reasoning_buffer, step_tokens, step_cost, finish_reason = (
                        self._update_step_buffers(
                            event, text_buffer, reasoning_buffer,
                            step_tokens, step_cost, finish_reason,
                        )
                    )

                # Step completed successfully
                break

            except Exception as e:
                # Check if retryable
                if self.retry_policy.is_retryable(e) and attempt < self.config.max_attempts:
                    attempt += 1
                    delay_ms = self.retry_policy.calculate_delay(attempt, e)

                    self._state = ProcessorState.RETRYING
                    yield AgentRetryEvent(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        message=str(e),
                    )

                    # Wait before retry
                    await asyncio.sleep(delay_ms / 1000)
                    continue
                else:
                    # Not retryable or max retries exceeded
                    raise

        # Finalize step
        self._finalize_step(step_tokens, step_cost, finish_reason)

        # Emit final context status
        yield self._build_final_context_status(step_tokens, messages)

    def _build_step_langfuse_context(self) -> dict[str, Any] | None:
        \"\"\"Build step-specific langfuse context.\"\"\"
        if not self._langfuse_context:
            return None
        return {
            **self._langfuse_context,
            "extra": {
                **self._langfuse_context.get("extra", {}),
                "step_number": self._step_count,
                "model": self.config.model,
            },
        }

    async def _handle_stream_event(
        self,
        event: Any,
        text_buffer: str,
        reasoning_buffer: str,
        tool_calls_completed: list[str],
        step_tokens: TokenUsage,
        session_id: str,
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Handle a single stream event and yield processor events.\"\"\"
        if event.type == StreamEventType.TEXT_START:
            yield AgentTextStartEvent()

        elif event.type == StreamEventType.TEXT_DELTA:
            delta = event.data.get("delta", "")
            yield AgentTextDeltaEvent(delta=delta)

        elif event.type == StreamEventType.TEXT_END:
            full_text = event.data.get("full_text", text_buffer)
            logger.debug(
                f"[Processor] TEXT_END: len={len(full_text) if full_text else 0}"
            )
            self._current_message.add_text(full_text)
            yield AgentTextEndEvent(full_text=full_text)

        elif event.type == StreamEventType.REASONING_START:
            pass

        elif event.type == StreamEventType.REASONING_DELTA:
            delta = event.data.get("delta", "")
            yield AgentThoughtDeltaEvent(delta=delta)

        elif event.type == StreamEventType.REASONING_END:
            full_reasoning = event.data.get("full_text", reasoning_buffer)
            self._current_message.add_reasoning(full_reasoning)
            yield AgentThoughtEvent(content=full_reasoning, thought_level="reasoning")

        elif event.type == StreamEventType.TOOL_CALL_START:
            yield from self._handle_tool_call_start(event)

        elif event.type == StreamEventType.TOOL_CALL_DELTA:
            yield from self._handle_tool_call_delta(event)

        elif event.type == StreamEventType.TOOL_CALL_END:
            async for ev in self._handle_tool_call_end(event, tool_calls_completed, session_id):
                yield ev

        elif event.type == StreamEventType.USAGE:
            async for ev in self._handle_usage_event(event):
                yield ev

        elif event.type == StreamEventType.FINISH:
            pass  # handled in _update_step_buffers

        elif event.type == StreamEventType.ERROR:
            error_msg = event.data.get("message", "Unknown error")
            raise Exception(error_msg)

    def _handle_tool_call_start(self, event: Any) -> list[ProcessorEvent]:
        \"\"\"Handle TOOL_CALL_START stream event.\"\"\"
        call_id = event.data.get("call_id", "")
        tool_name = event.data.get("name", "")

        tool_part = self._current_message.add_tool_call(
            call_id=call_id,
            tool=tool_name,
            input={},
        )
        self._pending_tool_calls[call_id] = tool_part
        self._pending_tool_args[call_id] = ""

        return [
            AgentActDeltaEvent(
                tool_name=tool_name,
                call_id=call_id,
                arguments_fragment="",
                accumulated_arguments="",
            )
        ]

    def _handle_tool_call_delta(self, event: Any) -> list[ProcessorEvent]:
        \"\"\"Handle TOOL_CALL_DELTA stream event.\"\"\"
        call_id = event.data.get("call_id", "")
        args_delta = event.data.get("arguments_delta", "")
        if call_id in self._pending_tool_calls and args_delta:
            self._pending_tool_args[call_id] = (
                self._pending_tool_args.get(call_id, "") + args_delta
            )
            tool_part = self._pending_tool_calls[call_id]
            return [
                AgentActDeltaEvent(
                    tool_name=tool_part.tool or "",
                    call_id=call_id,
                    arguments_fragment=args_delta,
                    accumulated_arguments=self._pending_tool_args[call_id],
                )
            ]
        return []

    async def _handle_tool_call_end(
        self,
        event: Any,
        tool_calls_completed: list[str],
        session_id: str,
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Handle TOOL_CALL_END stream event with validation and execution.\"\"\"
        call_id = event.data.get("call_id", "")
        tool_name = event.data.get("name", "")
        arguments = event.data.get("arguments", {})

        # Validate tool call
        validation_error = self._validate_tool_call(tool_name, arguments, call_id)
        if validation_error:
            yield validation_error
            return

        # Update tool part
        if call_id in self._pending_tool_calls:
            tool_part = self._pending_tool_calls[call_id]
            tool_part.input = arguments
            tool_part.status = ToolState.RUNNING
            tool_part.start_time = time.time()
            tool_part.tool_execution_id = f"exec_{uuid.uuid4().hex[:12]}"

            yield AgentActEvent(
                tool_name=tool_name,
                tool_input=arguments,
                call_id=call_id,
                status="running",
                tool_execution_id=tool_part.tool_execution_id,
            )

            # Execute tool
            async for tool_event in self._execute_tool(
                session_id, call_id, tool_name, arguments
            ):
                yield tool_event

            tool_calls_completed.append(call_id)

    def _validate_tool_call(
        self, tool_name: str, arguments: dict[str, Any], call_id: str
    ) -> AgentErrorEvent | None:
        \"\"\"Validate tool call parameters. Returns error event or None.\"\"\"
        try:
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise ValueError(f"Invalid tool_name: {tool_name!r}")
            if not isinstance(arguments, dict):
                raise ValueError(
                    f"Invalid tool_input type: {type(arguments).__name__}, expected dict"
                )
            if call_id and not isinstance(call_id, str):
                raise ValueError(f"Invalid call_id type: {type(call_id).__name__}")
            _test_event = AgentActEvent(
                tool_name=tool_name,
                tool_input=arguments,
                call_id=call_id,
                status="running",
            )
            del _test_event
        except (ValueError, TypeError) as ve:
            logger.error(
                f"[Processor] Early validation failed for tool call: "
                f"tool_name={tool_name!r}, arguments={arguments!r}, error={ve}"
            )
            return AgentErrorEvent(
                message=f"Tool call validation failed: {ve}",
                code="VALIDATION_ERROR",
            )
        return None

    async def _handle_usage_event(self, event: Any) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Handle USAGE stream event: cost calculation and context status.\"\"\"
        step_tokens = TokenUsage(
            input=event.data.get("input_tokens", 0),
            output=event.data.get("output_tokens", 0),
            reasoning=event.data.get("reasoning_tokens", 0),
            cache_read=event.data.get("cache_read_tokens", 0),
            cache_write=event.data.get("cache_write_tokens", 0),
        )

        cost_result = self.cost_tracker.calculate(
            usage={
                "input_tokens": step_tokens.input,
                "output_tokens": step_tokens.output,
                "reasoning_tokens": step_tokens.reasoning,
                "cache_read_tokens": step_tokens.cache_read,
                "cache_write_tokens": step_tokens.cache_write,
            },
            model_name=self.config.model,
        )
        step_cost = float(cost_result.cost)

        yield AgentCostUpdateEvent(
            cost=step_cost,
            tokens={
                "input": step_tokens.input,
                "output": step_tokens.output,
                "reasoning": step_tokens.reasoning,
            },
        )

        # Emit context status
        context_limit = self.config.context_limit
        current_input = step_tokens.input
        occupancy = (current_input / context_limit * 100) if context_limit > 0 else 0
        yield AgentContextStatusEvent(
            current_tokens=current_input,
            token_budget=context_limit,
            occupancy_pct=round(occupancy, 1),
            compression_level="none",
        )

        # Check for compaction need
        if self.cost_tracker.needs_compaction(step_tokens):
            yield AgentCompactNeededEvent()

    def _update_step_buffers(
        self,
        event: Any,
        text_buffer: str,
        reasoning_buffer: str,
        step_tokens: TokenUsage,
        step_cost: float,
        finish_reason: str,
    ) -> tuple[str, str, TokenUsage, float, str]:
        \"\"\"Update local step buffers from stream event. Returns updated values.\"\"\"
        if event.type == StreamEventType.TEXT_DELTA:
            text_buffer += event.data.get("delta", "")
        elif event.type == StreamEventType.REASONING_DELTA:
            reasoning_buffer += event.data.get("delta", "")
        elif event.type == StreamEventType.USAGE:
            step_tokens = TokenUsage(
                input=event.data.get("input_tokens", 0),
                output=event.data.get("output_tokens", 0),
                reasoning=event.data.get("reasoning_tokens", 0),
                cache_read=event.data.get("cache_read_tokens", 0),
                cache_write=event.data.get("cache_write_tokens", 0),
            )
            cost_result = self.cost_tracker.calculate(
                usage={
                    "input_tokens": step_tokens.input,
                    "output_tokens": step_tokens.output,
                    "reasoning_tokens": step_tokens.reasoning,
                    "cache_read_tokens": step_tokens.cache_read,
                    "cache_write_tokens": step_tokens.cache_write,
                },
                model_name=self.config.model,
            )
            step_cost = float(cost_result.cost)
        elif event.type == StreamEventType.FINISH:
            finish_reason = event.data.get("reason", "stop")
        return text_buffer, reasoning_buffer, step_tokens, step_cost, finish_reason

    def _finalize_step(
        self, step_tokens: TokenUsage, step_cost: float, finish_reason: str
    ) -> None:
        \"\"\"Update message tokens and cost after step completes.\"\"\"
        self._current_message.tokens = {
            "input": step_tokens.input,
            "output": step_tokens.output,
            "reasoning": step_tokens.reasoning,
        }
        self._current_message.cost = step_cost
        self._current_message.finish_reason = finish_reason
        self._current_message.completed_at = time.time()

    def _build_final_context_status(
        self, step_tokens: TokenUsage, messages: list[dict[str, Any]]
    ) -> AgentContextStatusEvent:
        \"\"\"Build final context status event after step completes.\"\"\"
        context_limit = self.config.context_limit
        current_input = step_tokens.input
        if current_input == 0:
            total_chars = sum(len(str(m.get("content", ""))) for m in messages)
            current_input = total_chars // 4
        occupancy = (current_input / context_limit * 100) if context_limit > 0 else 0
        return AgentContextStatusEvent(
            current_tokens=current_input,
            token_budget=context_limit,
            occupancy_pct=round(occupancy, 1),
            compression_level="none",
        )""".split("\n")


EXECUTE_TOOL_REPLACEMENT = """\
    async def _execute_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"
        Execute a tool call with permission checking and doom loop detection.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Yields:
            AgentDomainEvent objects and dict passthrough events for tool execution
        \"\"\"
        tool_part = self._pending_tool_calls.get(call_id)
        if not tool_part:
            logger.error(
                f"[Processor] Tool call not found in pending: call_id={call_id}, tool={tool_name}"
            )
            yield AgentObserveEvent(
                tool_name=tool_name,
                error=f"Tool call not found: {call_id}",
                call_id=call_id,
                tool_execution_id=None,
            )
            return

        # Get tool definition
        tool_def = self.tools.get(tool_name)
        if not tool_def:
            self._set_tool_error(tool_part, f"Unknown tool: {tool_name}")
            yield AgentObserveEvent(
                tool_name=tool_name,
                error=f"Unknown tool: {tool_name}",
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )
            return

        # Check doom loop
        doom_result = await self._check_doom_loop(session_id, tool_name, arguments, tool_part)
        if doom_result is not None:
            for ev in doom_result:
                yield ev
            return

        # Record tool call for doom loop detection
        self.doom_loop_detector.record(tool_name, arguments)

        # Handle HITL tools
        hitl_result = self._dispatch_hitl_tool(session_id, call_id, tool_name, arguments, tool_part)
        if hitl_result is not None:
            async for ev in hitl_result:
                yield ev
            return

        # Check tool permission
        perm_result = await self._check_tool_permission(
            session_id, call_id, tool_name, arguments, tool_def, tool_part
        )
        if perm_result is not None:
            for ev in perm_result:
                yield ev
            return

        # Execute tool
        self._state = ProcessorState.ACTING

        try:
            # Handle truncated/raw arguments
            arguments, arg_error = self._resolve_tool_arguments(tool_name, arguments, tool_part)
            if arg_error:
                yield arg_error
                return

            # Inject session_id for tools that need conversation context
            if tool_name in ("todoread", "todowrite") and "session_id" not in arguments:
                arguments["session_id"] = session_id

            # Call tool execute function
            start_time = time.time()
            result = await tool_def.execute(**arguments)
            end_time = time.time()

            # Build result strings
            output_str, sse_result = self._build_tool_result(result)

            # Update tool part
            tool_part.status = ToolState.COMPLETED
            tool_part.output = self._sanitize_tool_output(output_str)
            tool_part.end_time = end_time

            # Emit observe + MCP events
            async for ev in self._emit_observe_events(
                tool_name, tool_def, call_id, tool_part,
                sse_result, arguments, start_time, end_time,
            ):
                yield ev

            # Process artifacts
            async for ev in self._emit_artifact_events(tool_name, result, tool_part):
                yield ev

            # Emit todowrite events
            async for ev in self._emit_todowrite_events(tool_name, tool_def, session_id):
                yield ev

            # Emit plugin events
            async for ev in self._emit_plugin_events(tool_name, tool_def, output_str):
                yield ev

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            tool_part.status = ToolState.ERROR
            tool_part.error = str(e)
            tool_part.end_time = time.time()

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=str(e),
                duration_ms=int((time.time() - tool_part.start_time) * 1000)
                if tool_part.start_time
                else None,
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

        self._state = ProcessorState.OBSERVING

    def _set_tool_error(self, tool_part: ToolPart, error: str) -> None:
        \"\"\"Set error state on a tool part.\"\"\"
        tool_part.status = ToolState.ERROR
        tool_part.error = error
        tool_part.end_time = time.time()

    async def _check_doom_loop(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
    ) -> list[ProcessorEvent] | None:
        \"\"\"Check doom loop and request permission. Returns events if blocked, None to continue.\"\"\"
        if not self.doom_loop_detector.should_intervene(tool_name, arguments):
            return None

        events: list[ProcessorEvent] = [AgentDoomLoopDetectedEvent(tool=tool_name, input=arguments)]
        self._state = ProcessorState.WAITING_PERMISSION

        try:
            permission_result = await asyncio.wait_for(
                self.permission_manager.ask(
                    permission="doom_loop",
                    patterns=[tool_name],
                    session_id=session_id,
                    metadata={"tool": tool_name, "input": arguments},
                ),
                timeout=self.config.permission_timeout,
            )
            if permission_result == "reject":
                self._set_tool_error(tool_part, "Doom loop detected and rejected by user")
                events.append(AgentObserveEvent(
                    tool_name=tool_name,
                    error="Doom loop detected and rejected",
                    call_id=tool_part.call_id or "",
                    tool_execution_id=tool_part.tool_execution_id,
                ))
                return events
        except TimeoutError:
            self._set_tool_error(tool_part, "Permission request timed out")
            events.append(AgentObserveEvent(
                tool_name=tool_name,
                error="Permission request timed out",
                call_id=tool_part.call_id or "",
                tool_execution_id=tool_part.tool_execution_id,
            ))
            return events

        return None

    def _dispatch_hitl_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
    ) -> AsyncIterator[ProcessorEvent] | None:
        \"\"\"Dispatch HITL tools. Returns async iterator if matched, None otherwise.\"\"\"
        if tool_name == "ask_clarification":
            return self._handle_clarification_tool(
                session_id, call_id, tool_name, arguments, tool_part
            )
        if tool_name == "request_decision":
            return self._handle_decision_tool(
                session_id, call_id, tool_name, arguments, tool_part
            )
        if tool_name == "request_env_var":
            return self._handle_env_var_tool(
                session_id, call_id, tool_name, arguments, tool_part
            )
        return None

    async def _check_tool_permission(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_def: Any,
        tool_part: ToolPart,
    ) -> list[ProcessorEvent] | None:
        \"\"\"Check tool permission. Returns events if denied/timed out, None to continue.\"\"\"
        if not tool_def.permission:
            return None

        permission_rule = self.permission_manager.evaluate(
            permission=tool_def.permission,
            pattern=tool_name,
        )

        if permission_rule.action == PermissionAction.DENY:
            self._set_tool_error(tool_part, f"Permission denied: {tool_def.permission}")
            return [AgentObserveEvent(
                tool_name=tool_name,
                error=f"Permission denied: {tool_def.permission}",
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )]

        if permission_rule.action == PermissionAction.ASK:
            return await self._request_tool_permission(
                session_id, call_id, tool_name, arguments, tool_def, tool_part
            )

        return None

    async def _request_tool_permission(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_def: Any,
        tool_part: ToolPart,
    ) -> list[ProcessorEvent] | None:
        \"\"\"Request permission via HITLCoordinator. Returns events if denied, None if granted.\"\"\"
        self._state = ProcessorState.WAITING_PERMISSION
        events: list[ProcessorEvent] = []

        try:
            coordinator = self._get_hitl_coordinator()
            request_data = {
                "tool_name": tool_name,
                "action": "execute",
                "risk_level": "medium",
                "details": {"tool": tool_name, "input": arguments},
                "permission_type": tool_def.permission,
            }
            request_id = await coordinator.prepare_request(
                hitl_type=HITLType.PERMISSION,
                request_data=request_data,
                timeout_seconds=self.config.permission_timeout,
            )
            events.append(AgentPermissionAskedEvent(
                request_id=request_id,
                permission=tool_def.permission,
                patterns=[tool_name],
                metadata={"tool": tool_name, "input": arguments},
            ))

            permission_granted = await coordinator.wait_for_response(
                request_id=request_id,
                hitl_type=HITLType.PERMISSION,
                timeout_seconds=self.config.permission_timeout,
            )

            if not permission_granted:
                self._set_tool_error(tool_part, "Permission rejected by user")
                events.append(AgentObserveEvent(
                    tool_name=tool_name,
                    error="Permission rejected by user",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                ))
                return events

        except TimeoutError:
            self._set_tool_error(tool_part, "Permission request timed out")
            events.append(AgentObserveEvent(
                tool_name=tool_name,
                error="Permission request timed out",
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            ))
            return events
        except ValueError as e:
            logger.warning(f"[Processor] HITLCoordinator unavailable: {e}")
            self._set_tool_error(tool_part, "Permission request failed: no HITL context")
            events.append(AgentObserveEvent(
                tool_name=tool_name,
                error="Permission request failed: no HITL context",
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            ))
            return events

        return None

    def _resolve_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
    ) -> tuple[dict[str, Any], AgentObserveEvent | None]:
        \"\"\"Resolve truncated or raw arguments. Returns (arguments, error_event_or_none).\"\"\"
        if "_error" in arguments and arguments.get("_error") == "truncated":
            error_msg = arguments.get(
                "_message", "Tool arguments were truncated. The content may be too large."
            )
            logger.error(f"[Processor] Tool arguments truncated for {tool_name}")
            self._set_tool_error(tool_part, error_msg)
            return arguments, AgentObserveEvent(
                tool_name=tool_name,
                error=error_msg,
                call_id=tool_part.call_id or "",
                tool_execution_id=tool_part.tool_execution_id,
            )

        if "_raw" in arguments and len(arguments) == 1:
            parsed = self._parse_raw_arguments(tool_name, arguments["_raw"])
            if parsed is None:
                raw_args = arguments["_raw"]
                error_msg = (
                    f"Invalid JSON in tool arguments. "
                    f"Raw arguments preview: {raw_args[:500] if len(raw_args) > 500 else raw_args}"
                )
                logger.error(f"[Processor] Failed to parse _raw arguments for {tool_name}")
                self._set_tool_error(tool_part, error_msg)
                return arguments, AgentObserveEvent(
                    tool_name=tool_name,
                    error=error_msg,
                    call_id=tool_part.call_id or "",
                    tool_execution_id=tool_part.tool_execution_id,
                )
            arguments = parsed

        return arguments, None

    def _parse_raw_arguments(self, tool_name: str, raw_args: str) -> dict[str, Any] | None:
        \"\"\"Try to parse raw arguments string into dict. Returns None on failure.\"\"\"
        logger.warning(
            f"[Processor] Attempting to parse _raw arguments for tool {tool_name}: "
            f"{raw_args[:200] if len(raw_args) > 200 else raw_args}..."
        )

        def escape_control_chars(s: str) -> str:
            s = s.replace("\\n", "\\\\n")
            s = s.replace("\\r", "\\\\r")
            s = s.replace("\\t", "\\\\t")
            return s

        # Try 1: Direct parse
        try:
            result = json.loads(raw_args)
            logger.info(f"[Processor] Successfully parsed _raw arguments for {tool_name}")
            return result
        except json.JSONDecodeError:
            pass

        # Try 2: Escape control characters and parse
        try:
            fixed_args = escape_control_chars(raw_args)
            result = json.loads(fixed_args)
            logger.info(
                f"[Processor] Successfully parsed _raw arguments after escaping for {tool_name}"
            )
            return result
        except json.JSONDecodeError:
            pass

        # Try 3: Handle double-encoded JSON
        try:
            if raw_args.startswith('"') and raw_args.endswith('"'):
                inner = raw_args[1:-1]
                inner = inner.replace('\\\\"', '"').replace("\\\\\\\\", "\\\\")
                result = json.loads(inner)
                logger.info(
                    f"[Processor] Successfully parsed double-encoded _raw arguments for {tool_name}"
                )
                return result
        except json.JSONDecodeError:
            pass

        return None

    def _build_tool_result(
        self, result: Any
    ) -> tuple[str, Any]:
        \"\"\"Convert raw tool result to (output_str, sse_result).\"\"\"
        if isinstance(result, dict) and "artifact" in result:
            artifact = result["artifact"]
            output_str = result.get(
                "output",
                f"Exported artifact: {artifact.get('filename', 'unknown')} "
                f"({artifact.get('mime_type', 'unknown')}, "
                f"{artifact.get('size', 0)} bytes)",
            )
            sse_result = _strip_artifact_binary_data(result)
            return output_str, sse_result
        if isinstance(result, dict) and "output" in result:
            return result.get("output", ""), result
        if isinstance(result, str):
            return result, result
        return json.dumps(result), result

    async def _emit_observe_events(
        self,
        tool_name: str,
        tool_def: Any,
        call_id: str,
        tool_part: ToolPart,
        sse_result: Any,
        arguments: dict[str, Any],
        start_time: float,
        end_time: float,
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Emit observe event and optional MCP app result event.\"\"\"
        tool_instance = getattr(tool_def, "_tool_instance", None)
        has_ui = getattr(tool_instance, "has_ui", False) if tool_instance else False

        # Fallback for mcp__ tools
        if not has_ui and tool_name.startswith("mcp__") and tool_instance:
            _app_id_fb = getattr(tool_instance, "_app_id", "") or ""
            if _app_id_fb:
                has_ui = True
                logger.debug(
                    "[MCPApp] Fallback: tool %s has app_id=%s but no _ui_metadata",
                    tool_name, _app_id_fb,
                )

        # Build observe-level ui_metadata
        _observe_ui_meta, _hydrated_ui_meta = await self._build_observe_ui_metadata(
            tool_instance, has_ui, tool_name
        )

        yield AgentObserveEvent(
            tool_name=tool_name,
            result=sse_result,
            duration_ms=int((end_time - start_time) * 1000),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
            ui_metadata=_observe_ui_meta,
        )

        if tool_instance and has_ui:
            async for ev in self._emit_mcp_app_result_event(
                tool_name, tool_instance, tool_part, sse_result, arguments, _hydrated_ui_meta
            ):
                yield ev

    async def _build_observe_ui_metadata(
        self,
        tool_instance: Any,
        has_ui: bool,
        tool_name: str,
    ) -> tuple[dict | None, dict[str, Any]]:
        \"\"\"Build observe-level UI metadata for MCP tools with UI.\"\"\"
        if not tool_instance or not has_ui:
            return None, {}

        _o_app_id = (
            getattr(tool_instance, "_last_app_id", "")
            or getattr(tool_instance, "_app_id", "")
            or ""
        )
        _hydrated_ui_meta = await self._hydrate_mcp_ui_metadata(
            tool_instance=tool_instance,
            app_id=_o_app_id,
            tool_name=tool_name,
        )
        _o_server = getattr(tool_instance, "_server_name", "") or ""
        _o_project_id = (self._langfuse_context or {}).get("project_id", "")
        _observe_ui_meta = {
            "resource_uri": self._extract_mcp_resource_uri(_hydrated_ui_meta),
            "server_name": _o_server,
            "app_id": _o_app_id,
            "title": _hydrated_ui_meta.get("title", ""),
            "project_id": _o_project_id,
        }
        return _observe_ui_meta, _hydrated_ui_meta

    async def _emit_mcp_app_result_event(
        self,
        tool_name: str,
        tool_instance: Any,
        tool_part: ToolPart,
        sse_result: Any,
        arguments: dict[str, Any],
        hydrated_ui_meta: dict[str, Any],
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Build and emit MCP app result event.\"\"\"
        ui_meta = hydrated_ui_meta or getattr(tool_instance, "ui_metadata", None) or {}
        app_id = (
            getattr(tool_instance, "_last_app_id", "")
            or getattr(tool_instance, "_app_id", "")
            or ""
        )
        if not app_id:
            app_id = f"_synthetic_{tool_name}"

        resource_html = await self._fetch_mcp_resource_html(tool_instance, tool_name)

        logger.debug(
            "[MCPApp] Emitting event: tool=%s, app_id=%s, resource_uri=%s, html_len=%d",
            tool_name, app_id,
            self._extract_mcp_resource_uri(ui_meta), len(resource_html),
        )
        _server_name = getattr(tool_instance, "_server_name", "") or ""
        _project_id = (self._langfuse_context or {}).get("project_id", "")

        _structured_content = None
        if isinstance(sse_result, dict):
            _structured_content = sse_result.get("structuredContent")

        yield AgentMCPAppResultEvent(
            app_id=app_id,
            tool_name=tool_name,
            tool_result=sse_result,
            tool_input=arguments if arguments else None,
            resource_html=resource_html,
            resource_uri=self._extract_mcp_resource_uri(ui_meta),
            ui_metadata=ui_meta,
            tool_execution_id=tool_part.tool_execution_id,
            project_id=_project_id,
            server_name=_server_name,
            structured_content=_structured_content,
        )

    async def _fetch_mcp_resource_html(self, tool_instance: Any, tool_name: str) -> str:
        \"\"\"Fetch live HTML from MCP server via resources/read.\"\"\"
        resource_html = ""
        fetch_fn = getattr(tool_instance, "fetch_resource_html", None)
        if fetch_fn:
            try:
                resource_html = await fetch_fn()
            except Exception as fetch_err:
                logger.warning(
                    "[MCPApp] fetch_resource_html failed for %s: %s",
                    tool_name, fetch_err,
                )
        if not resource_html:
            resource_html = getattr(tool_instance, "_last_html", "") or ""
        return resource_html

    async def _emit_artifact_events(
        self,
        tool_name: str,
        result: Any,
        tool_part: ToolPart,
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Extract and upload artifacts from tool result.\"\"\"
        try:
            async for artifact_event in self._process_tool_artifacts(
                tool_name=tool_name,
                result=result,
                tool_execution_id=tool_part.tool_execution_id,
            ):
                yield artifact_event
        except Exception as artifact_err:
            logger.error(
                f"Artifact processing failed for tool {tool_name}: {artifact_err}",
                exc_info=True,
            )

    async def _emit_todowrite_events(
        self,
        tool_name: str,
        tool_def: Any,
        session_id: str,
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Emit pending task SSE events from todowrite tool.\"\"\"
        if tool_name != "todowrite":
            return
        tool_instance = getattr(tool_def, "_tool_instance", None)
        if not tool_instance or not hasattr(tool_instance, "consume_pending_events"):
            return

        try:
            pending = tool_instance.consume_pending_events()
            logger.info(
                f"[Processor] todowrite pending events: count={len(pending)}, "
                f"conversation_id={session_id}"
            )
            if not pending:
                logger.warning(
                    "[Processor] todowrite produced no pending events - "
                    "tool may have failed silently"
                )
            for task_event in pending:
                async for ev in self._process_todowrite_event(task_event):
                    yield ev
        except Exception as task_err:
            logger.error(f"Task event emission failed: {task_err}", exc_info=True)

    async def _process_todowrite_event(
        self, task_event: dict[str, Any]
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Process a single todowrite pending event.\"\"\"
        from src.domain.events.agent_events import (
            AgentTaskCompleteEvent,
            AgentTaskListUpdatedEvent,
            AgentTaskStartEvent,
            AgentTaskUpdatedEvent,
        )

        event_type = task_event.get("type")
        if event_type == "task_list_updated":
            yield from self._process_task_list_updated(task_event)
        elif event_type == "task_updated":
            yield from self._process_task_updated(task_event)

    def _process_task_list_updated(
        self, task_event: dict[str, Any]
    ) -> list[ProcessorEvent]:
        \"\"\"Process task_list_updated event.\"\"\"
        from src.domain.events.agent_events import (
            AgentTaskListUpdatedEvent,
            AgentTaskStartEvent,
        )

        events: list[ProcessorEvent] = []
        tasks = task_event["tasks"]
        logger.info(
            f"[Processor] Emitting task_list_updated: "
            f"{len(tasks)} tasks for {task_event['conversation_id']}"
        )
        events.append(AgentTaskListUpdatedEvent(
            conversation_id=task_event["conversation_id"],
            tasks=tasks,
        ))
        total = len(tasks)
        for t in tasks:
            if t.get("status") == "in_progress":
                self._current_task = {
                    "task_id": t["id"],
                    "content": t["content"],
                    "order_index": t.get("order_index", 0),
                    "total_tasks": total,
                }
                events.append(AgentTaskStartEvent(
                    task_id=t["id"],
                    content=t["content"],
                    order_index=t.get("order_index", 0),
                    total_tasks=total,
                ))
        return events

    def _process_task_updated(
        self, task_event: dict[str, Any]
    ) -> list[ProcessorEvent]:
        \"\"\"Process task_updated event.\"\"\"
        from src.domain.events.agent_events import (
            AgentTaskCompleteEvent,
            AgentTaskStartEvent,
            AgentTaskUpdatedEvent,
        )

        events: list[ProcessorEvent] = []
        task_status = task_event["status"]
        events.append(AgentTaskUpdatedEvent(
            conversation_id=task_event["conversation_id"],
            task_id=task_event["task_id"],
            status=task_status,
            content=task_event.get("content"),
        ))
        if task_status == "in_progress":
            total = self._current_task["total_tasks"] if self._current_task else 1
            self._current_task = {
                "task_id": task_event["task_id"],
                "content": task_event.get("content", ""),
                "order_index": task_event.get("order_index", 0),
                "total_tasks": total,
            }
            events.append(AgentTaskStartEvent(
                task_id=task_event["task_id"],
                content=task_event.get("content", ""),
                order_index=task_event.get("order_index", 0),
                total_tasks=total,
            ))
        elif task_status in ("completed", "failed", "cancelled"):
            ct = self._current_task
            if ct and ct["task_id"] == task_event["task_id"]:
                events.append(AgentTaskCompleteEvent(
                    task_id=ct["task_id"],
                    status=task_status,
                    order_index=ct["order_index"],
                    total_tasks=ct["total_tasks"],
                ))
                self._current_task = None
        return events

    async def _emit_plugin_events(
        self,
        tool_name: str,
        tool_def: Any,
        output_str: str,
    ) -> AsyncIterator[ProcessorEvent]:
        \"\"\"Emit pending SSE events from plugin/MCP tools.\"\"\"
        tool_instance = getattr(tool_def, "_tool_instance", None)
        refresh_count: int | None = None
        refresh_status = "not_applicable"
        if tool_name in {"plugin_manager", "register_mcp_server"}:
            if isinstance(output_str, str) and not output_str.startswith("Error:"):
                logger.info("[Processor] %s succeeded, refreshing tools", tool_name)
                refresh_count = self._refresh_tools()
                refresh_status = "success" if refresh_count is not None else "failed"
            else:
                logger.debug(
                    "[Processor] %s failed or returned error, skipping tool refresh",
                    tool_name,
                )
                refresh_status = "skipped"

        _plugin_tool_names = {
            "plugin_manager",
            "register_mcp_server",
            "skill_sync",
            "skill_installer",
            "delegate_to_subagent",
            "parallel_delegate_subagents",
            "sessions_spawn",
            "sessions_send",
            "subagents",
        }
        if (
            tool_name in _plugin_tool_names
            and tool_instance
            and hasattr(tool_instance, "consume_pending_events")
        ):
            try:
                for event in tool_instance.consume_pending_events():
                    if (
                        tool_name in {"plugin_manager", "register_mcp_server"}
                        and isinstance(event, dict)
                        and event.get("type") == "toolset_changed"
                    ):
                        event_data = event.get("data")
                        if isinstance(event_data, dict):
                            event_data.setdefault("refresh_source", "processor")
                            event_data["refresh_status"] = refresh_status
                            if refresh_count is not None:
                                event_data["refreshed_tool_count"] = refresh_count
                    yield event
            except Exception as pending_err:
                logger.error(f"{tool_name} event emission failed: {pending_err}")""".split("\n")


PROCESS_TOOL_ARTIFACTS_REPLACEMENT = """\
    async def _process_tool_artifacts(
        self,
        tool_name: str,
        result: Any,
        tool_execution_id: str | None = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        \"\"\"
        Process tool result and extract any artifacts (images, files, etc.).

        Yields:
            AgentArtifactCreatedEvent for each artifact created
        \"\"\"
        logger.warning(
            f"[ArtifactUpload] Processing tool={tool_name}, "
            f"has_service={self._artifact_service is not None}, "
            f"result_type={type(result).__name__}"
        )

        if not self._artifact_service:
            logger.warning("[ArtifactUpload] No artifact_service configured, skipping")
            return

        ctx = self._langfuse_context or {}
        project_id = ctx.get("project_id")
        tenant_id = ctx.get("tenant_id")
        conversation_id = ctx.get("conversation_id")
        message_id = ctx.get("message_id")

        if not project_id or not tenant_id:
            logger.warning(
                f"[ArtifactUpload] Missing context: project_id={project_id}, tenant_id={tenant_id}"
            )
            return

        if not isinstance(result, dict):
            return

        # Handle export_artifact result
        if result.get("artifact"):
            async for ev in self._process_export_artifact(
                tool_name, result, tool_execution_id,
                project_id, tenant_id, conversation_id, message_id,
            ):
                yield ev
            return

        # Handle MCP content array
        async for ev in self._process_mcp_content_artifacts(
            tool_name, result, tool_execution_id, project_id, tenant_id, conversation_id
        ):
            yield ev

    async def _process_export_artifact(
        self,
        tool_name: str,
        result: dict[str, Any],
        tool_execution_id: str | None,
        project_id: str,
        tenant_id: str,
        conversation_id: str | None,
        message_id: str | None,
    ) -> AsyncIterator[AgentDomainEvent]:
        \"\"\"Process export_artifact tool result.\"\"\"
        artifact_info = result["artifact"]
        try:
            file_content = self._extract_artifact_file_content(result, artifact_info)
            if file_content is None:
                return

            from src.application.services.artifact_service import (
                detect_mime_type,
                get_category_from_mime,
            )

            filename = artifact_info.get("filename", "exported_file")
            mime_type = detect_mime_type(filename)
            category = get_category_from_mime(mime_type)
            artifact_id = str(uuid.uuid4())

            yield AgentArtifactCreatedEvent(
                artifact_id=artifact_id,
                filename=filename,
                mime_type=mime_type,
                category=category.value,
                size_bytes=len(file_content),
                url=None,
                preview_url=None,
                tool_execution_id=tool_execution_id,
                source_tool=tool_name,
                source_path=artifact_info.get("path"),
            )

            # Emit artifact_open for canvas-displayable content
            canvas_type = _get_canvas_content_type(mime_type, filename)
            if canvas_type and len(file_content) < 500_000:
                try:
                    text_content = file_content.decode("utf-8")
                    yield AgentArtifactOpenEvent(
                        artifact_id=artifact_id,
                        title=filename,
                        content=text_content,
                        content_type=canvas_type,
                        language=_get_language_from_filename(filename),
                    )
                except (UnicodeDecodeError, ValueError):
                    pass

            # Schedule background upload
            self._schedule_artifact_upload(
                file_content, filename, project_id, tenant_id,
                tool_execution_id, conversation_id or "", message_id or "",
                tool_name, artifact_id, mime_type, category.value,
            )

        except Exception as e:
            import traceback

            logger.error(
                f"Failed to process export_artifact result: {e}\\n"
                f"Artifact info: {artifact_info}\\n"
                f"Traceback: {traceback.format_exc()}"
            )

    def _extract_artifact_file_content(
        self, result: dict[str, Any], artifact_info: dict[str, Any]
    ) -> bytes | None:
        \"\"\"Extract binary or text file content from artifact info.\"\"\"
        import base64

        encoding = artifact_info.get("encoding", "utf-8")
        if encoding == "base64":
            data = artifact_info.get("data")
            if not data:
                for item in result.get("content", []):
                    if item.get("type") == "image":
                        data = item.get("data")
                        break
            if data:
                file_content = base64.b64decode(data)
                logger.warning(
                    f"[ArtifactUpload] Decoded {len(file_content)} bytes from base64"
                )
                return file_content
            logger.warning("[ArtifactUpload] base64 encoding but no data found")
            return None

        # Text file
        content = result.get("content", [])
        if not content:
            logger.warning("export_artifact returned no content")
            return None
        first_item = content[0] if content else {}
        text = (
            first_item.get("text", "")
            if isinstance(first_item, dict)
            else str(first_item)
        )
        if not text:
            logger.warning("export_artifact returned empty text content")
            return None
        return text.encode("utf-8")

    def _schedule_artifact_upload(  # noqa: PLR0913
        self,
        file_content: bytes,
        filename: str,
        project_id: str,
        tenant_id: str,
        tool_execution_id: str | None,
        conversation_id: str,
        message_id: str,
        tool_name: str,
        artifact_id: str,
        mime_type: str,
        category_value: str,
    ) -> None:
        \"\"\"Schedule artifact upload in a background task.\"\"\"
        logger.warning(
            f"[ArtifactUpload] Scheduling threaded upload: filename={filename}, "
            f"size={len(file_content)}, project_id={project_id}"
        )

        def _sync_upload(  # noqa: PLR0913
            content: bytes,
            fname: str,
            pid: str,
            tid: str,
            texec_id: str,
            tname: str,
            art_id: str,
            bucket: str,
            endpoint: str,
            access_key: str,
            secret_key: str,
            region: str,
            mime: str,
            no_proxy: bool = False,
        ) -> dict:
            \"\"\"Synchronous S3 upload in a thread pool.\"\"\"
            from datetime import date
            from urllib.parse import quote

            import boto3
            from botocore.config import Config as BotoConfig

            config_kwargs: dict = {
                "connect_timeout": 10,
                "read_timeout": 30,
                "retries": {"max_attempts": 5, "mode": "standard"},
            }
            if no_proxy:
                config_kwargs["proxies"] = {"http": None, "https": None}

            s3 = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=BotoConfig(**config_kwargs),
            )

            date_part = date.today().strftime("%Y/%m/%d")
            unique_id = art_id[:8]
            safe_fname = fname.replace("/", "_")
            object_key = (
                f"artifacts/{tid}/{pid}/{date_part}"
                f"/{texec_id or 'direct'}/{unique_id}_{safe_fname}"
            )

            metadata = {
                "artifact_id": art_id,
                "project_id": pid,
                "tenant_id": tid,
                "filename": quote(fname, safe=""),
                "source_tool": tname or "",
            }

            s3.put_object(
                Bucket=bucket,
                Key=object_key,
                Body=content,
                ContentType=mime,
                Metadata=metadata,
            )

            url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": object_key},
                ExpiresIn=7 * 24 * 3600,
            )

            return {
                "url": url,
                "object_key": object_key,
                "size_bytes": len(content),
            }

        async def _threaded_upload(  # noqa: PLR0913
            content: bytes,
            fname: str,
            pid: str,
            tid: str,
            texec_id: str,
            conv_id: str,
            msg_id: str,
            tname: str,
            art_id: str,
            mime: str,
            cat: str,
        ) -> None:
            \"\"\"Run sync upload in thread, then publish result to Redis and DB.\"\"\"
            import time as _time

            from src.configuration.config import get_settings
            from src.infrastructure.agent.actor.execution import (
                _persist_events,
                _publish_event_to_stream,
            )

            settings = get_settings()

            try:
                result = await asyncio.to_thread(
                    _sync_upload,
                    content=content,
                    fname=fname,
                    pid=pid,
                    tid=tid,
                    texec_id=texec_id,
                    tname=tname,
                    art_id=art_id,
                    bucket=settings.s3_bucket_name,
                    endpoint=settings.s3_endpoint_url,
                    access_key=settings.aws_access_key_id,
                    secret_key=settings.aws_secret_access_key,
                    region=settings.aws_region,
                    mime=mime,
                    no_proxy=settings.s3_no_proxy,
                )
                logger.warning(
                    f"[ArtifactUpload] Threaded upload SUCCESS: "
                    f"filename={fname}, url={result['url'][:80]}"
                )

                ready_event = AgentArtifactReadyEvent(
                    artifact_id=art_id,
                    filename=fname,
                    mime_type=mime,
                    category=cat,
                    size_bytes=result["size_bytes"],
                    url=result["url"],
                    tool_execution_id=texec_id,
                    source_tool=tname,
                )
                ready_event_dict = ready_event.to_event_dict()
                ready_time_us = int(_time.time() * 1_000_000)
                await _publish_event_to_stream(
                    conversation_id=conv_id,
                    event=ready_event_dict,
                    message_id=msg_id,
                    event_time_us=ready_time_us,
                    event_counter=0,
                )
                await _persist_events(
                    conversation_id=conv_id,
                    message_id=msg_id,
                    events=[
                        {
                            **ready_event_dict,
                            "event_time_us": ready_time_us,
                            "event_counter": 0,
                        }
                    ],
                )
            except Exception as upload_err:
                logger.error(
                    f"[ArtifactUpload] Threaded upload failed: {fname}: {upload_err}"
                )
                error_event = AgentArtifactErrorEvent(
                    artifact_id=art_id,
                    filename=fname,
                    tool_execution_id=texec_id,
                    error=f"Upload failed: {upload_err}",
                )
                error_event_dict = error_event.to_event_dict()
                error_time_us = int(_time.time() * 1_000_000)
                try:
                    await _publish_event_to_stream(
                        conversation_id=conv_id,
                        event=error_event_dict,
                        message_id=msg_id,
                        event_time_us=error_time_us,
                        event_counter=0,
                    )
                except Exception:
                    logger.error("[ArtifactUpload] Failed to publish error event")
                try:
                    await _persist_events(
                        conversation_id=conv_id,
                        message_id=msg_id,
                        events=[
                            {
                                **error_event_dict,
                                "event_time_us": error_time_us,
                                "event_counter": 0,
                            }
                        ],
                    )
                except Exception:
                    logger.error("[ArtifactUpload] Failed to persist error event")

        _upload_task = asyncio.create_task(
            _threaded_upload(
                content=file_content,
                fname=filename,
                pid=project_id,
                tid=tenant_id,
                texec_id=tool_execution_id,
                conv_id=conversation_id,
                msg_id=message_id,
                tname=tool_name,
                art_id=artifact_id,
                mime=mime_type,
                cat=category_value,
            )
        )
        _processor_bg_tasks.add(_upload_task)
        _upload_task.add_done_callback(_processor_bg_tasks.discard)

    async def _process_mcp_content_artifacts(
        self,
        tool_name: str,
        result: dict[str, Any],
        tool_execution_id: str | None,
        project_id: str,
        tenant_id: str,
        conversation_id: str | None,
    ) -> AsyncIterator[AgentDomainEvent]:
        \"\"\"Process MCP content array with images/resources.\"\"\"
        content = result.get("content", [])
        if not content:
            return

        has_rich_content = any(
            item.get("type") in ("image", "resource")
            for item in content
            if isinstance(item, dict)
        )
        if not has_rich_content:
            return

        try:
            artifact_data_list = extract_artifacts_from_mcp_result(result, tool_name)

            for artifact_data in artifact_data_list:
                try:
                    artifact = await self._artifact_service.create_artifact(
                        file_content=artifact_data["content"],
                        filename=artifact_data["filename"],
                        project_id=project_id,
                        tenant_id=tenant_id,
                        sandbox_id=None,
                        tool_execution_id=tool_execution_id,
                        conversation_id=conversation_id,
                        source_tool=tool_name,
                        source_path=artifact_data.get("source_path"),
                        metadata={
                            "extracted_from": "mcp_result",
                            "original_mime": artifact_data["mime_type"],
                        },
                    )

                    logger.info(
                        f"Created artifact {artifact.id} from tool {tool_name}: "
                        f"{artifact.filename} ({artifact.category.value}, {artifact.size_bytes} bytes)"
                    )

                    yield AgentArtifactCreatedEvent(
                        artifact_id=artifact.id,
                        filename=artifact.filename,
                        mime_type=artifact.mime_type,
                        category=artifact.category.value,
                        size_bytes=artifact.size_bytes,
                        url=artifact.url,
                        preview_url=artifact.preview_url,
                        tool_execution_id=tool_execution_id,
                        source_tool=tool_name,
                    )

                except Exception as e:
                    logger.error(f"Failed to create artifact from {tool_name}: {e}")

        except Exception as e:
            logger.error(f"Error processing artifacts from tool {tool_name}: {e}")""".split("\n")


if __name__ == "__main__":
    main()
