"""
Temporal HITL Handler - Unified handler for Human-in-the-Loop operations.

This module provides a unified HITL handler that works with Temporal workflows.
It replaces the legacy managers (ClarificationManager, DecisionManager, EnvVarManager)
with a single, streamlined implementation.

Architecture:
    Agent Processor → TemporalHITLHandler → Temporal Activity (SSE) → Frontend
    Frontend → REST API → Temporal Signal → Workflow → Response

Key Features:
- Unified handling for all HITL types (clarification, decision, env_var, permission)
- Temporal-native: uses Activities and Signals
- SSE events for real-time frontend updates
- Strategy pattern for type-specific logic
"""

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, TypeVar

from src.domain.model.agent.hitl_types import (
    ClarificationOption,
    ClarificationType,
    DecisionOption,
    DecisionType,
    EnvVarField,
    HITLPendingException,
    HITLRequest,
    HITLType,
    PermissionAction,
    RiskLevel,
    create_clarification_request,
    create_decision_request,
    create_env_var_request,
    create_permission_request,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# HITL Type Strategies
# =============================================================================


class HITLTypeStrategy(ABC):
    """Base strategy for handling a specific HITL type."""

    @property
    @abstractmethod
    def hitl_type(self) -> HITLType:
        """Get the HITL type this strategy handles."""
        pass

    @abstractmethod
    def generate_request_id(self) -> str:
        """Generate a unique request ID."""
        pass

    @abstractmethod
    def create_request(
        self,
        conversation_id: str,
        request_data: Dict[str, Any],
        **kwargs,
    ) -> HITLRequest:
        """Create an HITL request from raw data."""
        pass

    @abstractmethod
    def extract_response_value(
        self,
        response_data: Dict[str, Any],
    ) -> Any:
        """Extract the usable response value from response data."""
        pass

    @abstractmethod
    def get_default_response(
        self,
        request: HITLRequest,
    ) -> Any:
        """Get a default response for timeout scenarios."""
        pass


class ClarificationStrategy(HITLTypeStrategy):
    """Strategy for clarification requests."""

    @property
    def hitl_type(self) -> HITLType:
        return HITLType.CLARIFICATION

    def generate_request_id(self) -> str:
        return f"clar_{uuid.uuid4().hex[:8]}"

    def create_request(
        self,
        conversation_id: str,
        request_data: Dict[str, Any],
        **kwargs,
    ) -> HITLRequest:
        question = request_data.get("question", "")
        options_data = request_data.get("options", [])
        clarification_type = ClarificationType(
            request_data.get("clarification_type", "custom")
        )

        options = []
        for opt in options_data:
            if isinstance(opt, dict):
                options.append(
                    ClarificationOption(
                        id=opt.get("id", str(len(options))),
                        label=opt.get("label", ""),
                        description=opt.get("description"),
                        recommended=opt.get("recommended", False),
                    )
                )
            elif isinstance(opt, str):
                options.append(
                    ClarificationOption(
                        id=str(len(options)),
                        label=opt,
                    )
                )

        # Use provided request_id if available, otherwise generate
        request_id = request_data.get("_request_id") or self.generate_request_id()

        return create_clarification_request(
            request_id=request_id,
            conversation_id=conversation_id,
            question=question,
            options=options,
            clarification_type=clarification_type,
            allow_custom=request_data.get("allow_custom", True),
            timeout_seconds=kwargs.get("timeout_seconds", 300.0),
            tenant_id=kwargs.get("tenant_id"),
            project_id=kwargs.get("project_id"),
            message_id=kwargs.get("message_id"),
            context=request_data.get("context", {}),
        )

    def extract_response_value(self, response_data: Dict[str, Any]) -> Any:
        return response_data.get("answer", "")

    def get_default_response(self, request: HITLRequest) -> Any:
        if request.clarification_data and request.clarification_data.default_value:
            return request.clarification_data.default_value
        if (
            request.clarification_data
            and request.clarification_data.options
        ):
            # Return first recommended or first option
            for opt in request.clarification_data.options:
                if opt.recommended:
                    return opt.id
            return request.clarification_data.options[0].id
        return ""


class DecisionStrategy(HITLTypeStrategy):
    """Strategy for decision requests."""

    @property
    def hitl_type(self) -> HITLType:
        return HITLType.DECISION

    def generate_request_id(self) -> str:
        return f"deci_{uuid.uuid4().hex[:8]}"

    def create_request(
        self,
        conversation_id: str,
        request_data: Dict[str, Any],
        **kwargs,
    ) -> HITLRequest:
        question = request_data.get("question", "")
        options_data = request_data.get("options", [])
        decision_type = DecisionType(request_data.get("decision_type", "single_choice"))

        options = []
        for opt in options_data:
            if isinstance(opt, dict):
                risk_level = None
                if opt.get("risk_level"):
                    risk_level = RiskLevel(opt["risk_level"])

                options.append(
                    DecisionOption(
                        id=opt.get("id", str(len(options))),
                        label=opt.get("label", ""),
                        description=opt.get("description"),
                        recommended=opt.get("recommended", False),
                        risk_level=risk_level,
                        estimated_time=opt.get("estimated_time"),
                        estimated_cost=opt.get("estimated_cost"),
                        risks=opt.get("risks", []),
                    )
                )
            elif isinstance(opt, str):
                options.append(
                    DecisionOption(
                        id=str(len(options)),
                        label=opt,
                    )
                )

        # Use provided request_id if available, otherwise generate
        request_id = request_data.get("_request_id") or self.generate_request_id()

        return create_decision_request(
            request_id=request_id,
            conversation_id=conversation_id,
            question=question,
            options=options,
            decision_type=decision_type,
            allow_custom=request_data.get("allow_custom", False),
            timeout_seconds=kwargs.get("timeout_seconds", 300.0),
            tenant_id=kwargs.get("tenant_id"),
            project_id=kwargs.get("project_id"),
            message_id=kwargs.get("message_id"),
            context=request_data.get("context", {}),
            default_option=request_data.get("default_option"),
            max_selections=request_data.get("max_selections"),
        )

    def extract_response_value(self, response_data: Dict[str, Any]) -> Any:
        return response_data.get("decision", "")

    def get_default_response(self, request: HITLRequest) -> Any:
        if request.decision_data and request.decision_data.default_option:
            return request.decision_data.default_option
        if request.decision_data and request.decision_data.options:
            for opt in request.decision_data.options:
                if opt.recommended:
                    return opt.id
            return request.decision_data.options[0].id
        return ""


class EnvVarStrategy(HITLTypeStrategy):
    """Strategy for environment variable requests."""

    @property
    def hitl_type(self) -> HITLType:
        return HITLType.ENV_VAR

    def generate_request_id(self) -> str:
        return f"env_{uuid.uuid4().hex[:8]}"

    def create_request(
        self,
        conversation_id: str,
        request_data: Dict[str, Any],
        **kwargs,
    ) -> HITLRequest:
        from src.domain.model.agent.hitl_types import EnvVarInputType

        tool_name = request_data.get("tool_name", "unknown")
        fields_data = request_data.get("fields", [])
        message = request_data.get("message")

        fields = []
        for f in fields_data:
            if isinstance(f, dict):
                input_type = EnvVarInputType.TEXT
                if f.get("input_type"):
                    input_type = EnvVarInputType(f["input_type"])
                elif f.get("secret"):
                    input_type = EnvVarInputType.PASSWORD

                fields.append(
                    EnvVarField(
                        name=f.get("name", ""),
                        label=f.get("label", f.get("name", "")),
                        description=f.get("description"),
                        required=f.get("required", True),
                        secret=f.get("secret", False),
                        input_type=input_type,
                        default_value=f.get("default_value"),
                        placeholder=f.get("placeholder"),
                        pattern=f.get("pattern"),
                    )
                )

        return create_env_var_request(
            request_id=self.generate_request_id(),
            conversation_id=conversation_id,
            tool_name=tool_name,
            fields=fields,
            message=message,
            timeout_seconds=kwargs.get("timeout_seconds", 300.0),
            tenant_id=kwargs.get("tenant_id"),
            project_id=kwargs.get("project_id"),
            message_id=kwargs.get("message_id"),
            context=request_data.get("context", {}),
            allow_save=request_data.get("allow_save", True),
        )

    def extract_response_value(self, response_data: Dict[str, Any]) -> Any:
        return response_data.get("values", {})

    def get_default_response(self, request: HITLRequest) -> Any:
        # Return empty dict - env vars have no sensible default
        return {}


class PermissionStrategy(HITLTypeStrategy):
    """Strategy for permission requests."""

    @property
    def hitl_type(self) -> HITLType:
        return HITLType.PERMISSION

    def generate_request_id(self) -> str:
        return f"perm_{uuid.uuid4().hex[:8]}"

    def create_request(
        self,
        conversation_id: str,
        request_data: Dict[str, Any],
        **kwargs,
    ) -> HITLRequest:
        tool_name = request_data.get("tool_name", "unknown")
        action = request_data.get("action", "execute")
        risk_level = RiskLevel(request_data.get("risk_level", "medium"))

        default_action = None
        if request_data.get("default_action"):
            default_action = PermissionAction(request_data["default_action"])

        return create_permission_request(
            request_id=self.generate_request_id(),
            conversation_id=conversation_id,
            tool_name=tool_name,
            action=action,
            risk_level=risk_level,
            timeout_seconds=kwargs.get("timeout_seconds", 60.0),
            tenant_id=kwargs.get("tenant_id"),
            project_id=kwargs.get("project_id"),
            message_id=kwargs.get("message_id"),
            details=request_data.get("details", {}),
            description=request_data.get("description"),
            allow_remember=request_data.get("allow_remember", True),
            default_action=default_action,
            context=request_data.get("context", {}),
        )

    def extract_response_value(self, response_data: Dict[str, Any]) -> Any:
        action = response_data.get("action", "deny")
        return action in ("allow", "allow_always")

    def get_default_response(self, request: HITLRequest) -> Any:
        if request.permission_data and request.permission_data.default_action:
            return request.permission_data.default_action.value in (
                "allow",
                "allow_always",
            )
        # Default to deny for safety
        return False


# =============================================================================
# Temporal HITL Handler
# =============================================================================


class TemporalHITLHandler:
    """
    Unified HITL handler for Temporal-based workflows.

    This handler replaces the legacy managers with a simpler, unified approach.
    It uses the Strategy pattern for type-specific behavior while maintaining
    a consistent interface.

    Usage (within processor):
        handler = TemporalHITLHandler(
            conversation_id="conv-123",
            tenant_id="tenant-456",
            project_id="project-789",
        )

        # Request clarification
        response = await handler.request_clarification(
            question="Which approach do you prefer?",
            options=["Option A", "Option B"],
        )

        # Request decision
        response = await handler.request_decision(
            question="How should we proceed?",
            options=[{"id": "1", "label": "Safe", "recommended": True}],
        )
    """

    # Strategy registry
    _strategies: Dict[HITLType, HITLTypeStrategy] = {
        HITLType.CLARIFICATION: ClarificationStrategy(),
        HITLType.DECISION: DecisionStrategy(),
        HITLType.ENV_VAR: EnvVarStrategy(),
        HITLType.PERMISSION: PermissionStrategy(),
    }

    def __init__(
        self,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        message_id: Optional[str] = None,
        default_timeout: float = 300.0,
        emit_sse_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        preinjected_response: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the HITL handler.

        Args:
            conversation_id: Current conversation ID
            tenant_id: Tenant ID for multi-tenancy
            project_id: Project ID for scoping
            message_id: Current message ID (optional)
            default_timeout: Default timeout in seconds
            emit_sse_callback: Callback for emitting SSE events (fallback)
            preinjected_response: Optional pre-injected HITL response for resume
                Format: {"request_id": "...", "hitl_type": "...", "response_data": {...}}
        """
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.message_id = message_id
        self.default_timeout = default_timeout
        self._emit_sse_callback = emit_sse_callback
        
        # Pre-injected response for HITL resume (used once then cleared)
        self._preinjected_response = preinjected_response

        # Track pending requests
        self._pending_requests: Dict[str, HITLRequest] = {}

    def _get_strategy(self, hitl_type: HITLType) -> HITLTypeStrategy:
        """Get the strategy for a given HITL type."""
        strategy = self._strategies.get(hitl_type)
        if not strategy:
            raise ValueError(f"No strategy registered for HITL type: {hitl_type}")
        return strategy

    # =========================================================================
    # High-Level Request Methods
    # =========================================================================

    async def request_clarification(
        self,
        question: str,
        options: Optional[List[Any]] = None,
        clarification_type: str = "custom",
        allow_custom: bool = True,
        timeout_seconds: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
        default_value: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        """
        Request clarification from the user.

        Args:
            question: The question to ask
            options: List of options (strings or dicts)
            clarification_type: Type of clarification
            allow_custom: Whether to allow custom input
            timeout_seconds: Timeout override
            context: Additional context
            default_value: Default value for timeout
            request_id: Optional pre-generated request ID

        Returns:
            User's answer
        """
        request_data = {
            "question": question,
            "options": options or [],
            "clarification_type": clarification_type,
            "allow_custom": allow_custom,
            "context": context or {},
            "default_value": default_value,
        }
        
        # Use provided request_id if given
        if request_id:
            request_data["_request_id"] = request_id

        response = await self._execute_hitl_request(
            HITLType.CLARIFICATION,
            request_data,
            timeout_seconds or self.default_timeout,
        )
        return response

    async def request_decision(
        self,
        question: str,
        options: List[Any],
        decision_type: str = "single_choice",
        allow_custom: bool = False,
        timeout_seconds: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
        default_option: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        """
        Request a decision from the user.

        Args:
            question: The decision question
            options: List of options (dicts with id, label, etc.)
            decision_type: Type of decision
            allow_custom: Whether to allow custom input
            timeout_seconds: Timeout override
            context: Additional context
            default_option: Default option ID for timeout
            request_id: Optional pre-generated request ID

        Returns:
            Selected option ID
        """
        request_data = {
            "question": question,
            "options": options,
            "decision_type": decision_type,
            "allow_custom": allow_custom,
            "context": context or {},
            "default_option": default_option,
        }
        
        # Use provided request_id if given
        if request_id:
            request_data["_request_id"] = request_id

        response = await self._execute_hitl_request(
            HITLType.DECISION,
            request_data,
            timeout_seconds or self.default_timeout,
        )
        return response

    async def request_env_vars(
        self,
        tool_name: str,
        fields: List[Dict[str, Any]],
        message: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        allow_save: bool = True,
    ) -> Dict[str, str]:
        """
        Request environment variables from the user.

        Args:
            tool_name: Name of the tool needing env vars
            fields: List of field definitions
            message: Custom message to display
            timeout_seconds: Timeout override
            allow_save: Whether to allow saving for future sessions

        Returns:
            Dict mapping variable name to value
        """
        request_data = {
            "tool_name": tool_name,
            "fields": fields,
            "message": message,
            "allow_save": allow_save,
        }

        response = await self._execute_hitl_request(
            HITLType.ENV_VAR,
            request_data,
            timeout_seconds or self.default_timeout,
        )
        return response

    async def request_permission(
        self,
        tool_name: str,
        action: str,
        risk_level: str = "medium",
        description: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
        allow_remember: bool = True,
    ) -> bool:
        """
        Request permission for a tool action.

        Args:
            tool_name: Name of the tool
            action: Description of the action
            risk_level: Risk level (low, medium, high, critical)
            description: Detailed description
            details: Additional details
            timeout_seconds: Timeout override
            allow_remember: Whether to allow remembering the decision

        Returns:
            True if permission granted, False otherwise
        """
        request_data = {
            "tool_name": tool_name,
            "action": action,
            "risk_level": risk_level,
            "description": description,
            "details": details or {},
            "allow_remember": allow_remember,
        }

        response = await self._execute_hitl_request(
            HITLType.PERMISSION,
            request_data,
            timeout_seconds or 60.0,  # Shorter default for permissions
        )
        return response

    # =========================================================================
    # Core HITL Execution
    # =========================================================================

    async def _execute_hitl_request(
        self,
        hitl_type: HITLType,
        request_data: Dict[str, Any],
        timeout_seconds: float,
    ) -> Any:
        """
        Execute an HITL request through Temporal.

        This is the core method that:
        1. Checks for pre-injected response (resume case)
        2. Creates the HITL request
        3. Emits SSE event via Temporal Activity
        4. Waits for response via Temporal Signal
        5. Returns the response value

        Args:
            hitl_type: Type of HITL request
            request_data: Type-specific request data
            timeout_seconds: Timeout in seconds

        Returns:
            Response value (type depends on hitl_type)
        """
        strategy = self._get_strategy(hitl_type)
        
        # Check for pre-injected response (HITL resume case)
        # This happens when continue_project_chat_activity restores agent state
        # and the tool is called again - we should return the cached response
        if self._preinjected_response:
            preinjected = self._preinjected_response
            preinjected_type = preinjected.get("hitl_type", "")
            preinjected_data = preinjected.get("response_data", {})
            
            # Type must match (clarification, decision, env_var, permission)
            if preinjected_type == hitl_type.value:
                logger.info(
                    f"[TemporalHITL] Using pre-injected response for {hitl_type.value}: "
                    f"request_id={preinjected.get('request_id')}"
                )
                # Clear the pre-injected response (use once only)
                self._preinjected_response = None
                # Extract and return the response value
                return strategy.extract_response_value(preinjected_data)
            else:
                logger.warning(
                    f"[TemporalHITL] Pre-injected response type mismatch: "
                    f"expected={hitl_type.value}, got={preinjected_type}"
                )

        # Create the request
        request = strategy.create_request(
            conversation_id=self.conversation_id,
            request_data=request_data,
            timeout_seconds=timeout_seconds,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            message_id=self.message_id,
        )

        logger.info(
            f"[TemporalHITL] Creating {hitl_type.value} request: {request.request_id}"
        )

        # Track pending request
        self._pending_requests[request.request_id] = request

        try:
            # Execute Temporal Activity to create request and emit SSE
            from temporalio import activity

            if activity.in_activity():
                # We're in an activity - use direct approach
                response_data = await self._execute_in_activity(request, timeout_seconds)
            else:
                # We're in workflow context - use activities
                response_data = await self._execute_in_workflow(request, timeout_seconds)

            # Extract response value using strategy
            if response_data.get("cancelled"):
                logger.warning(f"[TemporalHITL] Request cancelled: {request.request_id}")
                return strategy.get_default_response(request)

            if response_data.get("timeout"):
                logger.warning(f"[TemporalHITL] Request timeout: {request.request_id}")
                return strategy.get_default_response(request)

            response_value = strategy.extract_response_value(response_data)
            logger.info(
                f"[TemporalHITL] Got response for {request.request_id}: {type(response_value)}"
            )
            return response_value

        finally:
            # Clean up tracking
            self._pending_requests.pop(request.request_id, None)

    async def _execute_in_activity(
        self,
        request: HITLRequest,
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        """
        Execute HITL request from within a Temporal activity.

        Instead of returning a pending marker, this method now raises
        HITLPendingException to properly pause the Agent execution loop.
        The exception is caught by the processor and propagated up to the
        Workflow, which will then wait for the user response via Signal.
        """
        from datetime import datetime

        from src.infrastructure.adapters.secondary.temporal.activities.hitl import (
            _emit_hitl_sse_event,
            _persist_hitl_request,
        )

        # Persist request to database first
        await _persist_hitl_request(
            request_id=request.request_id,
            hitl_type=request.hitl_type,
            conversation_id=request.conversation_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            message_id=request.message_id,
            timeout_seconds=timeout_seconds,
            type_data=request.type_specific_data,
            created_at=datetime.utcnow(),
        )

        # Emit SSE event to frontend
        await _emit_hitl_sse_event(
            request_id=request.request_id,
            hitl_type=request.hitl_type,
            conversation_id=request.conversation_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            type_data=request.type_specific_data,
            timeout_seconds=timeout_seconds,
        )

        logger.info(
            f"[TemporalHITL] Raising HITLPendingException for request: {request.request_id}"
        )

        # Raise exception to pause Agent execution and signal Workflow to wait
        raise HITLPendingException(
            request_id=request.request_id,
            hitl_type=request.hitl_type,
            request_data=request.type_specific_data,
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            timeout_seconds=timeout_seconds,
        )

    async def _execute_in_workflow(
        self,
        request: HITLRequest,
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        """Execute HITL request from within a Temporal workflow."""

        from temporalio import workflow
        from temporalio.common import RetryPolicy

        # Import activities
        with workflow.unsafe.imports_passed_through():
            from src.infrastructure.adapters.secondary.temporal.activities.hitl import (
                create_hitl_request_activity,
            )

        # Create request via activity (persists and emits SSE)
        result = await workflow.execute_activity(
            create_hitl_request_activity,
            {
                "hitl_type": request.hitl_type.value,
                "conversation_id": request.conversation_id,
                "tenant_id": self.tenant_id,
                "project_id": self.project_id,
                "message_id": request.message_id,
                "timeout_seconds": timeout_seconds,
                "type_specific_data": request.type_specific_data,
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if result.get("status") != "created":
            logger.error(f"[TemporalHITL] Failed to create request: {result}")
            return {"error": "Failed to create HITL request"}

        # The workflow needs to wait for the signal
        # This happens in ProjectAgentWorkflow._wait_for_hitl_response
        # Return the request info for the workflow to use
        return {
            "pending": True,
            "request_id": result["request_id"],
            "created_at": result["created_at"],
        }

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_pending_requests(self) -> List[HITLRequest]:
        """Get all pending HITL requests."""
        return list(self._pending_requests.values())

    def has_pending_requests(self) -> bool:
        """Check if there are pending requests."""
        return len(self._pending_requests) > 0

    async def cancel_all_pending(self, reason: str = "Handler cleanup") -> None:
        """Cancel all pending HITL requests."""
        for request_id in list(self._pending_requests.keys()):
            await self.cancel_request(request_id, reason)

    async def cancel_request(
        self,
        request_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Cancel a specific HITL request."""
        if request_id not in self._pending_requests:
            return False

        logger.info(f"[TemporalHITL] Cancelling request: {request_id}")

        # Emit cancellation SSE event
        if self._emit_sse_callback:
            await self._emit_sse_callback(
                "hitl_cancelled",
                {
                    "request_id": request_id,
                    "reason": reason,
                },
            )

        self._pending_requests.pop(request_id, None)
        return True


# =============================================================================
# Factory Function
# =============================================================================


def create_hitl_handler(
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    message_id: Optional[str] = None,
    emit_sse_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
) -> TemporalHITLHandler:
    """
    Create a new TemporalHITLHandler instance.

    This is the recommended way to create handlers to ensure consistent
    configuration.

    Args:
        conversation_id: Current conversation ID
        tenant_id: Tenant ID
        project_id: Project ID
        message_id: Current message ID (optional)
        emit_sse_callback: Callback for emitting SSE events

    Returns:
        Configured TemporalHITLHandler instance
    """
    return TemporalHITLHandler(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        project_id=project_id,
        message_id=message_id,
        emit_sse_callback=emit_sse_callback,
    )
