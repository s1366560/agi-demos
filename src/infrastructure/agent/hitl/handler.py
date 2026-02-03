"""
HITL Handler - Human-in-the-Loop Tool Handling for ReActAgent.

This module provides centralized HITL tool handling logic, extracted from
SessionProcessor to support the Single Responsibility Principle.

Handles:
- Clarification tool (ask_clarification)
- Decision tool (request_decision)
- Environment variable tool (request_env_var)

Each tool follows the pattern:
1. Parse arguments and create request
2. Register request with manager
3. Emit "asked" event for frontend display
4. Wait for user response with timeout
5. Process response and emit result events

Reference: Extracted from processor.py HITL handlers (lines 1461-2067)
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol

from src.domain.events.agent_events import (
    AgentClarificationAnsweredEvent,
    AgentClarificationAskedEvent,
    AgentDecisionAnsweredEvent,
    AgentDecisionAskedEvent,
    AgentDomainEvent,
    AgentEnvVarProvidedEvent,
    AgentEnvVarRequestedEvent,
    AgentObserveEvent,
)

logger = logging.getLogger(__name__)


# ============================================================
# Enums and Data Classes
# ============================================================


class HITLToolType(Enum):
    """Types of HITL tools."""

    CLARIFICATION = "ask_clarification"
    DECISION = "request_decision"
    ENV_VAR = "request_env_var"


class ToolState(Enum):
    """Tool execution states."""

    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class HITLContext:
    """
    Context for HITL operations.

    Attributes:
        tenant_id: Tenant identifier
        project_id: Project identifier
        conversation_id: Conversation identifier
        message_id: Message identifier
    """

    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
        }


# ============================================================
# Protocols
# ============================================================


class ToolPartLike(Protocol):
    """Protocol for tool part objects to track state."""

    @property
    def tool_execution_id(self) -> Optional[str]:
        ...

    @property
    def status(self) -> Any:
        ...

    @status.setter
    def status(self, value: Any) -> None:
        ...

    @property
    def output(self) -> Any:
        ...

    @output.setter
    def output(self, value: Any) -> None:
        ...

    @property
    def error(self) -> Optional[str]:
        ...

    @error.setter
    def error(self, value: Optional[str]) -> None:
        ...

    @property
    def end_time(self) -> Optional[float]:
        ...

    @end_time.setter
    def end_time(self, value: Optional[float]) -> None:
        ...


class HITLManagerLike(Protocol):
    """Protocol for HITL managers (clarification, decision, env_var)."""

    async def register_request(
        self,
        request: Any,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        timeout: float = 300.0,
    ) -> None:
        ...

    async def wait_for_response(
        self,
        request_id: str,
        timeout: float = 300.0,
        default_response: Optional[str] = None,
    ) -> Any:
        ...

    async def unregister_request(self, request_id: str) -> None:
        ...


# ============================================================
# HITL Handler
# ============================================================


class HITLHandler:
    """
    Handles Human-in-the-Loop (HITL) tool execution.

    Provides unified handling for HITL tools including clarification,
    decision, and environment variable requests.

    Usage:
        handler = HITLHandler()

        async for event in handler.handle_clarification(
            session_id="sess-123",
            call_id="call-456",
            arguments={"question": "Which option?", "options": [...]},
            tool_part=tool_part,
            context=HITLContext(tenant_id="t1", project_id="p1"),
        ):
            yield event
    """

    def __init__(self, debug_logging: bool = False):
        """
        Initialize the HITL handler.

        Args:
            debug_logging: Whether to enable debug logging
        """
        self._debug_logging = debug_logging

    async def handle_clarification(
        self,
        session_id: str,
        call_id: str,
        arguments: Dict[str, Any],
        tool_part: ToolPartLike,
        context: HITLContext,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Handle clarification tool with SSE event emission.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            arguments: Tool arguments
            tool_part: Tool part for tracking state
            context: HITL context with tenant/project info

        Yields:
            AgentDomainEvent objects for clarification flow
        """
        from ..tools.clarification import (
            ClarificationOption,
            ClarificationRequest,
            ClarificationType,
            get_clarification_manager,
        )

        manager = get_clarification_manager()
        tool_name = HITLToolType.CLARIFICATION.value
        start_time = time.time()

        try:
            # Parse arguments
            question = arguments.get("question", "")
            clarification_type = arguments.get("clarification_type", "custom")
            options_raw = arguments.get("options", [])
            allow_custom = arguments.get("allow_custom", True)
            context_raw = arguments.get("context", {})
            timeout = arguments.get("timeout", 300.0)

            # Normalize context
            request_context = self._normalize_context(context_raw, context)

            # Create request ID
            request_id = f"clarif_{uuid.uuid4().hex[:8]}"

            # Convert options
            clarification_options = self._convert_clarification_options(options_raw)

            # Create request object
            try:
                clarif_type = ClarificationType(clarification_type)
            except ValueError:
                clarif_type = ClarificationType.CUSTOM

            option_objects = [
                ClarificationOption(
                    id=opt["id"],
                    label=opt["label"],
                    description=opt.get("description"),
                    recommended=opt.get("recommended", False),
                )
                for opt in clarification_options
            ]

            request = ClarificationRequest(
                request_id=request_id,
                question=question,
                clarification_type=clarif_type,
                options=option_objects,
                allow_custom=allow_custom,
                context=request_context,
            )

            # Register request
            await manager.register_request(
                request,
                tenant_id=context.tenant_id,
                project_id=context.project_id,
                conversation_id=context.conversation_id,
                message_id=context.message_id,
                timeout=timeout,
            )

            # Emit asked event BEFORE blocking
            yield AgentClarificationAskedEvent(
                request_id=request_id,
                question=question,
                clarification_type=clarification_type,
                options=clarification_options,
                allow_custom=allow_custom,
                context=request_context,
            )

            # Wait for response
            try:
                answer = await manager.wait_for_response(request_id, timeout=timeout)
                end_time = time.time()

                # Emit answered event
                yield AgentClarificationAnsweredEvent(
                    request_id=request_id,
                    answer=answer,
                )

                # Update tool part
                self._complete_tool_part(tool_part, answer, end_time)

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    result=answer,
                    duration_ms=int((end_time - start_time) * 1000),
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

            except asyncio.TimeoutError:
                self._error_tool_part(tool_part, "Clarification request timed out")

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error="Clarification request timed out",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

            finally:
                await manager.unregister_request(request_id)

        except Exception as e:
            logger.error(f"Clarification tool error: {e}", exc_info=True)
            self._error_tool_part(tool_part, str(e))

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=str(e),
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

    async def handle_decision(
        self,
        session_id: str,
        call_id: str,
        arguments: Dict[str, Any],
        tool_part: ToolPartLike,
        context: HITLContext,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Handle decision tool with SSE event emission.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            arguments: Tool arguments
            tool_part: Tool part for tracking state
            context: HITL context with tenant/project info

        Yields:
            AgentDomainEvent objects for decision flow
        """
        from ..tools.decision import (
            DecisionOption,
            DecisionRequest,
            DecisionType,
            get_decision_manager,
        )

        manager = get_decision_manager()
        tool_name = HITLToolType.DECISION.value
        start_time = time.time()

        try:
            # Parse arguments
            question = arguments.get("question", "")
            decision_type = arguments.get("decision_type", "custom")
            options_raw = arguments.get("options", [])
            allow_custom = arguments.get("allow_custom", False)
            default_option = arguments.get("default_option")
            context_raw = arguments.get("context", {})
            timeout = arguments.get("timeout", 300.0)

            # Normalize context
            request_context = self._normalize_context(context_raw, context)

            # Create request ID
            request_id = f"decision_{uuid.uuid4().hex[:8]}"

            # Convert options
            decision_options = self._convert_decision_options(options_raw)

            # Create request object
            try:
                dec_type = DecisionType(decision_type)
            except ValueError:
                dec_type = DecisionType.CUSTOM

            option_objects = [
                DecisionOption(
                    id=opt["id"],
                    label=opt["label"],
                    description=opt.get("description"),
                    recommended=opt.get("recommended", False),
                    estimated_time=opt.get("estimated_time"),
                    estimated_cost=opt.get("estimated_cost"),
                    risks=opt.get("risks", []),
                )
                for opt in decision_options
            ]

            request = DecisionRequest(
                request_id=request_id,
                question=question,
                decision_type=dec_type,
                options=option_objects,
                allow_custom=allow_custom,
                default_option=default_option,
                context=request_context,
            )

            # Register request
            await manager.register_request(
                request,
                tenant_id=context.tenant_id,
                project_id=context.project_id,
                conversation_id=context.conversation_id,
                message_id=context.message_id,
                timeout=timeout,
            )

            # Emit asked event BEFORE blocking
            yield AgentDecisionAskedEvent(
                request_id=request_id,
                question=question,
                decision_type=decision_type,
                options=decision_options,
                allow_custom=allow_custom,
                default_option=default_option,
                context=request_context,
            )

            # Wait for response
            try:
                decision = await manager.wait_for_response(
                    request_id, timeout=timeout, default_response=default_option
                )
                end_time = time.time()

                # Emit answered event
                yield AgentDecisionAnsweredEvent(
                    request_id=request_id,
                    decision=decision,
                )

                # Update tool part
                self._complete_tool_part(tool_part, decision, end_time)

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    result=decision,
                    duration_ms=int((end_time - start_time) * 1000),
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

            except asyncio.TimeoutError:
                self._error_tool_part(tool_part, "Decision request timed out")

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error="Decision request timed out",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

            finally:
                await manager.unregister_request(request_id)

        except Exception as e:
            logger.error(f"Decision tool error: {e}", exc_info=True)
            self._error_tool_part(tool_part, str(e))

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=str(e),
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

    async def handle_env_var(
        self,
        session_id: str,
        call_id: str,
        arguments: Dict[str, Any],
        tool_part: ToolPartLike,
        context: HITLContext,
        save_callback: Optional[Any] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Handle environment variable tool with SSE event emission.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            arguments: Tool arguments
            tool_part: Tool part for tracking state
            context: HITL context with tenant/project info
            save_callback: Optional callback for saving env vars to database

        Yields:
            AgentDomainEvent objects for env var request flow
        """
        from ..tools.env_var_tools import (
            EnvVarRequest,
            get_env_var_manager,
        )

        manager = get_env_var_manager()
        tool_name = HITLToolType.ENV_VAR.value
        start_time = time.time()

        try:
            # Parse arguments
            target_tool_name = arguments.get("tool_name", "")
            fields_raw = arguments.get("fields", [])
            message = arguments.get("message")
            context_raw = arguments.get("context", {})
            timeout = arguments.get("timeout", 300.0)
            save_to_project = arguments.get("save_to_project", False)

            # Normalize context
            request_context = self._normalize_context(context_raw, context)

            # Create request ID
            request_id = f"envvar_{uuid.uuid4().hex[:8]}"

            # Convert fields
            fields_for_sse, env_var_fields = self._convert_env_var_fields(fields_raw)

            # Create request object
            request = EnvVarRequest(
                request_id=request_id,
                tool_name=target_tool_name,
                fields=env_var_fields,
                context=request_context,
            )

            # Register request
            await manager.register_request(
                request,
                tenant_id=context.tenant_id,
                project_id=context.project_id,
                conversation_id=context.conversation_id,
                message_id=context.message_id,
                timeout=timeout,
            )

            # Emit requested event BEFORE blocking
            yield AgentEnvVarRequestedEvent(
                request_id=request_id,
                tool_name=target_tool_name,
                fields=fields_for_sse,
                context=request_context,
            )

            # Wait for response
            try:
                values = await manager.wait_for_response(request_id, timeout=timeout)
                end_time = time.time()

                # Save env vars if callback provided
                saved_variables = []
                if save_callback and values:
                    try:
                        saved_variables = await save_callback(
                            values=values,
                            target_tool_name=target_tool_name,
                            env_var_fields=env_var_fields,
                            tenant_id=context.tenant_id,
                            project_id=context.project_id if save_to_project else None,
                        )
                    except Exception as e:
                        logger.error(f"Error saving env vars: {e}")
                        saved_variables = list(values.keys()) if values else []
                else:
                    saved_variables = list(values.keys()) if values else []

                # Emit provided event
                yield AgentEnvVarProvidedEvent(
                    request_id=request_id,
                    tool_name=target_tool_name,
                    saved_variables=saved_variables,
                )

                # Update tool part
                result = {
                    "success": True,
                    "tool_name": target_tool_name,
                    "saved_variables": saved_variables,
                    "message": f"Successfully saved {len(saved_variables)} environment variable(s)",
                }
                self._complete_tool_part(tool_part, json.dumps(result), end_time)

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    result=result,
                    duration_ms=int((end_time - start_time) * 1000),
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

            except asyncio.TimeoutError:
                self._error_tool_part(tool_part, "Environment variable request timed out")

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error="Environment variable request timed out",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

            finally:
                await manager.unregister_request(request_id)

        except Exception as e:
            logger.error(f"Environment variable tool error: {e}", exc_info=True)
            self._error_tool_part(tool_part, str(e))

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=str(e),
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

    def is_hitl_tool(self, tool_name: str) -> bool:
        """
        Check if tool name is an HITL tool.

        Args:
            tool_name: Tool name to check

        Returns:
            True if tool is an HITL tool
        """
        try:
            HITLToolType(tool_name)
            return True
        except ValueError:
            return False

    def get_hitl_tool_type(self, tool_name: str) -> Optional[HITLToolType]:
        """
        Get HITL tool type from tool name.

        Args:
            tool_name: Tool name

        Returns:
            HITLToolType or None if not an HITL tool
        """
        try:
            return HITLToolType(tool_name)
        except ValueError:
            return None

    # ============================================================
    # Helper Methods
    # ============================================================

    def _normalize_context(
        self,
        context_raw: Any,
        hitl_context: HITLContext,
    ) -> Dict[str, Any]:
        """Normalize context from tool arguments."""
        if isinstance(context_raw, str):
            context = {"description": context_raw} if context_raw else {}
        elif isinstance(context_raw, dict):
            context = context_raw.copy()
        else:
            context = {}

        # Add conversation_id for cross-process resolution
        if hitl_context.conversation_id:
            context["conversation_id"] = hitl_context.conversation_id

        return context

    def _convert_clarification_options(
        self, options_raw: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert raw options to clarification options format."""
        return [
            {
                "id": opt.get("id", ""),
                "label": opt.get("label", ""),
                "description": opt.get("description"),
                "recommended": opt.get("recommended", False),
            }
            for opt in options_raw
        ]

    def _convert_decision_options(
        self, options_raw: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert raw options to decision options format."""
        return [
            {
                "id": opt.get("id", ""),
                "label": opt.get("label", ""),
                "description": opt.get("description"),
                "recommended": opt.get("recommended", False),
                "estimated_time": opt.get("estimated_time"),
                "estimated_cost": opt.get("estimated_cost"),
                "risks": opt.get("risks", []),
            }
            for opt in options_raw
        ]

    def _convert_env_var_fields(
        self, fields_raw: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], List[Any]]:
        """Convert raw fields to env var fields format."""
        from ..tools.env_var_tools import EnvVarField, EnvVarInputType

        fields_for_sse = []
        env_var_fields = []

        for field in fields_raw:
            var_name = field.get("variable_name", field.get("name", ""))
            display_name = field.get("display_name", field.get("label", var_name))
            input_type_str = field.get("input_type", "text")

            # Create field dict for SSE
            field_dict = {
                "name": var_name,
                "label": display_name,
                "description": field.get("description"),
                "required": field.get("is_required", field.get("required", True)),
                "input_type": input_type_str,
                "default_value": field.get("default_value"),
                "placeholder": field.get("placeholder"),
            }
            fields_for_sse.append(field_dict)

            # Create EnvVarField for manager
            try:
                input_type = EnvVarInputType(input_type_str)
            except ValueError:
                input_type = EnvVarInputType.TEXT

            env_var_fields.append(
                EnvVarField(
                    variable_name=var_name,
                    display_name=display_name,
                    description=field.get("description"),
                    input_type=input_type,
                    is_required=field.get("is_required", field.get("required", True)),
                    default_value=field.get("default_value"),
                )
            )

        return fields_for_sse, env_var_fields

    def _complete_tool_part(
        self, tool_part: ToolPartLike, output: Any, end_time: float
    ) -> None:
        """Mark tool part as completed."""
        tool_part.status = ToolState.COMPLETED
        tool_part.output = output
        tool_part.end_time = end_time

    def _error_tool_part(self, tool_part: ToolPartLike, error: str) -> None:
        """Mark tool part as errored."""
        tool_part.status = ToolState.ERROR
        tool_part.error = error
        tool_part.end_time = time.time()


# ============================================================
# Module-level Singleton
# ============================================================

_default_handler: Optional[HITLHandler] = None


def get_hitl_handler() -> HITLHandler:
    """Get the default HITL handler singleton."""
    global _default_handler
    if _default_handler is None:
        _default_handler = HITLHandler()
    return _default_handler


def set_hitl_handler(handler: HITLHandler) -> None:
    """Set the default HITL handler singleton."""
    global _default_handler
    _default_handler = handler
