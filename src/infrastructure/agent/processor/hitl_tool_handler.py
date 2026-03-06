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
from src.domain.model.agent.hitl_types import HITLType

from ..core.message import ToolPart, ToolState
from ..hitl.coordinator import HITLCoordinator

logger = logging.getLogger(__name__)


def _ensure_dict(raw: Any) -> dict[str, Any]:
    """Ensure context argument is a dictionary."""
    if isinstance(raw, str):
        return {"description": raw} if raw else {}
    if isinstance(raw, dict):
        return raw.copy()
    return {}


async def handle_clarification_tool(
    coordinator: HITLCoordinator,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    tool_part: ToolPart,
) -> AsyncIterator[AgentDomainEvent]:
    """Handle clarification tool via HITLCoordinator (Future-based)."""
    try:
        question = arguments.get("question", "")
        clarification_type = arguments.get("clarification_type", "custom")
        options_raw = arguments.get("options", [])
        allow_custom = arguments.get("allow_custom", True)
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)
        default_value = arguments.get("default_value")

        clarification_options: list[dict[str, Any]] = []
        for i, opt in enumerate(options_raw):
            clarification_options.append({
                "id": opt.get("id") or str(i),
                "label": opt.get("label", ""),
                "description": opt.get("description"),
                "recommended": opt.get("recommended", False),
            })

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
            context=context,
        )

        start_time = time.time()
        answer = await coordinator.wait_for_response(
            request_id,
            HITLType.CLARIFICATION,
            timeout,
        )
        end_time = time.time()

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
        logger.error(f"Clarification tool error: {e}", exc_info=True)
        tool_part.status = ToolState.ERROR
        tool_part.error = str(e)
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error=str(e),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )


async def handle_decision_tool(
    coordinator: HITLCoordinator,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    tool_part: ToolPart,
) -> AsyncIterator[AgentDomainEvent]:
    """Handle decision tool via HITLCoordinator (Future-based)."""
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

        decision_options: list[dict[str, Any]] = []
        for i, opt in enumerate(options_raw):
            decision_options.append({
                "id": opt.get("id") or str(i),
                "label": opt.get("label", ""),
                "description": opt.get("description"),
                "recommended": opt.get("recommended", False),
                "estimated_time": opt.get("estimated_time"),
                "estimated_cost": opt.get("estimated_cost"),
                "risks": opt.get("risks", []),
            })

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
        logger.error(f"Decision tool error: {e}", exc_info=True)
        tool_part.status = ToolState.ERROR
        tool_part.error = str(e)
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error=str(e),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )


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
    try:
        target_tool_name = arguments.get("tool_name", "")
        fields_raw = arguments.get("fields", [])
        message = arguments.get("message")
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)
        save_to_project = arguments.get("save_to_project", False)

        fields_for_sse = _prepare_fields_for_sse(fields_raw)

        request_data = {
            "tool_name": target_tool_name,
            "fields": fields_for_sse,
            "message": message,
            "allow_save": True,
        }

        request_id = await coordinator.prepare_request(
            HITLType.ENV_VAR,
            request_data,
            timeout,
        )

        yield AgentEnvVarRequestedEvent(
            request_id=request_id,
            tool_name=target_tool_name,
            fields=fields_for_sse,
            context=context if context else {},
        )

        start_time = time.time()
        values = await coordinator.wait_for_response(
            request_id,
            HITLType.ENV_VAR,
            timeout,
        )
        end_time = time.time()

        saved_variables: list[str] = []
        ctx = langfuse_context or {}
        tenant_id = ctx.get("tenant_id")
        project_id = ctx.get("project_id")

        if tenant_id and values:
            try:
                saved_variables = await _save_env_vars(
                    values=values,
                    fields_for_sse=fields_for_sse,
                    target_tool_name=target_tool_name,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    save_to_project=save_to_project,
                )
            except Exception as e:
                logger.error(f"Error saving env vars to database: {e}")
                saved_variables = list(values.keys()) if values else []
        else:
            saved_variables = list(values.keys()) if values else []

        yield AgentEnvVarProvidedEvent(
            request_id=request_id,
            tool_name=target_tool_name,
            saved_variables=saved_variables,
        )

        tool_part.status = ToolState.COMPLETED
        result = {
            "success": True,
            "tool_name": target_tool_name,
            "saved_variables": saved_variables,
            "message": f"Successfully saved {len(saved_variables)} environment variable(s)",
        }
        tool_part.output = json.dumps(result)
        tool_part.end_time = end_time

        yield AgentObserveEvent(
            tool_name=tool_name,
            result=result,
            duration_ms=int((end_time - start_time) * 1000),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )

    except TimeoutError:
        tool_part.status = ToolState.ERROR
        tool_part.error = "Environment variable request timed out"
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error="Environment variable request timed out",
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )

    except Exception as e:
        logger.error(f"Environment variable tool error: {e}", exc_info=True)
        tool_part.status = ToolState.ERROR
        tool_part.error = str(e)
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error=str(e),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )


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
                env_var = ToolEnvironmentVariable(
                    tenant_id=tenant_id,
                    project_id=effective_project_id,
                    tool_name=target_tool_name,
                    variable_name=var_name,
                    encrypted_value=encrypted_value,
                    description=field_spec.get("description"),
                    is_required=field_spec.get("required", True),
                    is_secret=field_spec.get("secret", True),
                    scope=scope,
                )
                await repository.upsert(env_var)
                saved_variables.append(var_name)
                logger.info(f"Saved env var: {target_tool_name}/{var_name}")
        await db_session.commit()

    return saved_variables


def _repair_jsonl(raw: str) -> str:
    """Validate and repair LLM-generated JSONL -- fix missing closing brackets.

    LLMs sometimes emit malformed JSON with missing closing braces/brackets.
    This tries common suffixes to repair each line.
    """
    import json as _json

    # Common suffixes LLMs forget: closing braces, brackets, or combos
    _suffixes = [
        "}", "}}", "}}}", "}}}}",
        "]}", "]}}", "]}}}",
        "]}]", "]}}]",
        "]", "]]",
        "}]", "}}]", "}}}]",
        "}}]}}", "]}}]}}",
    ]

    repaired_lines: list[str] = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            _json.loads(stripped)
            repaired_lines.append(stripped)
        except _json.JSONDecodeError:
            fixed = False
            for suffix in _suffixes:
                try:
                    _json.loads(stripped + suffix)
                    repaired_lines.append(stripped + suffix)
                    fixed = True
                    break
                except _json.JSONDecodeError:
                    continue
            if not fixed:
                repaired_lines.append(stripped)  # pass through as-is
    return "\n".join(repaired_lines)


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
    try:
        title = arguments.get("title", "")
        components = arguments.get("components", "")
        # Repair LLM-generated JSONL with missing closing braces
        if isinstance(components, str) and components.strip():
            components = _repair_jsonl(components)
        block_id = arguments.get("block_id", "")
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)

        request_data = {
            "block_id": block_id,
            "title": title,
            "components": components,
            "context": context,
        }

        request_id = await coordinator.prepare_request(
            HITLType.A2UI_ACTION,
            request_data,
            timeout,
        )

        # Create a canvas block so the frontend renders the A2UI surface tab
        effective_block_id = block_id
        try:
            from src.infrastructure.agent.canvas.tools import get_canvas_manager

            canvas_mgr = get_canvas_manager()
            block = canvas_mgr.create_block(
                conversation_id=coordinator.conversation_id,
                block_type="a2ui_surface",
                title=title,
                content=components,
                metadata={"surface_id": block_id or request_id},
            )
            yield AgentCanvasUpdatedEvent(
                conversation_id=coordinator.conversation_id,
                block_id=block.id,
                action="created",
                block=block.to_dict(),
            )
            effective_block_id = block.id
        except Exception:
            logger.warning(
                "Could not create canvas block for A2UI interactive surface",
                exc_info=True,
            )

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

        # Extract action fields from the response
        answer_dict = answer if isinstance(answer, dict) else {}
        action_name = answer_dict.get("action_name", "")
        source_component_id = answer_dict.get("source_component_id", "")
        action_context = _ensure_dict(answer_dict.get("context", {}))

        yield AgentA2UIActionAnsweredEvent(
            request_id=request_id,
            action_name=action_name,
            source_component_id=source_component_id,
            context=action_context,
        )

        tool_part.status = ToolState.COMPLETED
        result = {
            "action_name": action_name,
            "source_component_id": source_component_id,
            "context": action_context,
            "cancelled": answer_dict.get("cancelled", False),
            "block_id": effective_block_id,
        }
        tool_part.output = json.dumps(result)
        tool_part.end_time = end_time

        yield AgentObserveEvent(
            tool_name=tool_name,
            result=result,
            duration_ms=int((end_time - start_time) * 1000),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )

    except TimeoutError:
        tool_part.status = ToolState.ERROR
        tool_part.error = "A2UI action request timed out"
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error="A2UI action request timed out",
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )

    except Exception as e:
        logger.error(f"A2UI action tool error: {e}", exc_info=True)
        tool_part.status = ToolState.ERROR
        tool_part.error = str(e)
        tool_part.end_time = time.time()

        yield AgentObserveEvent(
            tool_name=tool_name,
            error=str(e),
            call_id=call_id,
            tool_execution_id=tool_part.tool_execution_id,
        )
