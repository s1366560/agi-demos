"""Drone CI/CD tools provided by the local Drone plugin."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from src.application.services.cicd_pipeline_service import (
    CicdPipelineError,
    CicdPipelineRunRequest,
    CicdPipelineService,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace_plan.pipeline import DRONE_PROVIDER

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.context import ToolContext

logger = logging.getLogger(__name__)

CICD_RUN_PIPELINE_TOOL_NAME = "cicd_run_pipeline"

CICD_RUN_PIPELINE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository": {
            "type": "string",
            "description": "Drone repository slug in '<owner>/<repo>' format. Required for ordinary chat CI/CD.",
        },
        "repo": {
            "type": "string",
            "description": "Alias for repository in '<owner>/<repo>' format.",
        },
        "provider": {
            "type": "string",
            "description": "CI/CD provider to run. The Drone plugin provides 'drone'.",
            "default": DRONE_PROVIDER,
        },
        "branch": {"type": "string", "description": "Optional Drone branch override."},
        "commit": {"type": "string", "description": "Optional Drone commit SHA override."},
        "target": {"type": "string", "description": "Optional Drone deployment target."},
        "params": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Optional Drone build parameter overrides.",
        },
        "wait": {
            "type": "boolean",
            "description": "Wait for the Drone run to finish before returning.",
            "default": True,
        },
        "reason": {
            "type": "string",
            "description": "Short reason for the CI/CD run, stored with pipeline evidence.",
        },
    },
}


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


@tool_define(
    name=CICD_RUN_PIPELINE_TOOL_NAME,
    description=(
        "Run the configured Drone CI/CD pipeline for a repository from ordinary chat. "
        "Use this to trigger, wait for, persist, and summarize Drone pipeline evidence without "
        "entering or selecting a workspace task harness. Always provide repository as owner/repo."
    ),
    parameters=CICD_RUN_PIPELINE_PARAMETERS,
    permission=None,
    category="cicd",
    tags=frozenset({"cicd", "pipeline", "drone"}),
)
async def cicd_run_pipeline_tool(
    ctx: ToolContext,
    *,
    repository: str | None = None,
    repo: str | None = None,
    provider: str = DRONE_PROVIDER,
    branch: str | None = None,
    commit: str | None = None,
    target: str | None = None,
    params: dict[str, str] | None = None,
    wait: bool = True,
    reason: str | None = None,
) -> ToolResult:
    """Run a repository CI/CD pipeline from a normal chat turn."""

    try:
        async with async_session_factory() as session:
            service = CicdPipelineService(session)
            summary = await service.run_pipeline(
                CicdPipelineRunRequest(
                    conversation_id=ctx.conversation_id,
                    project_id=ctx.project_id,
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    repository=repository or repo,
                    provider=provider,
                    branch=branch,
                    commit=commit,
                    target=target,
                    params=params,
                    wait=wait,
                    reason=reason,
                )
            )
            payload = {"ok": True, **summary.to_json()}
            return ToolResult(
                output=_json(payload),
                title="CI/CD pipeline completed",
                metadata=payload,
                is_error=summary.status != "success",
            )
    except CicdPipelineError as exc:
        payload = {"ok": False, "error": str(exc), "code": exc.code, **exc.metadata}
        return ToolResult(
            output=_json(payload),
            title="CI/CD pipeline rejected",
            metadata=payload,
            is_error=True,
        )
    except Exception as exc:
        logger.exception("ordinary chat CI/CD pipeline failed")
        payload = {
            "ok": False,
            "error": str(exc).strip() or exc.__class__.__name__,
            "code": "cicd_pipeline_unhandled_error",
        }
        return ToolResult(
            output=_json(payload),
            title="CI/CD pipeline failed",
            metadata=payload,
            is_error=True,
        )


__all__ = [
    "CICD_RUN_PIPELINE_PARAMETERS",
    "CICD_RUN_PIPELINE_TOOL_NAME",
    "cicd_run_pipeline_tool",
]
