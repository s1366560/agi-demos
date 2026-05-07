"""
HITL Tool Handlers - Extracted from SessionProcessor.

Handles Human-in-the-Loop tool interactions:
- Clarification requests (ask_clarification)
- Decision requests (request_decision)
- Environment variable requests (request_env_var)

Uses HITLCoordinator's Future-based cooperative pausing: each tool awaits
a Future that is resolved when the user responds, keeping the processor
generator alive across consecutive HITL calls.
"""

# ruff: noqa: PLR0915

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from src.domain.events.agent_events import (
    AgentA2UIActionAnsweredEvent,
    AgentA2UIActionAskedEvent,
    AgentCanvasUpdatedEvent,
    AgentClarificationAnsweredEvent,
    AgentClarificationAskedEvent,
    AgentDecisionAnsweredEvent,
    AgentDecisionAskedEvent,
    AgentDomainEvent,
    AgentEnvVarProvidedEvent,
    AgentEnvVarRequestedEvent,
    AgentObserveEvent,
)
from src.domain.model.agent.hitl.hitl_types import EnvVarRequestData
from src.domain.model.agent.hitl_types import HITLType
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)
from src.infrastructure.agent.canvas.a2ui_builder import (
    extract_actionable_actions,
    extract_surface_id,
    merge_a2ui_message_stream,
    validate_a2ui_incremental_surface_id,
    validate_a2ui_message_syntax,
    validate_a2ui_messages,
)
from src.infrastructure.agent.canvas.manager import CanvasManager
from src.infrastructure.agent.canvas.models import CanvasBlock
from src.infrastructure.agent.hitl.hitl_strategies import (
    ClarificationStrategy,
    DecisionStrategy,
    EnvVarStrategy,
)
from src.infrastructure.agent.hitl.utils import sanitize_env_var_plain_text
from src.infrastructure.agent.tools.env_var_tools import _normalize_hitl_env_values
from src.infrastructure.agent.tools.result import ToolResult

from ..core.message import ToolPart, ToolState
from ..hitl.coordinator import HITLCoordinator, unregister_coordinator

logger = logging.getLogger(__name__)

_PENDING_HITL_COMPLETION_REQUEST_IDS_KEY = "_pending_hitl_completion_request_ids"


def _redacted_hitl_tool_error(tool_name: str, call_id: str | None) -> str:
    """Build a non-leaky error message for HITL/tool observe events.

    The full exception (including upstream stack/secrets) is logged at
    server side via ``logger.exception``; the message returned here is
    safe to expose to the LLM and to the frontend event stream.
    """
    suffix = f" (call_id={call_id})" if call_id else ""
    return f"{tool_name} failed; see server logs{suffix}"


def _user_safe_error(exc: BaseException, tool_name: str, call_id: str | None) -> str:
    """Return a user/LLM-safe error string.

    For deterministic input-validation errors raised by our own code
    (``ValueError``/``TypeError``) we surface the original message because
    it is intentionally written to be actionable and contains no secrets.
    Everything else (network, DB, filesystem, third-party) is redacted to
    avoid leaking internal context — full traceback goes to ``logger.exception``.
    """
    if isinstance(exc, ValueError | TypeError):
        return str(exc)
    return _redacted_hitl_tool_error(tool_name, call_id)


def _ensure_dict(raw: Any) -> dict[str, Any]:
    """Ensure context argument is a dictionary."""
    if isinstance(raw, str):
        return {"description": raw} if raw else {}
    if isinstance(raw, dict):
        return raw.copy()
    return {}


def _extract_tool_result_message(result: ToolResult, default: str) -> str:
    """Extract a human-readable error message from a ToolResult payload."""
    try:
        payload = json.loads(result.output)
    except (TypeError, json.JSONDecodeError):
        return default

    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message
    return default


def _observe_env_var_error(
    *,
    tool_name: str,
    error_message: str,
    call_id: str,
    tool_part: ToolPart,
    end_time: float,
    start_time: float | None = None,
) -> AgentObserveEvent:
    """Mark the tool as failed and build the observe event."""
    tool_part.status = ToolState.ERROR
    tool_part.error = error_message
    tool_part.end_time = end_time
    duration_ms = int((end_time - start_time) * 1000) if start_time is not None else None
    return AgentObserveEvent(
        tool_name=tool_name,
        error=error_message,
        duration_ms=duration_ms,
        call_id=call_id,
        tool_execution_id=tool_part.tool_execution_id,
    )


def queue_tool_part_hitl_completion(tool_part: ToolPart, request_id: str) -> None:
    """Queue a consumed HITL request for durable completion after outer processing finishes."""
    queued_request_ids = tool_part.metadata.setdefault(_PENDING_HITL_COMPLETION_REQUEST_IDS_KEY, [])
    if not isinstance(queued_request_ids, list):
        queued_request_ids = []
        tool_part.metadata[_PENDING_HITL_COMPLETION_REQUEST_IDS_KEY] = queued_request_ids
    if request_id not in queued_request_ids:
        queued_request_ids.append(request_id)


def pop_tool_part_hitl_completion_request_ids(tool_part: ToolPart) -> list[str]:
    """Pop queued HITL completion request IDs from a tool part."""
    queued_request_ids = tool_part.metadata.pop(_PENDING_HITL_COMPLETION_REQUEST_IDS_KEY, [])
    if not isinstance(queued_request_ids, list):
        return []
    return [
        request_id
        for request_id in queued_request_ids
        if isinstance(request_id, str) and request_id
    ]


def _observe_env_var_result(
    *,
    tool_name: str,
    result: dict[str, Any],
    call_id: str,
    tool_part: ToolPart,
    end_time: float,
    start_time: float,
) -> AgentObserveEvent:
    """Mark the tool as completed and build the observe event."""
    tool_part.status = ToolState.COMPLETED
    tool_part.output = json.dumps(result)
    tool_part.end_time = end_time
    return AgentObserveEvent(
        tool_name=tool_name,
        result=result,
        duration_ms=int((end_time - start_time) * 1000),
        call_id=call_id,
        tool_execution_id=tool_part.tool_execution_id,
    )


def _parse_env_var_hitl_response(
    response: object,
    env_var_data: EnvVarRequestData,
) -> tuple[dict[str, str] | None, dict[str, Any] | None, str | None]:
    """Normalize HITL env-var responses into values, cancellation, or an error."""
    invalid_error = "Invalid environment variable values returned from HITL"
    if not isinstance(response, dict):
        return None, None, invalid_error

    if response.get("timeout"):
        return None, None, "Environment variable request timed out"

    if response.get("cancelled"):
        return (
            None,
            {
                "success": False,
                "cancelled": True,
                "tool_name": env_var_data.tool_name,
                "saved_variables": [],
                "message": "User did not provide the requested environment variables",
            },
            None,
        )

    raw_values = response.get("values", response)
    field_specs = {
        field.name: {
            "is_required": field.required,
            "is_secret": field.secret,
        }
        for field in env_var_data.fields
    }
    normalized_values = _normalize_hitl_env_values(raw_values, field_specs)
    if isinstance(normalized_values, ToolResult):
        return None, None, _extract_tool_result_message(normalized_values, invalid_error)
    return normalized_values, None, None


async def handle_clarification_tool(
    coordinator: HITLCoordinator,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    tool_part: ToolPart,
) -> AsyncIterator[AgentDomainEvent]:
    """Handle clarification tool via HITLCoordinator (Future-based)."""
    request_id: str | None = None
    try:
        question = arguments.get("question", "")
        clarification_type = arguments.get("clarification_type", "custom")
        options_raw = arguments.get("options", [])
        allow_custom = arguments.get("allow_custom", True)
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)
        default_value = arguments.get("default_value")

        preview_request = ClarificationStrategy().create_request(
            conversation_id="preview",
            request_data={
                "question": question,
                "options": options_raw,
                "clarification_type": clarification_type,
                "allow_custom": allow_custom,
                "context": context,
                "default_value": default_value,
            },
            timeout_seconds=timeout,
            default_value=default_value,
        )
        clarification_data = preview_request.clarification_data
        if clarification_data is None:
            raise ValueError("Clarification preview request missing clarification_data")

        question = preview_request.question
        clarification_type = clarification_data.clarification_type.value
        allow_custom = clarification_data.allow_custom
        context = clarification_data.context
        default_value = clarification_data.default_value
        clarification_options = [option.to_dict() for option in clarification_data.options]
        valid_option_ids = {option["id"] for option in clarification_options}
        if (
            clarification_options
            and default_value is not None
            and default_value not in valid_option_ids
        ):
            if not allow_custom:
                default_value = None

        # Auto-enable allow_custom when options are empty
        if not clarification_options:
            allow_custom = True
            logger.info(
                "[HITL] Clarification tool called with empty options, "
                "auto-enabling allow_custom for free-form response"
            )

        request_data = {
            "question": question,
            "options": clarification_options,
            "clarification_type": clarification_type,
            "allow_custom": allow_custom,
            "context": context,
            "default_value": default_value,
        }

        request_id = await coordinator.prepare_request(
            HITLType.CLARIFICATION,
            request_data,
            timeout,
        )

        yield AgentClarificationAskedEvent(
            request_id=request_id,
            question=question,
            clarification_type=clarification_type,
            options=clarification_options,
            allow_custom=allow_custom,
            default_value=default_value,
            context=context,
        )

        start_time = time.time()
        answer = await coordinator.wait_for_response(
            request_id,
            HITLType.CLARIFICATION,
            timeout,
        )
        end_time = time.time()
        queue_tool_part_hitl_completion(tool_part, request_id)

        yield AgentClarificationAnsweredEvent(
            request_id=request_id,
            answer=answer,
        )

        tool_part.status = ToolState.COMPLETED
        tool_part.output = answer
        tool_part.end_time = end_time

        yield AgentObserveEvent(
            tool_name=tool_name,
            result=answer,
            duration_ms=int((end_time - start_time) * 1000),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )

    except TimeoutError:
        tool_part.status = ToolState.ERROR
        tool_part.error = "Clarification request timed out"
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error="Clarification request timed out",
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )

    except Exception as e:
        logger.exception(
            "Clarification tool error",
            extra={"tool_name": tool_name, "call_id": call_id},
        )
        coordinator.cancel_request_if_pending(request_id)
        redacted = _user_safe_error(e, tool_name, call_id)
        tool_part.status = ToolState.ERROR
        tool_part.error = redacted
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error=redacted,
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )
        del e  # avoid leaking via locals


async def handle_decision_tool(
    coordinator: HITLCoordinator,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    tool_part: ToolPart,
) -> AsyncIterator[AgentDomainEvent]:
    """Handle decision tool via HITLCoordinator (Future-based)."""
    request_id: str | None = None
    try:
        question = arguments.get("question", "")
        decision_type = arguments.get("decision_type", "custom")
        options_raw = arguments.get("options", [])
        allow_custom = arguments.get("allow_custom", False)
        default_option = arguments.get("default_option")
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)
        selection_mode = arguments.get("selection_mode", "single")
        max_selections = arguments.get("max_selections")

        preview_request = DecisionStrategy().create_request(
            conversation_id="preview",
            request_data={
                "question": question,
                "options": options_raw,
                "decision_type": decision_type,
                "allow_custom": allow_custom,
                "context": context,
                "default_option": default_option,
                "selection_mode": selection_mode,
                "max_selections": max_selections,
            },
            timeout_seconds=timeout,
            default_option=default_option,
            max_selections=max_selections,
        )
        decision_data = preview_request.decision_data
        if decision_data is None:
            raise ValueError("Decision preview request missing decision_data")

        question = preview_request.question
        decision_type = decision_data.decision_type.value
        allow_custom = decision_data.allow_custom
        context = decision_data.context
        default_option = decision_data.default_option
        max_selections = decision_data.max_selections
        decision_options = [option.to_dict() for option in decision_data.options]
        valid_option_ids = {option["id"] for option in decision_options}
        if default_option not in valid_option_ids:
            default_option = None

        # Auto-enable allow_custom when options are empty
        if not decision_options:
            allow_custom = True
            logger.info(
                "[HITL] Decision tool called with empty options, "
                "auto-enabling allow_custom for free-form response"
            )

        request_data = {
            "question": question,
            "options": decision_options,
            "decision_type": decision_type,
            "allow_custom": allow_custom,
            "context": context,
            "default_option": default_option,
            "selection_mode": selection_mode,
            "max_selections": max_selections,
        }

        request_id = await coordinator.prepare_request(
            HITLType.DECISION,
            request_data,
            timeout,
        )

        yield AgentDecisionAskedEvent(
            request_id=request_id,
            question=question,
            decision_type=decision_type,
            options=decision_options,
            allow_custom=allow_custom,
            default_option=default_option,
            context=context,
            selection_mode=selection_mode,
            max_selections=max_selections,
        )

        start_time = time.time()
        decision = await coordinator.wait_for_response(
            request_id,
            HITLType.DECISION,
            timeout,
        )
        end_time = time.time()
        queue_tool_part_hitl_completion(tool_part, request_id)

        yield AgentDecisionAnsweredEvent(
            request_id=request_id,
            decision=decision,
        )

        tool_part.status = ToolState.COMPLETED
        tool_part.output = decision
        tool_part.end_time = end_time

        yield AgentObserveEvent(
            tool_name=tool_name,
            result=decision,
            duration_ms=int((end_time - start_time) * 1000),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )

    except TimeoutError:
        tool_part.status = ToolState.ERROR
        tool_part.error = "Decision request timed out"
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error="Decision request timed out",
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )

    except Exception as e:
        logger.exception(
            "Decision tool error",
            extra={"tool_name": tool_name, "call_id": call_id},
        )
        coordinator.cancel_request_if_pending(request_id)
        redacted = _user_safe_error(e, tool_name, call_id)
        tool_part.status = ToolState.ERROR
        tool_part.error = redacted
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error=redacted,
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )
        del e


def _prepare_fields_for_sse(fields_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize raw field definitions into SSE-compatible dicts."""
    fields_for_sse: list[dict[str, Any]] = []
    for field in fields_raw:
        var_name = field.get("variable_name", field.get("name", ""))
        display_name = field.get("display_name", field.get("label", var_name))
        input_type_str = field.get("input_type", "text")
        is_required = field.get("is_required", field.get("required", True))
        is_secret = field.get("is_secret", True)

        field_dict = {
            "name": var_name,
            "label": display_name,
            "description": field.get("description"),
            "required": is_required,
            "input_type": input_type_str,
            "default_value": field.get("default_value"),
            "placeholder": field.get("placeholder"),
            "secret": is_secret,
        }
        fields_for_sse.append(field_dict)
    return fields_for_sse


async def handle_env_var_tool(
    coordinator: HITLCoordinator,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    tool_part: ToolPart,
    langfuse_context: dict[str, Any] | None = None,
) -> AsyncIterator[AgentDomainEvent]:
    """Handle environment variable request tool via HITLCoordinator."""
    request_id: str | None = None
    try:
        target_tool_name = arguments.get("tool_name", "")
        fields_raw = arguments.get("fields", [])
        message = arguments.get("message")
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)
        save_to_project = arguments.get("save_to_project", False)
        active_project_id = coordinator.project_id or None
        save_project_id = active_project_id if save_to_project else None
        if save_to_project and not save_project_id:
            raise ValueError("Project-scoped environment variables require an active project")

        fields_for_sse = _prepare_fields_for_sse(fields_raw)

        request_data = {
            "tool_name": target_tool_name,
            "fields": fields_for_sse,
            "message": message,
            "context": context,
            "allow_save": True,
        }
        prepared_request = EnvVarStrategy().create_request(
            conversation_id=coordinator.conversation_id,
            request_data=request_data,
            timeout_seconds=timeout,
            tenant_id=coordinator.tenant_id,
            project_id=coordinator.project_id,
            message_id=getattr(coordinator, "message_id", None),
            save_project_id=save_project_id,
        )
        env_var_data = prepared_request.env_var_data
        if env_var_data is None:
            raise ValueError("Failed to build environment variable HITL request")
        request_data["_request_id"] = prepared_request.request_id

        request_id = await coordinator.prepare_request(
            HITLType.ENV_VAR,
            request_data,
            timeout,
            save_project_id=save_project_id,
        )

        yield AgentEnvVarRequestedEvent(
            request_id=request_id,
            tool_name=env_var_data.tool_name,
            fields=[field.to_dict() for field in env_var_data.fields],
            context=env_var_data.context,
        )

        start_time = time.time()
        response = await coordinator.wait_for_response(
            request_id,
            HITLType.ENV_VAR,
            timeout,
        )
        end_time = time.time()
        queue_tool_part_hitl_completion(tool_part, request_id)

        normalized_values, cancelled_result, error_message = _parse_env_var_hitl_response(
            response,
            env_var_data,
        )
        if error_message:
            yield _observe_env_var_error(
                tool_name=tool_name,
                error_message=error_message,
                call_id=call_id,
                tool_part=tool_part,
                end_time=end_time,
                start_time=start_time,
            )
            return

        if cancelled_result is not None:
            yield _observe_env_var_result(
                tool_name=tool_name,
                result=cancelled_result,
                call_id=call_id,
                tool_part=tool_part,
                end_time=end_time,
                start_time=start_time,
            )
            return

        if normalized_values is None:
            yield _observe_env_var_error(
                tool_name=tool_name,
                error_message="Invalid environment variable values returned from HITL",
                call_id=call_id,
                tool_part=tool_part,
                end_time=end_time,
                start_time=start_time,
            )
            return

        saved_variables: list[str] = []
        tenant_id = coordinator.tenant_id

        if normalized_values and not tenant_id:
            error_message = "Missing tenant context for environment variable save"
            yield _observe_env_var_error(
                tool_name=tool_name,
                error_message=error_message,
                call_id=call_id,
                tool_part=tool_part,
                end_time=end_time,
                start_time=start_time,
            )
            return

        if tenant_id and normalized_values:
            try:
                saved_variables = await _save_env_vars(
                    values=normalized_values,
                    fields_for_sse=[field.to_dict() for field in env_var_data.fields],
                    target_tool_name=env_var_data.tool_name,
                    tenant_id=tenant_id,
                    project_id=save_project_id,
                    save_to_project=save_to_project,
                )
            except Exception as exc:
                error_message = f"Failed to save environment variables: {exc}"
                logger.error(error_message, exc_info=True)
                yield _observe_env_var_error(
                    tool_name=tool_name,
                    error_message=error_message,
                    call_id=call_id,
                    tool_part=tool_part,
                    end_time=end_time,
                    start_time=start_time,
                )
                return
        else:
            saved_variables = list(normalized_values.keys())

        yield AgentEnvVarProvidedEvent(
            request_id=request_id,
            tool_name=env_var_data.tool_name,
            saved_variables=saved_variables,
        )

        tool_part.status = ToolState.COMPLETED
        result = {
            "success": True,
            "tool_name": env_var_data.tool_name,
            "saved_variables": saved_variables,
            "message": f"Successfully saved {len(saved_variables)} environment variable(s)",
        }
        yield _observe_env_var_result(
            tool_name=tool_name,
            result=result,
            call_id=call_id,
            tool_part=tool_part,
            end_time=end_time,
            start_time=start_time,
        )

    except TimeoutError:
        yield _observe_env_var_error(
            tool_name=tool_name,
            error_message="Environment variable request timed out",
            call_id=call_id,
            tool_part=tool_part,
            end_time=time.time(),
        )

    except Exception as e:
        logger.exception(
            "Environment variable tool error",
            extra={"tool_name": tool_name, "call_id": call_id},
        )
        coordinator.cancel_request_if_pending(request_id)
        yield _observe_env_var_error(
            tool_name=tool_name,
            error_message=_user_safe_error(e, tool_name, call_id),
            call_id=call_id,
            tool_part=tool_part,
            end_time=time.time(),
        )
        del e


async def _save_env_vars(
    values: dict[str, str],
    fields_for_sse: list[dict[str, Any]],
    target_tool_name: str,
    tenant_id: str,
    project_id: str | None,
    save_to_project: bool,
) -> list[str]:
    """Save environment variables to database with encryption."""
    from src.domain.model.agent.tool_environment_variable import (
        EnvVarScope,
        ToolEnvironmentVariable,
    )
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
        SqlToolEnvironmentVariableRepository,
    )
    from src.infrastructure.security.encryption_service import (
        get_encryption_service,
    )

    encryption_service = get_encryption_service()
    scope = EnvVarScope.PROJECT if save_to_project and project_id else EnvVarScope.TENANT
    effective_project_id = project_id if save_to_project else None
    saved_variables: list[str] = []

    async with async_session_factory() as db_session:
        repository = SqlToolEnvironmentVariableRepository(db_session)
        for field_spec in fields_for_sse:
            var_name = field_spec["name"]
            if values.get(var_name):
                encrypted_value = encryption_service.encrypt(values[var_name])
                persisted_description = None
                if not field_spec.get("secret", True):
                    persisted_description = sanitize_env_var_plain_text(
                        field_spec.get("description")
                    )
                env_var = ToolEnvironmentVariable(
                    tenant_id=tenant_id,
                    project_id=effective_project_id,
                    tool_name=target_tool_name,
                    variable_name=var_name,
                    encrypted_value=encrypted_value,
                    description=persisted_description,
                    is_required=field_spec.get("required", True),
                    is_secret=field_spec.get("secret", True),
                    scope=scope,
                )
                await repository.upsert(env_var)
                saved_variables.append(var_name)
                logger.info(f"Saved env var: {target_tool_name}/{var_name}")
        await db_session.commit()

    return saved_variables


def _upsert_a2ui_canvas_block(
    canvas_mgr: CanvasManager,
    conversation_id: str,
    title: str,
    components: str,
    block_id: str,
) -> tuple[CanvasBlock, str, str | None, CanvasBlock | None]:
    """Create or update the A2UI canvas block before waiting for HITL input."""
    from src.infrastructure.agent.canvas.tools import _resolve_block_id

    resolved_block_id = block_id
    existing_block = canvas_mgr.get_block(conversation_id, resolved_block_id)
    if existing_block is None and block_id:
        resolved_id = _resolve_block_id(canvas_mgr, conversation_id, block_id)
        if resolved_id is not None:
            resolved_block_id = resolved_id
            existing_block = canvas_mgr.get_block(conversation_id, resolved_block_id)

    if existing_block is not None and existing_block.block_type.value != "a2ui_surface":
        msg = f"Canvas block '{resolved_block_id}' is not an A2UI surface"
        raise ValueError(msg)

    syntax_error = validate_a2ui_message_syntax(components)
    if syntax_error is not None:
        raise ValueError(syntax_error)

    existing_surface_id = (
        existing_block.metadata.get("surface_id")
        if existing_block is not None and isinstance(existing_block.metadata, dict)
        else None
    ) or (extract_surface_id(existing_block.content) if existing_block is not None else None)
    if isinstance(existing_surface_id, str) and existing_surface_id:
        validation_error = validate_a2ui_incremental_surface_id(
            components,
            expected_surface_id=existing_surface_id,
        )
        if validation_error is not None:
            raise ValueError(validation_error)

    merged_content = merge_a2ui_message_stream(
        existing_block.content if existing_block is not None else None,
        components,
    )
    validation_error = validate_a2ui_messages(
        merged_content,
        require_initial_render=existing_block is None,
        require_user_action=True,
    )
    if validation_error is not None:
        raise ValueError(validation_error)

    surface_id = extract_surface_id(merged_content) or (
        existing_block.metadata.get("surface_id") if existing_block is not None else None
    )

    canvas_metadata = {"surface_id": surface_id} if surface_id else None
    if existing_block is not None:
        block = canvas_mgr.update_block(
            conversation_id=conversation_id,
            block_id=resolved_block_id,
            content=merged_content,
            title=title,
            metadata=canvas_metadata,
        )
        return block, "updated", surface_id, existing_block

    block = canvas_mgr.create_block(
        conversation_id=conversation_id,
        block_type="a2ui_surface",
        title=title,
        content=merged_content,
        metadata=canvas_metadata,
    )
    return block, "created", surface_id, None


def _attach_hitl_request_metadata(
    canvas_mgr: CanvasManager,
    conversation_id: str,
    block: CanvasBlock,
    request_id: str,
    surface_id: str | None,
) -> CanvasBlock:
    """Persist the HITL request ID onto the canvas block for frontend hydration."""
    metadata = {
        "hitl_request_id": request_id,
        **({"surface_id": surface_id} if surface_id else {}),
    }
    return canvas_mgr.update_block(
        conversation_id=conversation_id,
        block_id=block.id,
        metadata=metadata,
    )


def _canvas_updated_event(
    conversation_id: str,
    block: CanvasBlock,
    action: str,
) -> AgentCanvasUpdatedEvent:
    """Create a canvas updated event for an A2UI block."""
    return AgentCanvasUpdatedEvent(
        conversation_id=conversation_id,
        block_id=block.id,
        action=action,
        block=block.to_dict(),
    )


def _clear_hitl_request_metadata(
    canvas_mgr: CanvasManager,
    conversation_id: str,
    block_id: str,
    surface_id: str | None,
) -> CanvasBlock:
    """Clear the active HITL request marker after the interaction ends."""
    metadata = {
        "hitl_request_id": "",
        **({"surface_id": surface_id} if surface_id else {}),
    }
    return canvas_mgr.update_block(
        conversation_id=conversation_id,
        block_id=block_id,
        metadata=metadata,
    )


def _clear_hitl_request_event(
    canvas_mgr: CanvasManager | None,
    conversation_id: str,
    block_id: str | None,
    surface_id: str | None,
) -> AgentCanvasUpdatedEvent | None:
    """Clear HITL request metadata and return the corresponding canvas event."""
    if canvas_mgr is None or block_id is None:
        return None
    block = _clear_hitl_request_metadata(
        canvas_mgr=canvas_mgr,
        conversation_id=conversation_id,
        block_id=block_id,
        surface_id=surface_id,
    )
    return _canvas_updated_event(conversation_id, block, "updated")


async def _discard_prepared_request(
    coordinator: HITLCoordinator,
    request_id: str,
    reason: str,
) -> None:
    """Remove a prepared HITL request when setup fails before waiting."""
    pending_entry = coordinator._pending.pop(request_id, None)
    if pending_entry is not None:
        pending_future = getattr(pending_entry, "future", pending_entry)
        completion_future = getattr(pending_entry, "completion_future", None)
        if hasattr(pending_future, "done") and not pending_future.done():
            pending_future.set_result({"cancelled": True, "reason": reason})
        if completion_future is not None and not completion_future.done():
            completion_future.set_result(None)
    unregister_coordinator(request_id)
    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)
        _ = await repo.mark_cancelled(request_id)
        await session.commit()


def _rollback_a2ui_canvas_block(
    canvas_mgr: CanvasManager | None,
    conversation_id: str,
    block: CanvasBlock | None,
    previous_block: CanvasBlock | None,
    canvas_action: str,
) -> None:
    """Restore canvas state when interactive setup fails before any event is emitted."""
    if canvas_mgr is None or block is None:
        return
    if canvas_action == "created":
        try:
            canvas_mgr.delete_block(conversation_id, block.id)
        except KeyError:
            logger.debug("A2UI rollback skipped missing block %s", block.id)
        return
    if previous_block is not None:
        canvas_mgr._get_or_create_state(conversation_id).add(previous_block)


def _extract_a2ui_response(
    answer: object,
    block_id: str,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """Normalize the returned HITL payload into the tool result contract."""
    answer_dict = answer if isinstance(answer, dict) else {}
    action_name = answer_dict.get("action_name", "")
    source_component_id = answer_dict.get("source_component_id", "")
    action_context = _ensure_dict(answer_dict.get("context", {}))
    result = {
        "action_name": action_name,
        "source_component_id": source_component_id,
        "context": action_context,
        "cancelled": answer_dict.get("cancelled", False),
        "block_id": block_id,
    }
    return action_name, source_component_id, action_context, result


def _set_tool_part_error(tool_part: ToolPart, error: str) -> None:
    """Store an error result on the in-flight tool part."""
    tool_part.status = ToolState.ERROR
    tool_part.error = error
    tool_part.end_time = time.time()


def _complete_a2ui_tool_part(
    tool_part: ToolPart,
    result: dict[str, Any],
    end_time: float,
) -> None:
    """Persist the completed A2UI action result onto the tool part."""
    tool_part.status = ToolState.COMPLETED
    tool_part.output = json.dumps(result)
    tool_part.end_time = end_time


def _observe_event(
    *,
    tool_name: str,
    call_id: str,
    tool_part: ToolPart,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
) -> AgentObserveEvent:
    """Create an observe event for the current tool execution."""
    return AgentObserveEvent(
        tool_name=tool_name,
        result=result,
        error=error,
        duration_ms=duration_ms,
        call_id=call_id,
        tool_execution_id=tool_part.tool_execution_id,
    )


async def handle_a2ui_action_tool(
    coordinator: HITLCoordinator,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    tool_part: ToolPart,
) -> AsyncIterator[AgentDomainEvent]:
    """Handle A2UI interactive surface tool via HITLCoordinator (Future-based).

    Renders an A2UI surface and pauses the agent until the user interacts
    with it (button click, form submission, etc.).  The user action is
    returned as a dict with action_name, source_component_id, and context.
    """
    request_id: str | None = None
    canvas_mgr: CanvasManager | None = None
    block: CanvasBlock | None = None
    previous_block: CanvasBlock | None = None
    canvas_action = "created"
    canvas_emitted = False
    effective_block_id: str | None = None
    surface_id: str | None = None
    try:
        title = arguments.get("title", "")
        components = arguments.get("components", "")
        block_id = arguments.get("block_id", "")
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)

        # Create a canvas block so the frontend renders the A2UI surface tab
        from src.infrastructure.agent.canvas.tools import get_canvas_manager

        canvas_mgr = get_canvas_manager()
        block, canvas_action, surface_id, previous_block = _upsert_a2ui_canvas_block(
            canvas_mgr=canvas_mgr,
            conversation_id=coordinator.conversation_id,
            title=title,
            components=components,
            block_id=block_id,
        )
        effective_block_id = block.id

        request_data = {
            "block_id": effective_block_id,
            "title": title,
            "components": block.content,
            "allowed_actions": extract_actionable_actions(block.content),
            "context": context,
        }
        request_id = await coordinator.prepare_request(
            HITLType.A2UI_ACTION,
            request_data,
            timeout,
        )
        block = _attach_hitl_request_metadata(
            canvas_mgr=canvas_mgr,
            conversation_id=coordinator.conversation_id,
            block=block,
            request_id=request_id,
            surface_id=surface_id,
        )
        canvas_emitted = True
        yield _canvas_updated_event(coordinator.conversation_id, block, canvas_action)

        yield AgentA2UIActionAskedEvent(
            request_id=request_id,
            conversation_id=coordinator.conversation_id,
            block_id=effective_block_id,
            title=title,
            timeout_seconds=timeout,
            surface_data=request_data,
        )

        start_time = time.time()
        answer = await coordinator.wait_for_response(
            request_id,
            HITLType.A2UI_ACTION,
            timeout,
        )
        end_time = time.time()
        queue_tool_part_hitl_completion(tool_part, request_id)
        action_name, source_component_id, action_context, result = _extract_a2ui_response(
            answer,
            effective_block_id,
        )

        yield AgentA2UIActionAnsweredEvent(
            request_id=request_id,
            action_name=action_name,
            source_component_id=source_component_id,
            context=action_context,
        )
        cleared_event = _clear_hitl_request_event(
            canvas_mgr=canvas_mgr,
            conversation_id=coordinator.conversation_id,
            block_id=effective_block_id,
            surface_id=surface_id,
        )
        if cleared_event is not None:
            yield cleared_event

        _complete_a2ui_tool_part(
            tool_part=tool_part,
            result=result,
            end_time=end_time,
        )
        yield _observe_event(
            tool_name=tool_name,
            result=result,
            duration_ms=int((end_time - start_time) * 1000),
            call_id=call_id,
            tool_part=tool_part,
        )

    except TimeoutError:
        cleared_event = _clear_hitl_request_event(
            canvas_mgr=canvas_mgr,
            conversation_id=coordinator.conversation_id,
            block_id=effective_block_id,
            surface_id=surface_id,
        )
        if cleared_event is not None:
            yield cleared_event
        _set_tool_part_error(tool_part, "A2UI action request timed out")
        yield _observe_event(
            tool_name=tool_name,
            error="A2UI action request timed out",
            call_id=call_id,
            tool_part=tool_part,
        )

    except Exception as e:
        if request_id is not None and request_id in coordinator.pending_request_ids:
            await _discard_prepared_request(coordinator, request_id, "a2ui canvas setup failed")
        if not canvas_emitted:
            _rollback_a2ui_canvas_block(
                canvas_mgr=canvas_mgr,
                conversation_id=coordinator.conversation_id,
                block=block,
                previous_block=previous_block,
                canvas_action=canvas_action,
            )
        else:
            cleared_event = _clear_hitl_request_event(
                canvas_mgr=canvas_mgr,
                conversation_id=coordinator.conversation_id,
                block_id=effective_block_id,
                surface_id=surface_id,
            )
            if cleared_event is not None:
                yield cleared_event
        logger.exception(
            "A2UI action tool error",
            extra={"tool_name": tool_name, "call_id": call_id},
        )
        redacted = _user_safe_error(e, tool_name, call_id)
        _set_tool_part_error(tool_part, redacted)
        yield _observe_event(
            tool_name=tool_name,
            error=redacted,
            call_id=call_id,
            tool_part=tool_part,
        )
        del e
