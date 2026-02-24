"""Refactor processor.py to fix ruff complexity violations.

Strategy: Read the file, replace each violating function with a refactored version
that delegates to extracted helper methods.

Functions to fix:
1. process() - PLR0912(27), PLR0915(83)
2. _evaluate_llm_goal() - PLR0912(13)
3. _extract_goal_json() - PLR0912(15)
4. _process_step() - PLR0912(28), PLR0915(122)
5. _execute_tool() - PLR0911(13), PLR0912(63), PLR0915(236)
6. _process_tool_artifacts() - PLR0911(9), PLR0912(23), PLR0915(120)
"""

import sys

SRC = "src/infrastructure/agent/processor/processor.py"

with open(SRC, "r") as f:
    lines = f.readlines()

# We need the full text to do replacements
full_text = "".join(lines)


def find_method_range(lines, method_name, start_search=0):
    """Find the start and end line indices (0-based) for a method definition.

    Returns (start, end) where start is the line with 'async def' or 'def',
    and end is the last line of the method (before the next method at same indentation).
    """
    # Find the def line
    start = None
    for i in range(start_search, len(lines)):
        stripped = lines[i].lstrip()
        if stripped.startswith(f"async def {method_name}(") or stripped.startswith(
            f"def {method_name}("
        ):
            start = i
            break

    if start is None:
        raise ValueError(f"Method {method_name} not found after line {start_search}")

    # Determine indentation level
    indent = len(lines[start]) - len(lines[start].lstrip())

    # Find end: next def at same or lower indentation level, or end of class
    end = len(lines) - 1
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            continue
        line_indent = len(line) - len(line.lstrip())
        stripped = line.lstrip()
        # Another method at same indent or lower indent (e.g., class boundary)
        if (
            line_indent <= indent
            and stripped
            and not stripped.startswith("#")
            and not stripped.startswith("@")
        ):
            # Check if it's a def/async def or class or top-level
            if (
                stripped.startswith("def ")
                or stripped.startswith("async def ")
                or stripped.startswith("class ")
                or line_indent < indent
            ):
                end = i - 1
                # Trim trailing blank lines
                while end > start and lines[end].strip() == "":
                    end -= 1
                break

    return start, end


# ============================================================
# 1. Refactor process() - lines 497-673
# ============================================================

PROCESS_REPLACEMENT = '''\
    async def process(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        abort_signal: asyncio.Event | None = None,
        langfuse_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ProcessorEvent]:
        """
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
        """
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
                result = self._check_abort_and_limits(result)
                if result != ProcessorResult.CONTINUE:
                    yield from self._build_abort_or_limit_events(result)
                    return

                # Process one step
                had_tool_calls = False
                async for event in self._process_step(session_id, messages):
                    yield event
                    step_result = self._classify_step_event(event)
                    if step_result == ProcessorResult.STOP:
                        result = ProcessorResult.STOP
                        break
                    elif step_result == ProcessorResult.COMPACT:
                        result = ProcessorResult.COMPACT
                        break
                    elif step_result == "had_tool_calls":
                        had_tool_calls = True

                # Evaluate goal if no stop/compact
                if result == ProcessorResult.CONTINUE:
                    async for ev in self._evaluate_no_tool_result(
                        session_id, messages, had_tool_calls
                    ):
                        yield ev
                    result = self._last_process_result

                # Append tool results to messages for next iteration
                if result == ProcessorResult.CONTINUE:
                    self._append_tool_results_to_messages(messages)

            # Emit completion events
            async for ev in self._emit_completion_events(result, session_id):
                yield ev

        except Exception as e:
            logger.error(f"Processor error: {e}", exc_info=True)
            yield AgentErrorEvent(message=str(e), code=type(e).__name__)
            self._state = ProcessorState.ERROR

    def _check_abort_and_limits(self, result: ProcessorResult) -> ProcessorResult:
        """Check abort signal and step limits. Returns CONTINUE or STOP."""
        if self._abort_event and self._abort_event.is_set():
            return ProcessorResult.STOP
        self._step_count += 1
        if self._step_count > self.config.max_steps:
            return ProcessorResult.STOP
        return ProcessorResult.CONTINUE

    def _build_abort_or_limit_events(
        self, result: ProcessorResult
    ) -> list[ProcessorEvent]:
        """Build error events for abort or step limit exceeded."""
        events: list[ProcessorEvent] = []
        if self._abort_event and self._abort_event.is_set():
            events.append(AgentErrorEvent(message="Processing aborted", code="ABORTED"))
        elif self._step_count > self.config.max_steps:
            events.append(
                AgentErrorEvent(
                    message=f"Maximum steps ({self.config.max_steps}) exceeded",
                    code="MAX_STEPS_EXCEEDED",
                )
            )
        self._state = ProcessorState.ERROR
        return events

    def _classify_step_event(self, event: ProcessorEvent) -> ProcessorResult | str | None:
        """Classify a step event to determine loop control."""
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
            return ProcessorResult.STOP
        if event_type == AgentEventType.ACT.value:
            return "had_tool_calls"
        if event_type == AgentEventType.COMPACT_NEEDED.value:
            return ProcessorResult.COMPACT
        return None

    async def _evaluate_no_tool_result(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        had_tool_calls: bool,
    ) -> AsyncIterator[ProcessorEvent]:
        """Evaluate goal when no stop/compact occurred. Sets self._last_process_result."""
        if had_tool_calls:
            self._no_progress_steps = 0
            self._last_process_result = ProcessorResult.CONTINUE
            return

        goal_check = await self._evaluate_goal_completion(session_id, messages)
        if goal_check.achieved:
            self._no_progress_steps = 0
            yield AgentStatusEvent(status=f"goal_achieved:{goal_check.source}")
            self._last_process_result = ProcessorResult.COMPLETE
            return

        if self._is_conversational_response():
            self._no_progress_steps = 0
            yield AgentStatusEvent(status="goal_achieved:conversational_response")
            self._last_process_result = ProcessorResult.COMPLETE
            return

        if goal_check.should_stop:
            yield AgentErrorEvent(
                message=goal_check.reason or "Goal cannot be completed",
                code="GOAL_NOT_ACHIEVED",
            )
            self._state = ProcessorState.ERROR
            self._last_process_result = ProcessorResult.STOP
            return

        async for ev in self._handle_no_progress(goal_check):
            yield ev

    async def _handle_no_progress(
        self, goal_check: GoalCheckResult
    ) -> AsyncIterator[ProcessorEvent]:
        """Handle no-progress case and set self._last_process_result."""
        self._no_progress_steps += 1
        yield AgentStatusEvent(status=f"goal_pending:{goal_check.source}")
        if self._no_progress_steps > 1:
            yield AgentStatusEvent(status="planning_recheck")
        if self._no_progress_steps >= self.config.max_no_progress_steps:
            yield AgentErrorEvent(
                message=(
                    "Goal not achieved after "
                    f"{self._no_progress_steps} no-progress turns. "
                    f"{goal_check.reason or 'Replan required.'}"
                ),
                code="GOAL_NOT_ACHIEVED",
            )
            self._state = ProcessorState.ERROR
            self._last_process_result = ProcessorResult.STOP
        else:
            self._last_process_result = ProcessorResult.CONTINUE

    def _append_tool_results_to_messages(self, messages: list[dict[str, Any]]) -> None:
        """Append current message and tool results to messages list."""
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

    async def _emit_completion_events(
        self, result: ProcessorResult, session_id: str
    ) -> AsyncIterator[ProcessorEvent]:
        """Emit final completion/compact events."""
        if result == ProcessorResult.COMPLETE:
            suggestions_event = await self._generate_suggestions([])
            if suggestions_event:
                yield suggestions_event
            trace_url = self._build_trace_url(session_id)
            yield AgentCompleteEvent(trace_url=trace_url)
            self._state = ProcessorState.COMPLETED
        elif result == ProcessorResult.COMPACT:
            yield AgentStatusEvent(status="compact_needed")

    def _build_trace_url(self, session_id: str) -> str | None:
        """Build Langfuse trace URL if context is available."""
        if not self._langfuse_context:
            return None
        from src.configuration.config import get_settings

        settings = get_settings()
        if settings.langfuse_enabled and settings.langfuse_host:
            trace_id = self._langfuse_context.get("conversation_id", session_id)
            return f"{settings.langfuse_host}/trace/{trace_id}"
        return None
'''

# ============================================================
# 2. Refactor _evaluate_llm_goal() - PLR0912(13 branches)
# Extract bool coercion into helper
# ============================================================

EVALUATE_LLM_GOAL_REPLACEMENT = '''\
    async def _evaluate_llm_goal(self, messages: list[dict[str, Any]]) -> GoalCheckResult:
        """Evaluate completion using explicit LLM self-check in no-task mode."""
        fallback = self._evaluate_goal_from_latest_text()
        if self._llm_client is None:
            return fallback

        context_summary = self._build_goal_check_context(messages)
        if not context_summary:
            return fallback

        content = await self._call_goal_check_llm(context_summary, fallback)
        if content is None:
            return fallback

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

    async def _call_goal_check_llm(
        self, context_summary: str, fallback: GoalCheckResult
    ) -> str | None:
        """Call LLM for goal self-check. Returns response content or None."""
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
            return None

        if isinstance(response, dict):
            return str(response.get("content", "") or "")
        if isinstance(response, str):
            return response
        return str(response)

    @staticmethod
    def _coerce_goal_achieved_bool(value: Any) -> bool | None:
        """Coerce a goal_achieved value to bool or return None if unparseable."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        return None
'''

# ============================================================
# 3. Refactor _extract_goal_json() - PLR0912(15 branches)
# Extract JSON scanning loop into static method
# ============================================================

EXTRACT_GOAL_JSON_REPLACEMENT = '''\
    def _extract_goal_json(self, text: str) -> dict[str, Any] | None:
        """Extract goal-check JSON object from model text."""
        stripped = text.strip()
        if not stripped:
            return None

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        return self._scan_for_json_object(stripped)

    @staticmethod
    def _scan_for_json_object(text: str) -> dict[str, Any] | None:
        """Scan text for a valid JSON object using brace-depth tracking."""
        start_idx = text.find("{")
        while start_idx >= 0:
            result = SessionProcessor._try_extract_json_at(text, start_idx)
            if result is not None:
                return result
            start_idx = text.find("{", start_idx + 1)
        return None

    @staticmethod
    def _try_extract_json_at(text: str, start_idx: int) -> dict[str, Any] | None:
        """Try to extract a JSON object starting at start_idx."""
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
                    return SessionProcessor._parse_json_candidate(
                        text[start_idx : index + 1]
                    )
        return None

    @staticmethod
    def _parse_json_candidate(candidate: str) -> dict[str, Any] | None:
        """Parse a JSON candidate string, returning dict or None."""
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None
'''

# ============================================================
# 4. Refactor _process_step() - PLR0912(28), PLR0915(122)
# Extract handlers for each StreamEventType branch
# ============================================================

PROCESS_STEP_REPLACEMENT = '''\
    async def _process_step(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[ProcessorEvent]:
        """
        Process a single step in the ReAct loop.

        Args:
            session_id: Session identifier
            messages: Current messages

        Yields:
            AgentDomainEvent objects and dict passthrough events
        """
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
        step_state = _StepState()

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

                    async for output_event in self._dispatch_stream_event(
                        session_id, event, step_state
                    ):
                        yield output_event

                # Step completed successfully
                break

            except Exception as e:
                if self.retry_policy.is_retryable(e) and attempt < self.config.max_attempts:
                    attempt += 1
                    delay_ms = self.retry_policy.calculate_delay(attempt, e)
                    self._state = ProcessorState.RETRYING
                    yield AgentRetryEvent(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        message=str(e),
                    )
                    await asyncio.sleep(delay_ms / 1000)
                    continue
                else:
                    raise

        # Finalize step
        async for ev in self._finalize_step(messages, step_state):
            yield ev

    def _build_step_langfuse_context(self) -> dict[str, Any] | None:
        """Build step-specific langfuse context."""
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

    async def _dispatch_stream_event(
        self,
        session_id: str,
        event: Any,
        step_state: "_StepState",
    ) -> AsyncIterator[ProcessorEvent]:
        """Dispatch a single stream event to the appropriate handler."""
        etype = event.type
        if etype == StreamEventType.TEXT_START:
            yield AgentTextStartEvent()
        elif etype == StreamEventType.TEXT_DELTA:
            delta = event.data.get("delta", "")
            step_state.text_buffer += delta
            yield AgentTextDeltaEvent(delta=delta)
        elif etype == StreamEventType.TEXT_END:
            yield self._handle_text_end(event, step_state)
        elif etype == StreamEventType.REASONING_START:
            pass
        elif etype == StreamEventType.REASONING_DELTA:
            delta = event.data.get("delta", "")
            step_state.reasoning_buffer += delta
            yield AgentThoughtDeltaEvent(delta=delta)
        elif etype == StreamEventType.REASONING_END:
            yield self._handle_reasoning_end(event, step_state)
        elif etype == StreamEventType.TOOL_CALL_START:
            yield self._handle_tool_call_start(event)
        elif etype == StreamEventType.TOOL_CALL_DELTA:
            ev = self._handle_tool_call_delta(event)
            if ev is not None:
                yield ev
        elif etype == StreamEventType.TOOL_CALL_END:
            async for ev in self._handle_tool_call_end(session_id, event, step_state):
                yield ev
        elif etype == StreamEventType.USAGE:
            async for ev in self._handle_usage_event(event, step_state):
                yield ev
        elif etype == StreamEventType.FINISH:
            step_state.finish_reason = event.data.get("reason", "stop")
        elif etype == StreamEventType.ERROR:
            error_msg = event.data.get("message", "Unknown error")
            raise Exception(error_msg)

    def _handle_text_end(self, event: Any, step_state: "_StepState") -> ProcessorEvent:
        """Handle TEXT_END stream event."""
        full_text = event.data.get("full_text", step_state.text_buffer)
        logger.debug(f"[Processor] TEXT_END: len={len(full_text) if full_text else 0}")
        self._current_message.add_text(full_text)
        return AgentTextEndEvent(full_text=full_text)

    def _handle_reasoning_end(self, event: Any, step_state: "_StepState") -> ProcessorEvent:
        """Handle REASONING_END stream event."""
        full_reasoning = event.data.get("full_text", step_state.reasoning_buffer)
        self._current_message.add_reasoning(full_reasoning)
        return AgentThoughtEvent(content=full_reasoning, thought_level="reasoning")

    def _handle_tool_call_start(self, event: Any) -> ProcessorEvent:
        """Handle TOOL_CALL_START stream event."""
        call_id = event.data.get("call_id", "")
        tool_name = event.data.get("name", "")
        tool_part = self._current_message.add_tool_call(
            call_id=call_id,
            tool=tool_name,
            input={},
        )
        self._pending_tool_calls[call_id] = tool_part
        self._pending_tool_args[call_id] = ""
        return AgentActDeltaEvent(
            tool_name=tool_name,
            call_id=call_id,
            arguments_fragment="",
            accumulated_arguments="",
        )

    def _handle_tool_call_delta(self, event: Any) -> ProcessorEvent | None:
        """Handle TOOL_CALL_DELTA stream event."""
        call_id = event.data.get("call_id", "")
        args_delta = event.data.get("arguments_delta", "")
        if call_id not in self._pending_tool_calls or not args_delta:
            return None
        self._pending_tool_args[call_id] = (
            self._pending_tool_args.get(call_id, "") + args_delta
        )
        tool_part = self._pending_tool_calls[call_id]
        return AgentActDeltaEvent(
            tool_name=tool_part.tool or "",
            call_id=call_id,
            arguments_fragment=args_delta,
            accumulated_arguments=self._pending_tool_args[call_id],
        )

    async def _handle_tool_call_end(
        self, session_id: str, event: Any, step_state: "_StepState"
    ) -> AsyncIterator[ProcessorEvent]:
        """Handle TOOL_CALL_END stream event."""
        call_id = event.data.get("call_id", "")
        tool_name = event.data.get("name", "")
        arguments = event.data.get("arguments", {})

        # Validate tool call schema
        validation_error = self._validate_tool_call(call_id, tool_name, arguments)
        if validation_error is not None:
            yield validation_error
            return

        # Update tool part and execute
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

            async for tool_event in self._execute_tool(
                session_id, call_id, tool_name, arguments
            ):
                yield tool_event

            step_state.tool_calls_completed.append(call_id)

    def _validate_tool_call(
        self, call_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> ProcessorEvent | None:
        """Validate tool call parameters. Returns error event or None."""
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

    async def _handle_usage_event(
        self, event: Any, step_state: "_StepState"
    ) -> AsyncIterator[ProcessorEvent]:
        """Handle USAGE stream event."""
        step_state.step_tokens = TokenUsage(
            input=event.data.get("input_tokens", 0),
            output=event.data.get("output_tokens", 0),
            reasoning=event.data.get("reasoning_tokens", 0),
            cache_read=event.data.get("cache_read_tokens", 0),
            cache_write=event.data.get("cache_write_tokens", 0),
        )

        cost_result = self.cost_tracker.calculate(
            usage={
                "input_tokens": step_state.step_tokens.input,
                "output_tokens": step_state.step_tokens.output,
                "reasoning_tokens": step_state.step_tokens.reasoning,
                "cache_read_tokens": step_state.step_tokens.cache_read,
                "cache_write_tokens": step_state.step_tokens.cache_write,
            },
            model_name=self.config.model,
        )
        step_state.step_cost = float(cost_result.cost)

        yield AgentCostUpdateEvent(
            cost=step_state.step_cost,
            tokens={
                "input": step_state.step_tokens.input,
                "output": step_state.step_tokens.output,
                "reasoning": step_state.step_tokens.reasoning,
            },
        )

        yield self._build_context_status_event(step_state.step_tokens.input)

        if self.cost_tracker.needs_compaction(step_state.step_tokens):
            yield AgentCompactNeededEvent()

    def _build_context_status_event(self, current_input: int) -> AgentContextStatusEvent:
        """Build a context status event from input token count."""
        context_limit = self.config.context_limit
        occupancy = (current_input / context_limit * 100) if context_limit > 0 else 0
        return AgentContextStatusEvent(
            current_tokens=current_input,
            token_budget=context_limit,
            occupancy_pct=round(occupancy, 1),
            compression_level="none",
        )

    async def _finalize_step(
        self, messages: list[dict[str, Any]], step_state: "_StepState"
    ) -> AsyncIterator[ProcessorEvent]:
        """Finalize step: update message tokens/cost, emit context status."""
        self._current_message.tokens = {
            "input": step_state.step_tokens.input,
            "output": step_state.step_tokens.output,
            "reasoning": step_state.step_tokens.reasoning,
        }
        self._current_message.cost = step_state.step_cost
        self._current_message.finish_reason = step_state.finish_reason
        self._current_message.completed_at = time.time()

        current_input = step_state.step_tokens.input
        if current_input == 0:
            total_chars = sum(len(str(m.get("content", ""))) for m in messages)
            current_input = total_chars // 4
        yield self._build_context_status_event(current_input)
'''

# ============================================================
# 5. Refactor _execute_tool() - BIGGEST
# PLR0911(13), PLR0912(63), PLR0915(236)
# ============================================================

EXECUTE_TOOL_REPLACEMENT = '''\
    async def _execute_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> AsyncIterator[ProcessorEvent]:
        """
        Execute a tool call with permission checking and doom loop detection.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Yields:
            AgentDomainEvent objects and dict passthrough events for tool execution
        """
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

        tool_def = self.tools.get(tool_name)
        if not tool_def:
            self._set_tool_error(tool_part, f"Unknown tool: {tool_name}")
            yield self._build_error_observe(tool_name, f"Unknown tool: {tool_name}", call_id, tool_part)
            return

        # Doom loop check
        doom_result = await self._handle_doom_loop_check(
            session_id, call_id, tool_name, arguments, tool_part
        )
        if doom_result is not None:
            for ev in doom_result:
                yield ev
            return

        self.doom_loop_detector.record(tool_name, arguments)

        # HITL tool dispatch
        hitl_result = self._dispatch_hitl_tool(session_id, call_id, tool_name, arguments, tool_part)
        if hitl_result is not None:
            async for ev in hitl_result:
                yield ev
            return

        # Permission check
        perm_result = await self._handle_tool_permission(
            session_id, call_id, tool_name, arguments, tool_def, tool_part
        )
        if perm_result is not None:
            for ev in perm_result:
                yield ev
            return

        # Execute the tool
        self._state = ProcessorState.ACTING
        try:
            async for ev in self._run_tool_execution(
                session_id, call_id, tool_name, arguments, tool_def, tool_part
            ):
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
        """Set error state on a tool part."""
        tool_part.status = ToolState.ERROR
        tool_part.error = error
        tool_part.end_time = time.time()

    def _build_error_observe(
        self,
        tool_name: str,
        error: str,
        call_id: str,
        tool_part: ToolPart,
    ) -> AgentObserveEvent:
        """Build an error observe event."""
        return AgentObserveEvent(
            tool_name=tool_name,
            error=error,
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )

    async def _handle_doom_loop_check(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
    ) -> list[ProcessorEvent] | None:
        """Check doom loop. Returns list of events + signals return, or None to continue."""
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
                events.append(self._build_error_observe(
                    tool_name, "Doom loop detected and rejected", call_id, tool_part
                ))
                return events
        except TimeoutError:
            self._set_tool_error(tool_part, "Permission request timed out")
            events.append(self._build_error_observe(
                tool_name, "Permission request timed out", call_id, tool_part
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
        """Dispatch HITL tools. Returns async iterator or None."""
        hitl_map = {
            "ask_clarification": self._handle_clarification_tool,
            "request_decision": self._handle_decision_tool,
            "request_env_var": self._handle_env_var_tool,
        }
        handler = hitl_map.get(tool_name)
        if handler is None:
            return None
        return handler(session_id, call_id, tool_name, arguments, tool_part)

    async def _handle_tool_permission(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_def: ToolDefinition,
        tool_part: ToolPart,
    ) -> list[ProcessorEvent] | None:
        """Check tool permission. Returns events + signals return, or None."""
        if not tool_def.permission:
            return None

        permission_rule = self.permission_manager.evaluate(
            permission=tool_def.permission,
            pattern=tool_name,
        )

        if permission_rule.action == PermissionAction.DENY:
            self._set_tool_error(tool_part, f"Permission denied: {tool_def.permission}")
            return [self._build_error_observe(
                tool_name, f"Permission denied: {tool_def.permission}", call_id, tool_part
            )]

        if permission_rule.action == PermissionAction.ASK:
            return await self._request_permission_via_hitl(
                session_id, call_id, tool_name, arguments, tool_def, tool_part
            )

        return None

    async def _request_permission_via_hitl(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_def: ToolDefinition,
        tool_part: ToolPart,
    ) -> list[ProcessorEvent] | None:
        """Request permission via HITL coordinator. Returns events or None."""
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
                events.append(self._build_error_observe(
                    tool_name, "Permission rejected by user", call_id, tool_part
                ))
                return events
        except TimeoutError:
            self._set_tool_error(tool_part, "Permission request timed out")
            events.append(self._build_error_observe(
                tool_name, "Permission request timed out", call_id, tool_part
            ))
            return events
        except ValueError as e:
            logger.warning(f"[Processor] HITLCoordinator unavailable: {e}")
            self._set_tool_error(tool_part, "Permission request failed: no HITL context")
            events.append(self._build_error_observe(
                tool_name, "Permission request failed: no HITL context", call_id, tool_part
            ))
            return events

        return None

    async def _run_tool_execution(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_def: ToolDefinition,
        tool_part: ToolPart,
    ) -> AsyncIterator[ProcessorEvent]:
        """Core tool execution: resolve args, call tool, emit observe + post-events."""
        # Resolve truncated / _raw arguments
        resolved = self._resolve_tool_arguments(tool_name, arguments, tool_part, call_id)
        if resolved is None:
            yield self._build_error_observe(tool_name, tool_part.error or "", call_id, tool_part)
            return
        arguments = resolved

        # Inject session_id for tools that need conversation context
        if tool_name in ("todoread", "todowrite") and "session_id" not in arguments:
            arguments["session_id"] = session_id

        # Call tool execute function
        start_time = time.time()
        result = await tool_def.execute(**arguments)
        end_time = time.time()

        # Build tool result
        output_str, sse_result = self._build_tool_result(result)

        # Update tool part
        tool_part.status = ToolState.COMPLETED
        tool_part.output = self._sanitize_tool_output(output_str)
        tool_part.end_time = end_time

        # Emit observe event with optional MCP UI metadata
        async for ev in self._emit_observe_event(
            tool_name, call_id, tool_part, tool_def, sse_result, arguments,
            start_time, end_time
        ):
            yield ev

        # Process artifacts
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

        # Emit todowrite events
        async for ev in self._emit_todowrite_events(tool_name, tool_def, session_id):
            yield ev

        # Emit plugin/tool events
        async for ev in self._emit_plugin_events(tool_name, tool_def, output_str):
            yield ev

    def _resolve_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
        call_id: str,
    ) -> dict[str, Any] | None:
        """Resolve truncated/_raw arguments. Returns resolved args or None on failure."""
        if "_error" in arguments and arguments.get("_error") == "truncated":
            error_msg = arguments.get(
                "_message", "Tool arguments were truncated. The content may be too large."
            )
            logger.error(f"[Processor] Tool arguments truncated for {tool_name}")
            self._set_tool_error(tool_part, error_msg)
            return None

        if "_raw" in arguments and len(arguments) == 1:
            return self._parse_raw_arguments(tool_name, arguments["_raw"], tool_part)

        return arguments

    def _parse_raw_arguments(
        self,
        tool_name: str,
        raw_args: str,
        tool_part: ToolPart,
    ) -> dict[str, Any] | None:
        """Try multiple strategies to parse raw JSON arguments."""
        logger.warning(
            f"[Processor] Attempting to parse _raw arguments for tool {tool_name}: "
            f"{raw_args[:200] if len(raw_args) > 200 else raw_args}..."
        )

        parsed = self._try_parse_raw_json(raw_args)
        if parsed is not None:
            logger.info(f"[Processor] Successfully parsed _raw arguments for {tool_name}")
            return parsed

        error_msg = (
            f"Invalid JSON in tool arguments. "
            f"Raw arguments preview: {raw_args[:500] if len(raw_args) > 500 else raw_args}"
        )
        logger.error(f"[Processor] Failed to parse _raw arguments for {tool_name}")
        self._set_tool_error(tool_part, error_msg)
        return None

    @staticmethod
    def _try_parse_raw_json(raw_args: str) -> dict[str, Any] | None:
        """Try parsing raw JSON with multiple strategies."""
        # Try 1: Direct parse
        try:
            return json.loads(raw_args)
        except json.JSONDecodeError:
            pass

        # Try 2: Escape control characters
        try:
            fixed = raw_args.replace("\\n", "\\\\n").replace("\\r", "\\\\r").replace("\\t", "\\\\t")
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Try 3: Handle double-encoded JSON
        try:
            if raw_args.startswith('"') and raw_args.endswith('"'):
                inner = raw_args[1:-1]
                inner = inner.replace('\\\\"', '"').replace("\\\\\\\\", "\\\\")
                return json.loads(inner)
        except json.JSONDecodeError:
            pass

        return None

    def _build_tool_result(
        self, result: Any
    ) -> tuple[str, Any]:
        """Extract output_str and sse_result from a tool result."""
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

    async def _emit_observe_event(
        self,
        tool_name: str,
        call_id: str,
        tool_part: ToolPart,
        tool_def: ToolDefinition,
        sse_result: Any,
        arguments: dict[str, Any],
        start_time: float,
        end_time: float,
    ) -> AsyncIterator[ProcessorEvent]:
        """Emit observe event with optional MCP UI metadata and app result."""
        tool_instance = getattr(tool_def, "_tool_instance", None)
        has_ui = self._check_tool_has_ui(tool_instance, tool_name)
        observe_ui_meta, hydrated_ui_meta = await self._build_observe_ui_metadata(
            tool_instance, tool_name, has_ui
        )

        yield AgentObserveEvent(
            tool_name=tool_name,
            result=sse_result,
            duration_ms=int((end_time - start_time) * 1000),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
            ui_metadata=observe_ui_meta,
        )

        if tool_instance and has_ui:
            async for ev in self._emit_mcp_app_result_event(
                tool_instance, tool_name, tool_part, sse_result, arguments,
                hydrated_ui_meta
            ):
                yield ev

    def _check_tool_has_ui(self, tool_instance: Any, tool_name: str) -> bool:
        """Check if a tool has MCP App UI metadata."""
        if tool_instance is None:
            return False
        has_ui = getattr(tool_instance, "has_ui", False)
        if not has_ui and tool_name.startswith("mcp__"):
            _app_id_fb = getattr(tool_instance, "_app_id", "") or ""
            if _app_id_fb:
                has_ui = True
                logger.debug(
                    "[MCPApp] Fallback: tool %s has app_id=%s but no _ui_metadata",
                    tool_name,
                    _app_id_fb,
                )
        return has_ui

    async def _build_observe_ui_metadata(
        self,
        tool_instance: Any,
        tool_name: str,
        has_ui: bool,
    ) -> tuple[dict | None, dict[str, Any]]:
        """Build observe-level UI metadata. Returns (observe_meta, hydrated_meta)."""
        if not tool_instance or not has_ui:
            return None, {}

        app_id = (
            getattr(tool_instance, "_last_app_id", "")
            or getattr(tool_instance, "_app_id", "")
            or ""
        )
        hydrated = await self._hydrate_mcp_ui_metadata(
            tool_instance=tool_instance,
            app_id=app_id,
            tool_name=tool_name,
        )
        server = getattr(tool_instance, "_server_name", "") or ""
        project_id = (self._langfuse_context or {}).get("project_id", "")
        observe_meta = {
            "resource_uri": self._extract_mcp_resource_uri(hydrated),
            "server_name": server,
            "app_id": app_id,
            "title": hydrated.get("title", ""),
            "project_id": project_id,
        }
        return observe_meta, hydrated

    async def _emit_mcp_app_result_event(
        self,
        tool_instance: Any,
        tool_name: str,
        tool_part: ToolPart,
        sse_result: Any,
        arguments: dict[str, Any],
        hydrated_ui_meta: dict[str, Any],
    ) -> AsyncIterator[ProcessorEvent]:
        """Emit AgentMCPAppResultEvent for tools with UI."""
        ui_meta = hydrated_ui_meta or getattr(tool_instance, "ui_metadata", None) or {}
        app_id = (
            getattr(tool_instance, "_last_app_id", "")
            or getattr(tool_instance, "_app_id", "")
            or ""
        )
        if not app_id:
            app_id = f"_synthetic_{tool_name}"

        resource_html = await self._fetch_resource_html(tool_instance, tool_name)

        logger.debug(
            "[MCPApp] Emitting event: tool=%s, app_id=%s, resource_uri=%s, html_len=%d",
            tool_name,
            app_id,
            self._extract_mcp_resource_uri(ui_meta),
            len(resource_html),
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

    async def _fetch_resource_html(self, tool_instance: Any, tool_name: str) -> str:
        """Fetch live HTML from MCP server, falling back to cached."""
        resource_html = ""
        fetch_fn = getattr(tool_instance, "fetch_resource_html", None)
        if fetch_fn:
            try:
                resource_html = await fetch_fn()
            except Exception as fetch_err:
                logger.warning(
                    "[MCPApp] fetch_resource_html failed for %s: %s",
                    tool_name,
                    fetch_err,
                )
        if not resource_html:
            resource_html = getattr(tool_instance, "_last_html", "") or ""
        return resource_html

    async def _emit_todowrite_events(
        self, tool_name: str, tool_def: ToolDefinition, session_id: str
    ) -> AsyncIterator[ProcessorEvent]:
        """Emit pending task SSE events from todowrite tool."""
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
        """Process a single todowrite pending event."""
        from src.domain.events.agent_events import (
            AgentTaskCompleteEvent,
            AgentTaskListUpdatedEvent,
            AgentTaskStartEvent,
            AgentTaskUpdatedEvent,
        )

        event_type = task_event.get("type")
        if event_type == "task_list_updated":
            async for ev in self._handle_task_list_updated(task_event, AgentTaskListUpdatedEvent, AgentTaskStartEvent):
                yield ev
        elif event_type == "task_updated":
            async for ev in self._handle_task_updated(
                task_event, AgentTaskUpdatedEvent, AgentTaskStartEvent, AgentTaskCompleteEvent
            ):
                yield ev

    async def _handle_task_list_updated(
        self,
        task_event: dict[str, Any],
        ListEvent: type,
        StartEvent: type,
    ) -> AsyncIterator[ProcessorEvent]:
        """Handle task_list_updated event."""
        tasks = task_event["tasks"]
        logger.info(
            f"[Processor] Emitting task_list_updated: "
            f"{len(tasks)} tasks for {task_event['conversation_id']}"
        )
        yield ListEvent(
            conversation_id=task_event["conversation_id"],
            tasks=tasks,
        )
        total = len(tasks)
        for t in tasks:
            if t.get("status") == "in_progress":
                self._current_task = {
                    "task_id": t["id"],
                    "content": t["content"],
                    "order_index": t.get("order_index", 0),
                    "total_tasks": total,
                }
                yield StartEvent(
                    task_id=t["id"],
                    content=t["content"],
                    order_index=t.get("order_index", 0),
                    total_tasks=total,
                )

    async def _handle_task_updated(
        self,
        task_event: dict[str, Any],
        UpdatedEvent: type,
        StartEvent: type,
        CompleteEvent: type,
    ) -> AsyncIterator[ProcessorEvent]:
        """Handle task_updated event."""
        task_status = task_event["status"]
        yield UpdatedEvent(
            conversation_id=task_event["conversation_id"],
            task_id=task_event["task_id"],
            status=task_status,
            content=task_event.get("content"),
        )
        if task_status == "in_progress":
            total = self._current_task["total_tasks"] if self._current_task else 1
            self._current_task = {
                "task_id": task_event["task_id"],
                "content": task_event.get("content", ""),
                "order_index": task_event.get("order_index", 0),
                "total_tasks": total,
            }
            yield StartEvent(
                task_id=task_event["task_id"],
                content=task_event.get("content", ""),
                order_index=task_event.get("order_index", 0),
                total_tasks=total,
            )
        elif task_status in ("completed", "failed", "cancelled"):
            ct = self._current_task
            if ct and ct["task_id"] == task_event["task_id"]:
                yield CompleteEvent(
                    task_id=ct["task_id"],
                    status=task_status,
                    order_index=ct["order_index"],
                    total_tasks=ct["total_tasks"],
                )
                self._current_task = None

    async def _emit_plugin_events(
        self, tool_name: str, tool_def: ToolDefinition, output_str: str
    ) -> AsyncIterator[ProcessorEvent]:
        """Emit pending SSE events from plugin/tool management tools."""
        tool_instance = getattr(tool_def, "_tool_instance", None)
        refresh_count, refresh_status = self._maybe_refresh_tools(tool_name, output_str)

        plugin_tools = {
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
        if tool_name not in plugin_tools:
            return
        if not tool_instance or not hasattr(tool_instance, "consume_pending_events"):
            return

        try:
            for event in tool_instance.consume_pending_events():
                self._enrich_toolset_changed_event(
                    event, tool_name, refresh_status, refresh_count
                )
                yield event
        except Exception as pending_err:
            logger.error(f"{tool_name} event emission failed: {pending_err}")

    def _maybe_refresh_tools(
        self, tool_name: str, output_str: str
    ) -> tuple[int | None, str]:
        """Refresh tools if applicable. Returns (count, status)."""
        if tool_name not in {"plugin_manager", "register_mcp_server"}:
            return None, "not_applicable"

        if isinstance(output_str, str) and not output_str.startswith("Error:"):
            logger.info("[Processor] %s succeeded, refreshing tools", tool_name)
            count = self._refresh_tools()
            status = "success" if count is not None else "failed"
            return count, status

        logger.debug(
            "[Processor] %s failed or returned error, skipping tool refresh",
            tool_name,
        )
        return None, "skipped"

    @staticmethod
    def _enrich_toolset_changed_event(
        event: Any,
        tool_name: str,
        refresh_status: str,
        refresh_count: int | None,
    ) -> None:
        """Enrich toolset_changed event with refresh metadata."""
        if tool_name not in {"plugin_manager", "register_mcp_server"}:
            return
        if not isinstance(event, dict) or event.get("type") != "toolset_changed":
            return
        event_data = event.get("data")
        if not isinstance(event_data, dict):
            return
        event_data.setdefault("refresh_source", "processor")
        event_data["refresh_status"] = refresh_status
        if refresh_count is not None:
            event_data["refreshed_tool_count"] = refresh_count
'''

# ============================================================
# 6. Refactor _process_tool_artifacts()
# PLR0911(9), PLR0912(23), PLR0915(120)
# ============================================================

PROCESS_TOOL_ARTIFACTS_REPLACEMENT = '''\
    async def _process_tool_artifacts(
        self,
        tool_name: str,
        result: Any,
        tool_execution_id: str | None = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Process tool result and extract any artifacts (images, files, etc.).

        This method:
        1. Extracts image/resource content from MCP-style results
        2. Uploads artifacts to storage via ArtifactService
        3. Emits artifact_created events for frontend display

        Args:
            tool_name: Name of the tool that produced the result
            result: Tool execution result (may contain images/resources)
            tool_execution_id: ID of the tool execution

        Yields:
            AgentArtifactCreatedEvent for each artifact created
        """
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

        # Handle export_artifact results
        if result.get("artifact"):
            async for ev in self._process_export_artifact(
                result, tool_name, tool_execution_id, project_id, tenant_id,
                conversation_id, message_id
            ):
                yield ev
            return

        # Handle MCP content array
        async for ev in self._process_mcp_content_artifacts(
            result, tool_name, tool_execution_id, project_id, tenant_id, conversation_id
        ):
            yield ev

    async def _process_export_artifact(
        self,
        result: dict[str, Any],
        tool_name: str,
        tool_execution_id: str | None,
        project_id: str,
        tenant_id: str,
        conversation_id: str | None,
        message_id: str | None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Process export_artifact tool result."""
        artifact_info = result["artifact"]
        has_data = artifact_info.get("data") is not None
        logger.warning(
            f"[ArtifactUpload] tool={tool_name}, has_data={has_data}, "
            f"encoding={artifact_info.get('encoding')}"
        )

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

            self._schedule_artifact_upload(
                file_content, filename, mime_type, category.value, artifact_id,
                tool_execution_id, tool_name, project_id, tenant_id,
                conversation_id, message_id,
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
        """Extract file content bytes from artifact result."""
        import base64

        encoding = artifact_info.get("encoding", "utf-8")
        if encoding == "base64":
            return self._extract_base64_content(result, artifact_info)

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

    @staticmethod
    def _extract_base64_content(
        result: dict[str, Any], artifact_info: dict[str, Any]
    ) -> bytes | None:
        """Extract base64-encoded content from artifact result."""
        import base64

        data = artifact_info.get("data")
        if not data:
            for item in result.get("content", []):
                if item.get("type") == "image":
                    data = item.get("data")
                    break
        if data:
            file_content = base64.b64decode(data)
            logger.warning(f"[ArtifactUpload] Decoded {len(file_content)} bytes from base64")
            return file_content
        logger.warning("[ArtifactUpload] base64 encoding but no data found")
        return None

    def _schedule_artifact_upload(  # noqa: PLR0913
        self,
        file_content: bytes,
        filename: str,
        mime_type: str,
        category_value: str,
        artifact_id: str,
        tool_execution_id: str | None,
        tool_name: str,
        project_id: str,
        tenant_id: str,
        conversation_id: str | None,
        message_id: str | None,
    ) -> None:
        """Schedule artifact upload in background thread."""
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
            """Synchronous S3 upload in a thread pool."""
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
            """Run sync upload in thread, then publish result to Redis and DB."""
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
                conv_id=conversation_id or "",
                msg_id=message_id or "",
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
        result: dict[str, Any],
        tool_name: str,
        tool_execution_id: str | None,
        project_id: str,
        tenant_id: str,
        conversation_id: str | None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Process MCP content array for image/resource artifacts."""
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
            logger.error(f"Error processing artifacts from tool {tool_name}: {e}")
'''

# ============================================================
# Now we need to add the _StepState dataclass before SessionProcessor
# ============================================================

STEP_STATE_CLASS = '''
@dataclass
class _StepState:
    """Mutable state for a single processing step."""

    text_buffer: str = ""
    reasoning_buffer: str = ""
    tool_calls_completed: list[str] = field(default_factory=list)
    step_tokens: TokenUsage = field(default_factory=TokenUsage)
    step_cost: float = 0.0
    finish_reason: str = "stop"

'''


# ============================================================
# Apply replacements
# ============================================================


def apply_replacements():
    with open(SRC, "r") as f:
        lines = f.readlines()

    # Find all method ranges (0-based line indices)
    # We must process from bottom to top to maintain line numbers

    replacements = []

    # 1. process()
    start, end = find_method_range(lines, "process")
    replacements.append((start, end, PROCESS_REPLACEMENT))

    # 2. _evaluate_llm_goal()
    start, end = find_method_range(lines, "_evaluate_llm_goal")
    replacements.append((start, end, EVALUATE_LLM_GOAL_REPLACEMENT))

    # 3. _extract_goal_json()
    start, end = find_method_range(lines, "_extract_goal_json")
    replacements.append((start, end, EXTRACT_GOAL_JSON_REPLACEMENT))

    # 4. _process_step()
    start, end = find_method_range(lines, "_process_step")
    replacements.append((start, end, PROCESS_STEP_REPLACEMENT))

    # 5. _execute_tool()
    start, end = find_method_range(lines, "_execute_tool")
    replacements.append((start, end, EXECUTE_TOOL_REPLACEMENT))

    # 6. _process_tool_artifacts()
    start, end = find_method_range(lines, "_process_tool_artifacts")
    replacements.append((start, end, PROCESS_TOOL_ARTIFACTS_REPLACEMENT))

    # Sort by start line descending (apply from bottom to top)
    replacements.sort(key=lambda x: x[0], reverse=True)

    # Report ranges
    for start, end, _ in replacements:
        method_line = lines[start].strip()
        print(f"  Replacing lines {start + 1}-{end + 1}: {method_line[:60]}...")

    # Apply replacements
    for start, end, replacement in replacements:
        # Replace lines[start:end+1] with replacement
        replacement_lines = replacement.split("\n")
        # Ensure each line ends with \n
        replacement_lines = [line + "\n" for line in replacement_lines]
        # Remove the last empty line if it exists (from trailing \n in template)
        if replacement_lines and replacement_lines[-1].strip() == "":
            replacement_lines = replacement_lines[:-1]

        lines[start : end + 1] = replacement_lines

    # Now insert _StepState class before SessionProcessor class
    # Find "class SessionProcessor:" line
    for i, line in enumerate(lines):
        if line.strip().startswith("class SessionProcessor:"):
            # Insert _StepState before this line
            step_state_lines = [l + "\n" for l in STEP_STATE_CLASS.split("\n")]
            lines[i:i] = step_state_lines
            break

    # Write output
    with open(SRC, "w") as f:
        f.writelines(lines)

    print(f"\nWrote {len(lines)} lines to {SRC}")


if __name__ == "__main__":
    apply_replacements()
