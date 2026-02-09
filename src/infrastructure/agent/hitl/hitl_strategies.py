"""HITL Type Strategies for Human-in-the-Loop operations.

Strategy pattern implementations for handling different HITL request types
(clarification, decision, env_var, permission).
"""

import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.domain.model.agent.hitl_types import (
    ClarificationOption,
    ClarificationType,
    DecisionOption,
    DecisionType,
    EnvVarField,
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
        clarification_type = ClarificationType(request_data.get("clarification_type", "custom"))

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
        if request.clarification_data and request.clarification_data.options:
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
        return False
