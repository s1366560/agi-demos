"""
Tool Executor - Core tool execution with permission checking and doom loop detection.

Encapsulates:
- Tool execution with permission checking
- Doom loop detection and intervention
- Error handling for truncated/malformed arguments
- Result processing and artifact extraction
- HITL tool delegation

Extracted from processor.py to reduce complexity and improve testability.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Protocol

from src.domain.events.agent_events import (
    AgentArtifactCreatedEvent,
    AgentDomainEvent,
    AgentDoomLoopDetectedEvent,
    AgentObserveEvent,
    AgentPermissionAskedEvent,
)

logger = logging.getLogger(__name__)


def _strip_artifact_binary(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of an artifact result with binary/base64 data removed."""
    cleaned = {**result}
    if "artifact" in cleaned and isinstance(cleaned["artifact"], dict):
        artifact = {**cleaned["artifact"]}
        artifact.pop("data", None)
        cleaned["artifact"] = artifact
    if "content" in cleaned and isinstance(cleaned["content"], list):
        stripped = []
        for item in cleaned["content"]:
            if isinstance(item, dict) and item.get("type") in ("image", "resource"):
                item = {**item}
                item.pop("data", None)
            stripped.append(item)
        cleaned["content"] = stripped
    return cleaned


# ============================================================================
# Protocol Definitions
# ============================================================================


class ToolDefinitionProtocol(Protocol):
    """Protocol for tool definitions."""

    name: str
    permission: Optional[str]

    async def execute(self, **kwargs: Any) -> Any:  # noqa: ANN401
        """Execute the tool."""
        ...


class ToolPartProtocol(Protocol):
    """Protocol for tool call part."""

    status: Any  # ToolState
    error: Optional[str]
    output: Optional[str]
    start_time: float
    end_time: Optional[float]
    tool_execution_id: str


class DoomLoopDetectorProtocol(Protocol):
    """Protocol for doom loop detector."""

    def should_intervene(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Check if doom loop intervention is needed."""
        ...

    def record(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        """Record a tool call for detection."""
        ...


class PermissionManagerProtocol(Protocol):
    """Protocol for permission manager."""

    def evaluate(self, permission: str, pattern: str) -> Any:
        """Evaluate permission rule."""
        ...

    async def ask(
        self,
        permission: str,
        patterns: List[str],
        session_id: str,
        metadata: Dict[str, Any],
    ) -> str:
        """Ask for permission. Returns 'approve' or 'reject'."""
        ...


class ArtifactServiceProtocol(Protocol):
    """Protocol for artifact service."""

    async def upload_artifact(
        self,
        content: bytes,
        filename: str,
        content_type: str,
        project_id: str,
        tenant_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Upload an artifact and return metadata."""
        ...


# ============================================================================
# Data Classes
# ============================================================================


class ToolState(str, Enum):
    """Tool execution states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class PermissionAction(str, Enum):
    """Permission action types."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class ExecutionContext:
    """Context for tool execution."""

    session_id: str
    project_id: Optional[str] = None
    tenant_id: Optional[str] = None
    conversation_id: Optional[str] = None
    permission_timeout: float = 60.0


@dataclass
class ExecutionResult:
    """Result of tool execution."""

    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0
    artifacts: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================================
# Helper Functions
# ============================================================================


def escape_control_chars(s: str) -> str:
    """Escape control characters in a JSON string."""
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    return s


def parse_raw_arguments(raw_args: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to parse raw JSON arguments with multiple strategies.

    Args:
        raw_args: Raw JSON string to parse

    Returns:
        Parsed dict or None if all attempts fail
    """
    # Try 1: Direct parse
    try:
        return json.loads(raw_args)
    except json.JSONDecodeError:
        pass

    # Try 2: Escape control characters and parse
    try:
        fixed_args = escape_control_chars(raw_args)
        return json.loads(fixed_args)
    except json.JSONDecodeError:
        pass

    # Try 3: Handle double-encoded JSON
    try:
        if raw_args.startswith('"') and raw_args.endswith('"'):
            inner = raw_args[1:-1]
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
            return json.loads(inner)
    except json.JSONDecodeError:
        pass

    return None


# ============================================================================
# HITL Tool Names
# ============================================================================

HITL_TOOLS = frozenset({"ask_clarification", "request_decision", "request_env_var"})


def is_hitl_tool(tool_name: str) -> bool:
    """Check if tool is a Human-in-the-Loop tool."""
    return tool_name in HITL_TOOLS


# ============================================================================
# Tool Executor
# ============================================================================


class ToolExecutor:
    """
    Core tool execution handler.

    Responsibilities:
    - Execute tools with permission checking
    - Handle doom loop detection and intervention
    - Process truncated/malformed arguments
    - Delegate HITL tools to appropriate handlers
    - Extract artifacts from tool results
    """

    def __init__(
        self,
        doom_loop_detector: DoomLoopDetectorProtocol,
        permission_manager: PermissionManagerProtocol,
        artifact_service: Optional[ArtifactServiceProtocol] = None,
        debug_logging: bool = False,
    ):
        """
        Initialize tool executor.

        Args:
            doom_loop_detector: Detector for repetitive tool calls
            permission_manager: Manager for permission checking
            artifact_service: Optional service for artifact uploads
            debug_logging: Enable verbose debug logging
        """
        self._doom_loop_detector = doom_loop_detector
        self._permission_manager = permission_manager
        self._artifact_service = artifact_service
        self._debug_logging = debug_logging

    async def execute(
        self,
        tool_name: str,
        tool_def: ToolDefinitionProtocol,
        arguments: Dict[str, Any],
        tool_part: ToolPartProtocol,
        context: ExecutionContext,
        call_id: str,
        work_plan_steps: Optional[List[Dict[str, Any]]] = None,
        tool_to_step_mapping: Optional[Dict[str, int]] = None,
        hitl_callback: Optional[
            Callable[[str, str, str, Dict[str, Any], ToolPartProtocol], AsyncIterator[AgentDomainEvent]]
        ] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Execute a tool with full lifecycle management.

        Args:
            tool_name: Name of tool to execute
            tool_def: Tool definition with execute function
            arguments: Tool arguments
            tool_part: Tool call tracking part
            context: Execution context
            call_id: Tool call ID
            work_plan_steps: Optional work plan steps
            tool_to_step_mapping: Optional tool to step mapping
            hitl_callback: Optional callback for HITL tools

        Yields:
            Domain events from execution
        """
        work_plan_steps = work_plan_steps or []
        tool_to_step_mapping = tool_to_step_mapping or {}

        # Check doom loop first
        doom_loop_rejected = False
        async for event in self._check_doom_loop(
            tool_name=tool_name,
            arguments=arguments,
            tool_part=tool_part,
            context=context,
            call_id=call_id,
        ):
            yield event
            if isinstance(event, AgentObserveEvent) and event.error:
                doom_loop_rejected = True

        if doom_loop_rejected:
            return

        # Record tool call for doom loop detection
        self._doom_loop_detector.record(tool_name, arguments)

        # Handle HITL tools via callback
        if is_hitl_tool(tool_name) and hitl_callback:
            async for event in hitl_callback(
                context.session_id, call_id, tool_name, arguments, tool_part
            ):
                yield event
            return

        # Check permission
        permission_rejected = False
        async for event in self._check_permission(
            tool_name=tool_name,
            tool_def=tool_def,
            arguments=arguments,
            tool_part=tool_part,
            context=context,
            call_id=call_id,
        ):
            yield event
            if isinstance(event, AgentObserveEvent) and event.error:
                permission_rejected = True

        if permission_rejected:
            return

        # Validate and fix arguments
        arguments, error = self._validate_arguments(tool_name, arguments)
        if error:
            self._mark_tool_error(tool_part, error)
            yield AgentObserveEvent(
                tool_name=tool_name,
                error=error,
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )
            return

        # Execute the tool
        async for event in self._do_execute(
            tool_name=tool_name,
            tool_def=tool_def,
            arguments=arguments,
            tool_part=tool_part,
            context=context,
            call_id=call_id,
            work_plan_steps=work_plan_steps,
            tool_to_step_mapping=tool_to_step_mapping,
        ):
            yield event

    async def _check_doom_loop(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_part: ToolPartProtocol,
        context: ExecutionContext,
        call_id: str,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Check for doom loop and handle intervention."""
        if not self._doom_loop_detector.should_intervene(tool_name, arguments):
            return

        # Emit doom loop detected
        yield AgentDoomLoopDetectedEvent(tool=tool_name, input=arguments)

        # Ask for permission to continue
        try:
            permission_result = await asyncio.wait_for(
                self._permission_manager.ask(
                    permission="doom_loop",
                    patterns=[tool_name],
                    session_id=context.session_id,
                    metadata={"tool": tool_name, "input": arguments},
                ),
                timeout=context.permission_timeout,
            )

            if permission_result == "reject":
                self._mark_tool_error(tool_part, "Doom loop detected and rejected by user")
                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error="Doom loop detected and rejected",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

        except asyncio.TimeoutError:
            self._mark_tool_error(tool_part, "Permission request timed out")
            yield AgentObserveEvent(
                tool_name=tool_name,
                error="Permission request timed out",
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

    async def _check_permission(
        self,
        tool_name: str,
        tool_def: ToolDefinitionProtocol,
        arguments: Dict[str, Any],
        tool_part: ToolPartProtocol,
        context: ExecutionContext,
        call_id: str,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Check tool permission and handle ASK flow."""
        if not tool_def.permission:
            return

        permission_rule = self._permission_manager.evaluate(
            permission=tool_def.permission,
            pattern=tool_name,
        )

        if permission_rule.action == PermissionAction.DENY:
            error = f"Permission denied: {tool_def.permission}"
            self._mark_tool_error(tool_part, error)
            yield AgentObserveEvent(
                tool_name=tool_name,
                error=error,
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )
            return

        if permission_rule.action == PermissionAction.ASK:
            # Request permission
            yield AgentPermissionAskedEvent(
                request_id=f"perm_{uuid.uuid4().hex[:8]}",
                permission=tool_def.permission,
                patterns=[tool_name],
                metadata={"tool": tool_name, "input": arguments},
            )

            try:
                permission_result = await asyncio.wait_for(
                    self._permission_manager.ask(
                        permission=tool_def.permission,
                        patterns=[tool_name],
                        session_id=context.session_id,
                        metadata={"tool": tool_name, "input": arguments},
                    ),
                    timeout=context.permission_timeout,
                )

                if permission_result == "reject":
                    self._mark_tool_error(tool_part, "Permission rejected by user")
                    yield AgentObserveEvent(
                        tool_name=tool_name,
                        error="Permission rejected by user",
                        call_id=call_id,
                        tool_execution_id=tool_part.tool_execution_id,
                    )

            except asyncio.TimeoutError:
                self._mark_tool_error(tool_part, "Permission request timed out")
                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error="Permission request timed out",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

    def _validate_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Optional[str]]:
        """
        Validate and fix tool arguments.

        Returns:
            Tuple of (validated_arguments, error_message)
        """
        # Handle truncated arguments
        if "_error" in arguments and arguments.get("_error") == "truncated":
            error_msg = arguments.get(
                "_message", "Tool arguments were truncated. The content may be too large."
            )
            return arguments, error_msg

        # Handle _raw arguments (from failed JSON parsing)
        if "_raw" in arguments and len(arguments) == 1:
            raw_args = arguments["_raw"]

            if self._debug_logging:
                preview = raw_args[:200] if len(raw_args) > 200 else raw_args
                logger.debug(f"[ToolExecutor] Attempting to parse _raw arguments: {preview}...")

            parsed = parse_raw_arguments(raw_args)
            if parsed is not None:
                return parsed, None
            else:
                preview = raw_args[:500] if len(raw_args) > 500 else raw_args
                return arguments, f"Invalid JSON in tool arguments. Raw arguments preview: {preview}"

        return arguments, None

    async def _do_execute(
        self,
        tool_name: str,
        tool_def: ToolDefinitionProtocol,
        arguments: Dict[str, Any],
        tool_part: ToolPartProtocol,
        context: ExecutionContext,
        call_id: str,
        work_plan_steps: List[Dict[str, Any]],
        tool_to_step_mapping: Dict[str, int],
    ) -> AsyncIterator[AgentDomainEvent]:
        """Execute the tool and process results."""
        try:
            start_time = time.time()
            result = await tool_def.execute(**arguments)
            end_time = time.time()

            # Process result format
            output_str, sse_result = self._process_result(result)

            # Update tool part
            tool_part.status = ToolState.COMPLETED
            tool_part.output = output_str
            tool_part.end_time = end_time

            # Update work plan step status
            step_number = tool_to_step_mapping.get(tool_name)
            if step_number is not None and step_number < len(work_plan_steps):
                work_plan_steps[step_number]["status"] = "completed"

            # Emit observe event
            yield AgentObserveEvent(
                tool_name=tool_name,
                result=sse_result,
                duration_ms=int((end_time - start_time) * 1000),
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

            # Process artifacts
            async for artifact_event in self._process_artifacts(
                tool_name=tool_name,
                result=result,
                tool_execution_id=tool_part.tool_execution_id,
                context=context,
            ):
                yield artifact_event

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)

            self._mark_tool_error(tool_part, str(e))

            # Update work plan step status
            step_number = tool_to_step_mapping.get(tool_name)
            if step_number is not None and step_number < len(work_plan_steps):
                work_plan_steps[step_number]["status"] = "failed"

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=str(e),
                duration_ms=int((time.time() - tool_part.start_time) * 1000)
                if tool_part.start_time
                else None,
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

    # Max bytes for tool output stored in LLM context
    _MAX_TOOL_OUTPUT_BYTES = 30_000

    # Regex matching long base64-like sequences (256+ chars)
    _BASE64_PATTERN = re.compile(r'[A-Za-z0-9+/=]{256,}')

    def _process_result(self, result: Any) -> tuple[str, Any]:
        """
        Process tool result into output string and SSE result.

        Returns:
            Tuple of (output_string, sse_result)
        """
        if isinstance(result, dict) and "artifact" in result:
            # Artifact result - use summary, never serialize base64 to LLM context
            artifact = result["artifact"]
            output_str = result.get(
                "output",
                f"Exported artifact: {artifact.get('filename', 'unknown')} "
                f"({artifact.get('mime_type', 'unknown')}, "
                f"{artifact.get('size', 0)} bytes)",
            )
            return self._sanitize_tool_output(output_str), _strip_artifact_binary(result)
        elif isinstance(result, dict) and "output" in result:
            output_str = result.get("output", "")
            return self._sanitize_tool_output(output_str), result
        elif isinstance(result, str):
            return self._sanitize_tool_output(result), result
        else:
            return self._sanitize_tool_output(json.dumps(result)), result

    def _sanitize_tool_output(self, output: str) -> str:
        """Sanitize tool output to prevent binary/base64 data from entering LLM context."""
        if not output:
            return output

        sanitized = self._BASE64_PATTERN.sub("[binary data omitted]", output)

        encoded = sanitized.encode("utf-8", errors="replace")
        if len(encoded) > self._MAX_TOOL_OUTPUT_BYTES:
            sanitized = encoded[: self._MAX_TOOL_OUTPUT_BYTES].decode(
                "utf-8", errors="ignore"
            )
            sanitized += "\n... [output truncated]"

        return sanitized

    def _mark_tool_error(self, tool_part: ToolPartProtocol, error: str) -> None:
        """Mark tool part as error."""
        tool_part.status = ToolState.ERROR
        tool_part.error = error
        tool_part.end_time = time.time()

    async def _process_artifacts(
        self,
        tool_name: str,
        result: Any,
        tool_execution_id: Optional[str],
        context: ExecutionContext,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Process and upload artifacts from tool result."""
        if not self._artifact_service:
            return

        if not context.project_id or not context.tenant_id:
            if self._debug_logging:
                logger.debug(
                    "[ToolExecutor] Missing project_id or tenant_id for artifact processing"
                )
            return

        # Import artifact extractor
        from src.infrastructure.agent.artifact.extractor import (
            ExtractionContext,
            get_artifact_extractor,
        )

        extractor = get_artifact_extractor()
        extraction_context = ExtractionContext(
            project_id=context.project_id,
            tenant_id=context.tenant_id,
            conversation_id=context.conversation_id,
        )

        async for artifact in extractor.process(
            tool_name=tool_name,
            result=result,
            context=extraction_context,
            tool_execution_id=tool_execution_id,
        ):
            try:
                # Upload artifact
                upload_result = await self._artifact_service.upload_artifact(
                    content=artifact.content,
                    filename=artifact.filename or f"artifact_{uuid.uuid4().hex[:8]}",
                    content_type=artifact.content_type,
                    project_id=context.project_id,
                    tenant_id=context.tenant_id,
                    metadata={
                        "tool_name": tool_name,
                        "tool_execution_id": tool_execution_id,
                        "conversation_id": context.conversation_id,
                        "category": artifact.category,
                    },
                )

                yield AgentArtifactCreatedEvent(
                    artifact_id=upload_result.get("artifact_id", ""),
                    filename=artifact.filename,
                    content_type=artifact.content_type,
                    url=upload_result.get("url", ""),
                    metadata={
                        "tool_name": tool_name,
                        "category": artifact.category,
                    },
                )

            except Exception as e:
                logger.error(f"Failed to upload artifact: {e}", exc_info=True)


# ============================================================================
# Singleton Management
# ============================================================================

_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """
    Get singleton ToolExecutor instance.

    Raises:
        RuntimeError if executor not initialized
    """
    global _executor
    if _executor is None:
        raise RuntimeError(
            "ToolExecutor not initialized. Call set_tool_executor() or create_tool_executor() first."
        )
    return _executor


def set_tool_executor(executor: ToolExecutor) -> None:
    """Set singleton ToolExecutor instance."""
    global _executor
    _executor = executor


def create_tool_executor(
    doom_loop_detector: DoomLoopDetectorProtocol,
    permission_manager: PermissionManagerProtocol,
    artifact_service: Optional[ArtifactServiceProtocol] = None,
    debug_logging: bool = False,
) -> ToolExecutor:
    """
    Create and set singleton ToolExecutor.

    Args:
        doom_loop_detector: Doom loop detector instance
        permission_manager: Permission manager instance
        artifact_service: Optional artifact service
        debug_logging: Enable debug logging

    Returns:
        Created ToolExecutor instance
    """
    global _executor
    _executor = ToolExecutor(
        doom_loop_detector=doom_loop_detector,
        permission_manager=permission_manager,
        artifact_service=artifact_service,
        debug_logging=debug_logging,
    )
    return _executor
