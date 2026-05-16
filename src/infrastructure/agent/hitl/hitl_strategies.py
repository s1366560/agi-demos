"""HITL Type Strategies for Human-in-the-Loop operations.

Strategy pattern implementations for handling different HITL request types
(clarification, decision, env_var, permission).
"""

import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from typing import Any

from src.domain.model.agent.hitl_types import (
    A2UIActionRequestData,
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
from src.infrastructure.agent.hitl.utils import (
    build_env_var_request_context,
    normalize_env_var_name,
    sanitize_env_var_plain_text,
    sanitize_env_var_text,
    sanitize_hitl_context,
    sanitize_hitl_text,
)

logger = logging.getLogger(__name__)


class HITLTypeStrategy(ABC):
    """Base strategy for handling a specific HITL type."""

    @property
    @abstractmethod
    def hitl_type(self) -> HITLType:
        """Get the HITL type this strategy handles."""

    @abstractmethod
    def generate_request_id(self) -> str:
        """Generate a unique request ID."""

    @abstractmethod
    def create_request(
        self,
        conversation_id: str,
        request_data: dict[str, Any],
        **kwargs: Any,
    ) -> HITLRequest:
        """Create an HITL request from raw data."""

    @abstractmethod
    def extract_response_value(
        self,
        response_data: object,
    ) -> Any:
        """Extract the usable response value from response data."""

    @abstractmethod
    def get_default_response(
        self,
        request: HITLRequest,
    ) -> Any:
        """Get a default response for timeout scenarios."""


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
        request_data: dict[str, Any],
        **kwargs: Any,
    ) -> HITLRequest:
        question = sanitize_hitl_text(request_data.get("question", "")) or ""
        options_data = request_data.get("options", []) or []
        clarification_type = ClarificationType(request_data.get("clarification_type", "custom"))

        options: list[ClarificationOption] = []
        for opt in options_data:
            if isinstance(opt, dict):
                label = sanitize_hitl_text(opt.get("label", ""))
                if label is None:
                    continue
                options.append(
                    ClarificationOption(
                        id=str(opt.get("id", str(len(options)))).strip() or str(len(options)),
                        label=label,
                        description=sanitize_hitl_text(opt.get("description")),
                        recommended=opt.get("recommended", False),
                    )
                )
            elif isinstance(opt, str):
                label = sanitize_hitl_text(opt)
                if label is None:
                    continue
                options.append(
                    ClarificationOption(
                        id=str(len(options)),
                        label=label,
                    )
                )

        # Auto-enable allow_custom when options are empty
        allow_custom = request_data.get("allow_custom", True)
        if not options:
            allow_custom = True
        request_id = request_data.get("_request_id") or self.generate_request_id()
        sanitized_default_value = sanitize_hitl_text(
            kwargs.get("default_value", request_data.get("default_value"))
        )

        return create_clarification_request(
            request_id=request_id,
            conversation_id=conversation_id,
            question=question,
            options=options,
            clarification_type=clarification_type,
            allow_custom=allow_custom,
            timeout_seconds=kwargs.get("timeout_seconds", 300.0),
            tenant_id=kwargs.get("tenant_id"),
            project_id=kwargs.get("project_id"),
            message_id=kwargs.get("message_id"),
            context=sanitize_hitl_context(request_data.get("context", {})),
            default_value=sanitized_default_value,
        )

    def extract_response_value(self, response_data: object) -> Any:
        if isinstance(response_data, str):
            return sanitize_hitl_text(response_data) or ""
        if not isinstance(response_data, dict):
            return ""
        answer = response_data.get("answer", "")
        if isinstance(answer, list):
            sanitized_answers: list[str] = []
            for item in answer:
                sanitized_item = sanitize_hitl_text(item)
                if sanitized_item is not None:
                    sanitized_answers.append(sanitized_item)
            return sanitized_answers
        return sanitize_hitl_text(answer) or ""

    def get_default_response(self, request: HITLRequest) -> Any:
        if request.clarification_data and request.clarification_data.default_value:
            return request.clarification_data.default_value
        if request.clarification_data and request.clarification_data.options:
            for opt in request.clarification_data.options:
                if opt.recommended:
                    return opt.id
            return request.clarification_data.options[0].id
        return ""


def _decision_type_from_request_data(request_data: dict[str, Any]) -> DecisionType:
    """Resolve the decision type from legacy and current request fields."""
    selection_mode = request_data.get("selection_mode", "single")
    if selection_mode == "multiple":
        return DecisionType("multi_choice")
    return DecisionType(request_data.get("decision_type", "single_choice"))


def _decision_option_risk_level(option: dict[str, Any]) -> RiskLevel | None:
    """Parse an optional risk level from a decision option."""
    if not option.get("risk_level"):
        return None
    try:
        return RiskLevel(option["risk_level"])
    except ValueError:
        return None


def _sanitize_decision_option_risks(raw_risks: object) -> list[str]:
    """Sanitize optional decision option risk descriptions."""
    if not isinstance(raw_risks, list):
        return []

    sanitized_risks: list[str] = []
    for raw_risk in raw_risks:
        sanitized_risk = sanitize_hitl_text(raw_risk)
        if sanitized_risk is not None:
            sanitized_risks.append(sanitized_risk)
    return sanitized_risks


def _decision_option_from_mapping(
    option: dict[str, Any],
    fallback_index: int,
) -> DecisionOption | None:
    """Build a decision option from a mapping payload."""
    label = sanitize_hitl_text(option.get("label", ""))
    if label is None:
        return None

    option_id = str(option.get("id", str(fallback_index))).strip() or str(fallback_index)
    return DecisionOption(
        id=option_id,
        label=label,
        description=sanitize_hitl_text(option.get("description")),
        recommended=option.get("recommended", False),
        risk_level=_decision_option_risk_level(option),
        estimated_time=sanitize_hitl_text(option.get("estimated_time")),
        estimated_cost=sanitize_hitl_text(option.get("estimated_cost")),
        risks=_sanitize_decision_option_risks(option.get("risks", [])),
    )


def _parse_decision_options(options_data: Iterable[Any]) -> list[DecisionOption]:
    """Parse decision options while preserving legacy string-option support."""
    options: list[DecisionOption] = []
    for option_data in options_data:
        if isinstance(option_data, dict):
            option = _decision_option_from_mapping(option_data, len(options))
            if option is not None:
                options.append(option)
            continue
        if isinstance(option_data, str):
            label = sanitize_hitl_text(option_data)
            if label is not None:
                options.append(DecisionOption(id=str(len(options)), label=label))
    return options


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
        request_data: dict[str, Any],
        **kwargs: Any,
    ) -> HITLRequest:
        question = sanitize_hitl_text(request_data.get("question", "")) or ""
        options_data = request_data.get("options", []) or []
        decision_type = _decision_type_from_request_data(request_data)
        options = _parse_decision_options(options_data)

        # Auto-enable allow_custom when options are empty
        allow_custom = request_data.get("allow_custom", False)
        if not options:
            allow_custom = True
        request_id = request_data.get("_request_id") or self.generate_request_id()

        return create_decision_request(
            request_id=request_id,
            conversation_id=conversation_id,
            question=question,
            options=options,
            decision_type=decision_type,
            allow_custom=allow_custom,
            timeout_seconds=kwargs.get("timeout_seconds", 300.0),
            tenant_id=kwargs.get("tenant_id"),
            project_id=kwargs.get("project_id"),
            message_id=kwargs.get("message_id"),
            context=sanitize_hitl_context(request_data.get("context", {})),
            default_option=request_data.get("default_option"),
            max_selections=request_data.get("max_selections"),
        )

    def extract_response_value(self, response_data: object) -> Any:
        if isinstance(response_data, str):
            return sanitize_hitl_text(response_data) or ""
        if not isinstance(response_data, dict):
            return ""
        decision = response_data.get("decision", "")
        if isinstance(decision, list):
            sanitized_decisions: list[str] = []
            for item in decision:
                sanitized_item = sanitize_hitl_text(item)
                if sanitized_item is not None:
                    sanitized_decisions.append(sanitized_item)
            return sanitized_decisions
        return sanitize_hitl_text(decision) or ""

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
        request_data: dict[str, Any],
        **kwargs: Any,
    ) -> HITLRequest:
        from src.domain.model.agent.hitl_types import EnvVarInputType

        tool_name = sanitize_env_var_text(request_data.get("tool_name", "unknown")) or "unknown"
        fields_data = request_data.get("fields", [])
        message = sanitize_env_var_text(request_data.get("message"))

        fields = []
        requested_names: list[str] = []
        for f in fields_data:
            if isinstance(f, dict):
                is_secret = bool(f.get("secret", False))
                input_type = EnvVarInputType.TEXT
                if f.get("input_type"):
                    try:
                        input_type = EnvVarInputType(f["input_type"])
                    except ValueError:
                        input_type = EnvVarInputType.TEXT
                if is_secret:
                    input_type = EnvVarInputType.PASSWORD
                name = normalize_env_var_name(f.get("name"))
                if not name:
                    raise ValueError("Invalid environment variable name")
                label = sanitize_env_var_text(f.get("label")) or name
                requested_names.append(sanitize_env_var_plain_text(f.get("label")) or name)
                description = sanitize_env_var_text(f.get("description"))
                default_value = sanitize_env_var_text(f.get("default_value"))
                placeholder = sanitize_env_var_text(f.get("placeholder"))
                if input_type == EnvVarInputType.PASSWORD or is_secret:
                    default_value = None
                    placeholder = None

                fields.append(
                    EnvVarField(
                        name=name,
                        label=label,
                        description=description,
                        required=bool(f.get("required", True)),
                        secret=is_secret,
                        input_type=input_type,
                        default_value=default_value,
                        placeholder=placeholder,
                        pattern=sanitize_env_var_text(f.get("pattern")),
                    )
                )

        if not fields:
            raise ValueError("Env-var HITL request requires at least one valid field")

        request_id = request_data.get("_request_id") or self.generate_request_id()
        request_context, _scope_label = build_env_var_request_context(
            raw_context=request_data.get("context", {}),
            tool_name=tool_name,
            requested_variables=requested_names,
            project_id=kwargs.get("save_project_id"),
        )
        return create_env_var_request(
            request_id=request_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            fields=fields,
            message=message,
            timeout_seconds=kwargs.get("timeout_seconds", 300.0),
            tenant_id=kwargs.get("tenant_id"),
            project_id=kwargs.get("project_id"),
            message_id=kwargs.get("message_id"),
            context=request_context,
            allow_save=request_data.get("allow_save", True),
        )

    def extract_response_value(self, response_data: object) -> Any:
        if isinstance(response_data, str):
            return response_data
        if isinstance(response_data, Mapping):
            return response_data.get("values", response_data)
        return response_data

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
        request_data: dict[str, Any],
        **kwargs: Any,
    ) -> HITLRequest:
        tool_name = sanitize_hitl_text(request_data.get("tool_name", "unknown")) or "unknown"
        action = sanitize_hitl_text(request_data.get("action", "execute")) or "execute"
        try:
            risk_level = RiskLevel(request_data.get("risk_level", "medium"))
        except ValueError:
            risk_level = RiskLevel.MEDIUM

        default_action = None
        if request_data.get("default_action"):
            default_action = PermissionAction(request_data["default_action"])

        request_id = request_data.get("_request_id") or self.generate_request_id()
        return create_permission_request(
            request_id=request_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            action=action,
            risk_level=risk_level,
            timeout_seconds=kwargs.get("timeout_seconds", 60.0),
            tenant_id=kwargs.get("tenant_id"),
            project_id=kwargs.get("project_id"),
            message_id=kwargs.get("message_id"),
            details=sanitize_hitl_context(request_data.get("details", {})),
            description=sanitize_hitl_text(request_data.get("description")),
            allow_remember=request_data.get("allow_remember", True),
            default_action=default_action,
            context=sanitize_hitl_context(request_data.get("context", {})),
        )

    def extract_response_value(self, response_data: object) -> Any:
        if isinstance(response_data, str):
            return response_data in ("allow", "allow_always")
        if not isinstance(response_data, Mapping):
            return False
        action = response_data.get("action", "deny")
        if isinstance(action, str) and action in {
            permission.value for permission in PermissionAction
        }:
            granted = response_data.get("granted")
            if isinstance(granted, bool) and granted is not (action in ("allow", "allow_always")):
                return False
            return action in ("allow", "allow_always")
        granted = response_data.get("granted")
        if isinstance(granted, bool):
            return granted
        return False

    def get_default_response(self, request: HITLRequest) -> Any:
        if request.permission_data and request.permission_data.default_action:
            return request.permission_data.default_action.value in (
                "allow",
                "allow_always",
            )
        return False


class A2UIActionStrategy(HITLTypeStrategy):
    """Strategy for A2UI interactive surface action requests.

    When the agent renders an interactive A2UI surface and needs to wait
    for the user to interact (click a button, submit a form, etc.).
    """

    @property
    def hitl_type(self) -> HITLType:
        return HITLType.A2UI_ACTION

    def generate_request_id(self) -> str:
        return f"a2ui_{uuid.uuid4().hex[:8]}"

    def create_request(
        self,
        conversation_id: str,
        request_data: dict[str, Any],
        **kwargs: Any,
    ) -> HITLRequest:
        """Create an HITL request for an A2UI interactive surface.

        request_data should contain:
          - block_id: Canvas block ID housing the A2UI surface
          - title: Human-readable surface title
          - components: JSONL component definitions (for persistence/debug)
          - allowed_actions: validated button id/name pairs accepted for this request
          - context: Arbitrary metadata
        """
        raw_allowed_actions = request_data.get("allowed_actions", [])
        allowed_actions = [
            {
                "source_component_id": action.get("source_component_id", ""),
                "action_name": action.get("action_name", ""),
            }
            for action in raw_allowed_actions
            if isinstance(action, dict)
            and isinstance(action.get("source_component_id"), str)
            and bool(action.get("source_component_id", "").strip())
            and isinstance(action.get("action_name"), str)
            and bool(action.get("action_name", "").strip())
        ]
        return HITLRequest(
            request_id=self.generate_request_id(),
            hitl_type=HITLType.A2UI_ACTION,
            conversation_id=conversation_id,
            timeout_seconds=kwargs.get("timeout_seconds", 300.0),
            tenant_id=kwargs.get("tenant_id"),
            project_id=kwargs.get("project_id"),
            message_id=kwargs.get("message_id"),
            a2ui_data=A2UIActionRequestData(
                title=request_data.get("title", "A2UI interaction required"),
                block_id=request_data.get("block_id", ""),
                allowed_actions=allowed_actions,
                context=request_data.get("context", {}),
            ),
        )

    def extract_response_value(self, response_data: object) -> Any:
        """Extract the action details from the frontend response.

        Expected shape from A2UISurfaceRenderer:
          {"action_name": str, "source_component_id": str, "context": dict}
        """
        if isinstance(response_data, dict):
            return {
                "action_name": response_data.get("action_name", ""),
                "source_component_id": response_data.get("source_component_id", ""),
                "context": response_data.get("context", {}),
            }
        return {"action_name": "", "source_component_id": "", "context": {}}

    def get_default_response(self, request: HITLRequest) -> Any:
        """Default response when the A2UI surface times out or is cancelled."""
        return {"action_name": "", "cancelled": True}
