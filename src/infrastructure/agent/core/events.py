"""SSE Event definitions for agent communication."""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

from src.domain.events.agent_events import AgentDomainEvent


class SSEEventType(str, Enum):
    """SSE event types for agent communication."""

    # Status events
    STATUS = "status"
    START = "start"
    COMPLETE = "complete"
    ERROR = "error"

    # Thinking events
    THOUGHT = "thought"
    THOUGHT_DELTA = "thought_delta"

    # Work plan events (multi-level thinking)
    WORK_PLAN = "work_plan"
    STEP_START = "step_start"
    STEP_END = "step_end"

    # Tool events
    ACT = "act"
    OBSERVE = "observe"

    # Text events
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"

    # Message events
    MESSAGE = "message"

    # Permission events
    PERMISSION_ASKED = "permission_asked"
    PERMISSION_REPLIED = "permission_replied"

    # Doom loop events
    DOOM_LOOP_DETECTED = "doom_loop_detected"
    DOOM_LOOP_INTERVENED = "doom_loop_intervened"

    # Human interaction events
    CLARIFICATION_ASKED = "clarification_asked"
    CLARIFICATION_ANSWERED = "clarification_answered"
    DECISION_ASKED = "decision_asked"
    DECISION_ANSWERED = "decision_answered"

    # Cost events
    COST_UPDATE = "cost_update"
    STEP_FINISH = "step_finish"

    # Retry events
    RETRY = "retry"

    # Context events
    COMPACT_NEEDED = "compact_needed"
    CONTEXT_COMPRESSED = "context_compressed"

    # Pattern events
    PATTERN_MATCH = "pattern_match"

    # Skill execution events (L2 layer direct execution)
    SKILL_MATCHED = "skill_matched"
    SKILL_EXECUTION_START = "skill_execution_start"
    SKILL_EXECUTION_COMPLETE = "skill_execution_complete"
    SKILL_FALLBACK = "skill_fallback"

    # Plan Mode events
    PLAN_MODE_ENTER = "plan_mode_enter"
    PLAN_MODE_EXIT = "plan_mode_exit"
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    PLAN_STATUS_CHANGED = "plan_status_changed"


@dataclass
class SSEEvent:
    """
    Server-Sent Event for agent communication.

    Used for real-time streaming of:
    - Thinking process (thoughts, plans, steps)
    - Tool execution (act/observe)
    - Text generation
    - Permission requests
    - Cost updates
    - Errors and retries
    """

    type: SSEEventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_sse_format(self) -> str:
        """
        Convert to SSE wire format.

        Returns:
            String in SSE format: "event: type\ndata: json\n\n"
        """
        event_type = self.type.value if isinstance(self.type, SSEEventType) else self.type
        data_json = json.dumps(
            {
                **self.data,
                "timestamp": self.timestamp,
            },
            ensure_ascii=False,
        )
        return f"event: {event_type}\ndata: {data_json}\n\n"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value if isinstance(self.type, SSEEventType) else self.type,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    @classmethod
    def status(cls, status: str) -> "SSEEvent":
        """Create a status event."""
        return cls(SSEEventType.STATUS, {"status": status})

    @classmethod
    def start(cls) -> "SSEEvent":
        """Create a start event."""
        return cls(SSEEventType.START)

    @classmethod
    def complete(cls, result: Any = None, trace_url: str = None) -> "SSEEvent":
        """Create a complete event."""
        data = {}
        if result:
            data["result"] = result
        if trace_url:
            data["trace_url"] = trace_url
        return cls(SSEEventType.COMPLETE, data)

    @classmethod
    def error(cls, message: str, code: str = None) -> "SSEEvent":
        """Create an error event."""
        data = {"message": message}
        if code:
            data["code"] = code
        return cls(SSEEventType.ERROR, data)

    @classmethod
    def thought(
        cls,
        content: str,
        thought_level: str = "task",
        step_index: int = None,
    ) -> "SSEEvent":
        """Create a thought event."""
        data = {
            "content": content,
            "thought_level": thought_level,
        }
        if step_index is not None:
            data["step_index"] = step_index
        return cls(SSEEventType.THOUGHT, data)

    @classmethod
    def thought_delta(cls, delta: str) -> "SSEEvent":
        """Create a thought delta event."""
        return cls(SSEEventType.THOUGHT_DELTA, {"delta": delta})

    @classmethod
    def work_plan(cls, plan: Dict[str, Any]) -> "SSEEvent":
        """Create a work plan event."""
        # Directly use plan data for frontend compatibility
        return cls(SSEEventType.WORK_PLAN, plan)

    @classmethod
    def step_start(cls, step_index: int, step_description: str) -> "SSEEvent":
        """Create a step start event."""
        return cls(
            SSEEventType.STEP_START,
            {
                "step_index": step_index,
                "description": step_description,
            },
        )

    @classmethod
    def step_end(cls, step_index: int, status: str = "completed") -> "SSEEvent":
        """Create a step end event."""
        return cls(
            SSEEventType.STEP_END,
            {
                "step_index": step_index,
                "status": status,
            },
        )

    @classmethod
    def act(
        cls,
        tool_name: str,
        tool_input: Dict[str, Any] = None,
        call_id: str = None,
        status: str = "running",
    ) -> "SSEEvent":
        """Create a tool action event."""
        data = {
            "tool_name": tool_name,
            "status": status,
        }
        if tool_input:
            data["tool_input"] = tool_input
        if call_id:
            data["call_id"] = call_id
        return cls(SSEEventType.ACT, data)

    @classmethod
    def observe(
        cls,
        tool_name: str,
        result: Any = None,
        error: str = None,
        duration_ms: int = None,
        call_id: str = None,
    ) -> "SSEEvent":
        """Create a tool observation event."""
        data = {"tool_name": tool_name}
        if result is not None:
            data["result"] = result
        if error:
            data["error"] = error
            data["status"] = "error"
        else:
            data["status"] = "completed"
        if duration_ms is not None:
            data["duration_ms"] = duration_ms
        if call_id:
            data["call_id"] = call_id
        return cls(SSEEventType.OBSERVE, data)

    @classmethod
    def text_start(cls) -> "SSEEvent":
        """Create a text start event."""
        return cls(SSEEventType.TEXT_START)

    @classmethod
    def text_delta(cls, delta: str) -> "SSEEvent":
        """Create a text delta event."""
        return cls(SSEEventType.TEXT_DELTA, {"delta": delta})

    @classmethod
    def text_end(cls, full_text: str = None) -> "SSEEvent":
        """Create a text end event."""
        return cls(SSEEventType.TEXT_END, {"full_text": full_text} if full_text else {})

    @classmethod
    def message(cls, role: str, content: str) -> "SSEEvent":
        """Create a message event."""
        return cls(SSEEventType.MESSAGE, {"role": role, "content": content})

    @classmethod
    def permission_asked(
        cls,
        request_id: str,
        permission: str,
        patterns: list,
        metadata: Dict[str, Any] = None,
    ) -> "SSEEvent":
        """Create a permission asked event."""
        return cls(
            SSEEventType.PERMISSION_ASKED,
            {
                "request_id": request_id,
                "permission": permission,
                "patterns": patterns,
                "metadata": metadata or {},
            },
        )

    @classmethod
    def doom_loop_detected(
        cls,
        tool: str,
        input: Dict[str, Any],
    ) -> "SSEEvent":
        """Create a doom loop detected event."""
        return cls(
            SSEEventType.DOOM_LOOP_DETECTED,
            {
                "tool": tool,
                "input": input,
            },
        )

    @classmethod
    def cost_update(
        cls,
        cost: float,
        tokens: Dict[str, int],
    ) -> "SSEEvent":
        """Create a cost update event."""
        return cls(
            SSEEventType.COST_UPDATE,
            {
                "cost": cost,
                "tokens": tokens,
            },
        )

    @classmethod
    def step_finish(
        cls,
        tokens: Dict[str, int],
        cost: float,
        finish_reason: str,
        trace_url: str = None,
    ) -> "SSEEvent":
        """Create a step finish event."""
        data = {
            "tokens": tokens,
            "cost": cost,
            "finish_reason": finish_reason,
        }
        if trace_url:
            data["trace_url"] = trace_url
        return cls(SSEEventType.STEP_FINISH, data)

    @classmethod
    def retry(
        cls,
        attempt: int,
        delay_ms: int,
        message: str,
    ) -> "SSEEvent":
        """Create a retry event."""
        return cls(
            SSEEventType.RETRY,
            {
                "attempt": attempt,
                "delay_ms": delay_ms,
                "message": message,
            },
        )

    @classmethod
    def compact_needed(cls) -> "SSEEvent":
        """Create a compact needed event."""
        return cls(SSEEventType.COMPACT_NEEDED)

    @classmethod
    def context_compressed(
        cls,
        was_compressed: bool,
        compression_strategy: str,
        original_message_count: int,
        final_message_count: int,
        estimated_tokens: int,
        token_budget: int,
        budget_utilization_pct: float,
        summarized_message_count: int = 0,
    ) -> "SSEEvent":
        """
        Create a context compressed event.

        Emitted when context window compression occurs during a conversation.
        Used to notify frontend about compression state for UI feedback.

        Args:
            was_compressed: Whether compression was applied
            compression_strategy: Strategy used (none, truncate, summarize)
            original_message_count: Messages before compression
            final_message_count: Messages after compression
            estimated_tokens: Estimated tokens in final context
            token_budget: Total available token budget
            budget_utilization_pct: Percentage of budget used
            summarized_message_count: Number of messages summarized
        """
        return cls(
            SSEEventType.CONTEXT_COMPRESSED,
            {
                "was_compressed": was_compressed,
                "compression_strategy": compression_strategy,
                "original_message_count": original_message_count,
                "final_message_count": final_message_count,
                "estimated_tokens": estimated_tokens,
                "token_budget": token_budget,
                "budget_utilization_pct": round(budget_utilization_pct, 2),
                "summarized_message_count": summarized_message_count,
            },
        )

    @classmethod
    def pattern_match(
        cls,
        pattern_id: str,
        pattern_name: str,
        confidence: float,
    ) -> "SSEEvent":
        """Create a pattern match event."""
        return cls(
            SSEEventType.PATTERN_MATCH,
            {
                "pattern_id": pattern_id,
                "pattern_name": pattern_name,
                "confidence": confidence,
            },
        )

    # === Human-in-the-Loop Events ===

    @classmethod
    def clarification_asked(
        cls,
        request_id: str,
        question: str,
        clarification_type: str,
        options: list,
        allow_custom: bool = True,
        context: Dict[str, Any] = None,
    ) -> "SSEEvent":
        """
        Create a clarification asked event.

        Emitted when the agent needs clarification from the user during planning.

        Args:
            request_id: Unique identifier for this clarification request
            question: The clarification question to ask the user
            clarification_type: Type of clarification (scope, approach, prerequisite, priority, custom)
            options: List of predefined options (each with id, label, description, recommended)
            allow_custom: Whether user can provide custom text input
            context: Additional context for the clarification
        """
        return cls(
            SSEEventType.CLARIFICATION_ASKED,
            {
                "request_id": request_id,
                "question": question,
                "clarification_type": clarification_type,
                "options": options,
                "allow_custom": allow_custom,
                "context": context or {},
            },
        )

    @classmethod
    def clarification_answered(
        cls,
        request_id: str,
        answer: str,
    ) -> "SSEEvent":
        """
        Create a clarification answered event.

        Emitted when the user responds to a clarification request.

        Args:
            request_id: The request ID that was answered
            answer: The user's answer (option ID or custom text)
        """
        return cls(
            SSEEventType.CLARIFICATION_ANSWERED,
            {
                "request_id": request_id,
                "answer": answer,
            },
        )

    @classmethod
    def decision_asked(
        cls,
        request_id: str,
        question: str,
        decision_type: str,
        options: list,
        allow_custom: bool = False,
        default_option: str = None,
        context: Dict[str, Any] = None,
    ) -> "SSEEvent":
        """
        Create a decision asked event.

        Emitted when the agent needs a decision from the user during execution.

        Args:
            request_id: Unique identifier for this decision request
            question: The decision question to ask the user
            decision_type: Type of decision (branch, method, confirmation, risk, custom)
            options: List of decision options (each with id, label, description, recommended,
                     estimated_time, estimated_cost, risks)
            allow_custom: Whether user can provide custom decision
            default_option: Option to use if timeout occurs
            context: Additional context for the decision
        """
        return cls(
            SSEEventType.DECISION_ASKED,
            {
                "request_id": request_id,
                "question": question,
                "decision_type": decision_type,
                "options": options,
                "allow_custom": allow_custom,
                "default_option": default_option,
                "context": context or {},
            },
        )

    @classmethod
    def decision_answered(
        cls,
        request_id: str,
        decision: str,
    ) -> "SSEEvent":
        """
        Create a decision answered event.

        Emitted when the user responds to a decision request.

        Args:
            request_id: The request ID that was answered
            decision: The user's decision (option ID or custom text)
        """
        return cls(
            SSEEventType.DECISION_ANSWERED,
            {
                "request_id": request_id,
                "decision": decision,
            },
        )

    @classmethod
    def doom_loop_intervened(
        cls,
        request_id: str,
        action: str,
    ) -> "SSEEvent":
        """
        Create a doom loop intervened event.

        Emitted when the user responds to a doom loop intervention request.

        Args:
            request_id: The intervention request ID
            action: The user's action ('continue' or 'stop')
        """
        return cls(
            SSEEventType.DOOM_LOOP_INTERVENED,
            {
                "request_id": request_id,
                "action": action,
            },
        )

    # === Skill Execution Events (L2 Layer) ===

    @classmethod
    def skill_matched(
        cls,
        skill_id: str,
        skill_name: str,
        tools: list,
        match_score: float,
        execution_mode: str,
    ) -> "SSEEvent":
        """
        Create a skill matched event.

        Emitted when a skill is matched to a user query.

        Args:
            skill_id: The matched skill's ID
            skill_name: The matched skill's name
            tools: List of tool names in the skill
            match_score: The match score (0-1)
            execution_mode: 'direct' for SkillExecutor or 'prompt' for prompt injection
        """
        return cls(
            SSEEventType.SKILL_MATCHED,
            {
                "skill_id": skill_id,
                "skill_name": skill_name,
                "tools": tools,
                "match_score": match_score,
                "execution_mode": execution_mode,
            },
        )

    @classmethod
    def skill_execution_start(
        cls,
        skill_id: str,
        skill_name: str,
        tools: list,
        query: str,
    ) -> "SSEEvent":
        """
        Create a skill execution start event.

        Emitted when a skill starts direct execution via SkillExecutor.

        Args:
            skill_id: The skill's ID
            skill_name: The skill's name
            tools: List of tool names to be executed
            query: The user query that triggered execution
        """
        return cls(
            SSEEventType.SKILL_EXECUTION_START,
            {
                "skill_id": skill_id,
                "skill_name": skill_name,
                "tools": tools,
                "query": query,
            },
        )

    @classmethod
    def skill_execution_complete(
        cls,
        skill_id: str,
        skill_name: str,
        success: bool,
        tool_results: list,
        execution_time_ms: int,
        summary: str = None,
        error: str = None,
    ) -> "SSEEvent":
        """
        Create a skill execution complete event.

        Emitted when a skill finishes direct execution.

        Args:
            skill_id: The skill's ID
            skill_name: The skill's name
            success: Whether the execution was successful
            tool_results: List of tool execution results
            execution_time_ms: Total execution time in milliseconds
            summary: Optional summary of results
            error: Optional error message if failed
        """
        data = {
            "skill_id": skill_id,
            "skill_name": skill_name,
            "success": success,
            "tool_results": tool_results,
            "execution_time_ms": execution_time_ms,
        }
        if summary:
            data["summary"] = summary
        if error:
            data["error"] = error
        return cls(SSEEventType.SKILL_EXECUTION_COMPLETE, data)

    @classmethod
    def skill_fallback(
        cls,
        skill_name: str,
        reason: str,
        error: str = None,
    ) -> "SSEEvent":
        """
        Create a skill fallback event.

        Emitted when skill direct execution fails and falls back to LLM.

        Args:
            skill_name: The skill's name
            reason: Reason for fallback (e.g., 'execution_failed')
            error: Optional error message
        """
        data = {
            "skill_name": skill_name,
            "reason": reason,
        }
        if error:
            data["error"] = error
        return cls(SSEEventType.SKILL_FALLBACK, data)

    # === Plan Mode Events ===

    @classmethod
    def plan_mode_enter(
        cls,
        conversation_id: str,
        plan_id: str,
        plan_title: str,
    ) -> "SSEEvent":
        """
        Create a plan mode enter event.

        Emitted when the agent enters Plan Mode.

        Args:
            conversation_id: The conversation ID
            plan_id: The plan document ID
            plan_title: The plan title
        """
        return cls(
            SSEEventType.PLAN_MODE_ENTER,
            {
                "conversation_id": conversation_id,
                "plan_id": plan_id,
                "plan_title": plan_title,
            },
        )

    @classmethod
    def plan_mode_exit(
        cls,
        conversation_id: str,
        plan_id: str,
        plan_status: str,
        approved: bool,
    ) -> "SSEEvent":
        """
        Create a plan mode exit event.

        Emitted when the agent exits Plan Mode.

        Args:
            conversation_id: The conversation ID
            plan_id: The plan document ID
            plan_status: The final plan status
            approved: Whether the plan was approved
        """
        return cls(
            SSEEventType.PLAN_MODE_EXIT,
            {
                "conversation_id": conversation_id,
                "plan_id": plan_id,
                "plan_status": plan_status,
                "approved": approved,
            },
        )

    @classmethod
    def plan_created(
        cls,
        plan_id: str,
        title: str,
        conversation_id: str,
    ) -> "SSEEvent":
        """
        Create a plan created event.

        Emitted when a new plan document is created.

        Args:
            plan_id: The plan document ID
            title: The plan title
            conversation_id: The associated conversation ID
        """
        return cls(
            SSEEventType.PLAN_CREATED,
            {
                "plan_id": plan_id,
                "title": title,
                "conversation_id": conversation_id,
            },
        )

    @classmethod
    def plan_updated(
        cls,
        plan_id: str,
        content: str,
        version: int,
    ) -> "SSEEvent":
        """
        Create a plan updated event.

        Emitted when a plan document content is updated.

        Args:
            plan_id: The plan document ID
            content: The updated content (Markdown)
            version: The new version number
        """
        return cls(
            SSEEventType.PLAN_UPDATED,
            {
                "plan_id": plan_id,
                "content": content,
                "version": version,
            },
        )

    @classmethod
    def plan_status_changed(
        cls,
        plan_id: str,
        old_status: str,
        new_status: str,
    ) -> "SSEEvent":
        """
        Create a plan status changed event.

        Emitted when a plan document status changes.

        Args:
            plan_id: The plan document ID
            old_status: Previous status
            new_status: New status
        """
        return cls(
            SSEEventType.PLAN_STATUS_CHANGED,
            {
                "plan_id": plan_id,
                "old_status": old_status,
                "new_status": new_status,
            },
        )

    @staticmethod
    def from_domain_event(event: AgentDomainEvent) -> "SSEEvent":
        """Convert a domain event to an SSE event."""
        # Extract data by dumping the model, excluding type and timestamp
        data = event.model_dump(exclude={"event_type", "timestamp"})
        
        # Handle special cases where domain model fields might differ slightly from SSE expectations
        # For now, we assume they are compatible as we designed them to be
        
        return SSEEvent(
            type=SSEEventType(event.event_type.value),
            data=data,
            timestamp=event.timestamp,
        )
