"""
HITL Tool Handlers - Extracted from SessionProcessor.

Handles Human-in-the-Loop tool interactions:
- Clarification requests (ask_clarification)
- Decision requests (request_decision)
- Environment variable requests (request_env_var)
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

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
from src.domain.model.agent.hitl_types import HITLPendingException, HITLType

from ..core.message import ToolPart, ToolState
from ..hitl.ray_hitl_handler import RayHITLHandler

logger = logging.getLogger(__name__)


def _ensure_dict(raw: Any) -> dict:
    """Ensure context argument is a dictionary."""
    if isinstance(raw, str):
        return {"description": raw} if raw else {}
    if isinstance(raw, dict):
        return raw.copy()
    return {}


async def handle_clarification_tool(
    handler: RayHITLHandler,
    call_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    tool_part: ToolPart,
) -> AsyncIterator[AgentDomainEvent]:
    """Handle clarification tool with SSE event emission via RayHITLHandler."""
    try:
        question = arguments.get("question", "")
        clarification_type = arguments.get("clarification_type", "custom")
        options_raw = arguments.get("options", [])
        allow_custom = arguments.get("allow_custom", True)
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)
        default_value = arguments.get("default_value")

        clarification_options = [
            {
                "id": opt.get("id", ""),
                "label": opt.get("label", ""),
                "description": opt.get("description"),
                "recommended": opt.get("recommended", False),
            }
            for opt in options_raw
        ]

        preinjected = handler.peek_preinjected_response(HITLType.CLARIFICATION)
        request_id = (
            preinjected.get("request_id")
            if preinjected and preinjected.get("request_id")
            else f"clar_{uuid.uuid4().hex[:8]}"
        )

        if not preinjected:
            yield AgentClarificationAskedEvent(
                request_id=request_id,
                question=question,
                clarification_type=clarification_type,
                options=clarification_options,
                allow_custom=allow_custom,
                context=context,
            )

        start_time = time.time()
        try:
            answer = await handler.request_clarification(
                question=question,
                options=clarification_options,
                clarification_type=clarification_type,
                allow_custom=allow_custom,
                timeout_seconds=timeout,
                context=context,
                default_value=default_value,
                request_id=request_id,
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

        except asyncio.TimeoutError:
            tool_part.status = ToolState.ERROR
            tool_part.error = "Clarification request timed out"
            tool_part.end_time = time.time()

            yield AgentObserveEvent(
                tool_name=tool_name,
                error="Clarification request timed out",
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

    except HITLPendingException:
        raise

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
    handler: RayHITLHandler,
    call_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    tool_part: ToolPart,
) -> AsyncIterator[AgentDomainEvent]:
    """Handle decision tool with SSE event emission via RayHITLHandler."""
    try:
        question = arguments.get("question", "")
        decision_type = arguments.get("decision_type", "custom")
        options_raw = arguments.get("options", [])
        allow_custom = arguments.get("allow_custom", False)
        default_option = arguments.get("default_option")
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)

        decision_options = [
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

        preinjected = handler.peek_preinjected_response(HITLType.DECISION)
        request_id = (
            preinjected.get("request_id")
            if preinjected and preinjected.get("request_id")
            else f"deci_{uuid.uuid4().hex[:8]}"
        )

        if not preinjected:
            yield AgentDecisionAskedEvent(
                request_id=request_id,
                question=question,
                decision_type=decision_type,
                options=decision_options,
                allow_custom=allow_custom,
                default_option=default_option,
                context=context,
            )

        start_time = time.time()
        try:
            decision = await handler.request_decision(
                question=question,
                options=decision_options,
                decision_type=decision_type,
                allow_custom=allow_custom,
                timeout_seconds=timeout,
                context=context,
                default_option=default_option,
                request_id=request_id,
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

        except asyncio.TimeoutError:
            tool_part.status = ToolState.ERROR
            tool_part.error = "Decision request timed out"
            tool_part.end_time = time.time()

            yield AgentObserveEvent(
                tool_name=tool_name,
                error="Decision request timed out",
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

    except HITLPendingException:
        raise

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


async def handle_env_var_tool(
    handler: RayHITLHandler,
    call_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    tool_part: ToolPart,
    langfuse_context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[AgentDomainEvent]:
    """Handle environment variable request tool with SSE event emission."""
    try:
        target_tool_name = arguments.get("tool_name", "")
        fields_raw = arguments.get("fields", [])
        message = arguments.get("message")
        context = _ensure_dict(arguments.get("context", {}))
        timeout = arguments.get("timeout", 300.0)
        save_to_project = arguments.get("save_to_project", False)

        fields_for_sse: List[Dict[str, Any]] = []
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

        preinjected = handler.peek_preinjected_response(HITLType.ENV_VAR)
        request_id = (
            preinjected.get("request_id")
            if preinjected and preinjected.get("request_id")
            else f"envvar_{uuid.uuid4().hex[:8]}"
        )

        if not preinjected:
            yield AgentEnvVarRequestedEvent(
                request_id=request_id,
                tool_name=target_tool_name,
                fields=fields_for_sse,
                context=context if context else {},
            )

        start_time = time.time()
        try:
            values = await handler.request_env_vars(
                tool_name=target_tool_name,
                fields=fields_for_sse,
                message=message,
                timeout_seconds=timeout,
                request_id=request_id,
            )
            end_time = time.time()

            saved_variables: List[str] = []
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

        except asyncio.TimeoutError:
            tool_part.status = ToolState.ERROR
            tool_part.error = "Environment variable request timed out"
            tool_part.end_time = time.time()

            yield AgentObserveEvent(
                tool_name=tool_name,
                error="Environment variable request timed out",
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

    except HITLPendingException:
        raise

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
    values: Dict[str, str],
    fields_for_sse: List[Dict[str, Any]],
    target_tool_name: str,
    tenant_id: str,
    project_id: Optional[str],
    save_to_project: bool,
) -> List[str]:
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
    saved_variables: List[str] = []

    async with async_session_factory() as db_session:
        repository = SqlToolEnvironmentVariableRepository(db_session)
        for field_spec in fields_for_sse:
            var_name = field_spec["name"]
            if var_name in values and values[var_name]:
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
