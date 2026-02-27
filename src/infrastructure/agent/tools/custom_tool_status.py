"""Custom tool loading status -- built-in diagnostic tool.

Allows the agent (or user) to check whether custom tools loaded
successfully and inspect any import errors.
"""

from __future__ import annotations

import logging

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


@tool_define(
    name="custom_tools_status",
    description=(
        "Check the loading status of custom tools (from .memstack/tools/). "
        "Returns a summary of loaded tools and any import errors or "
        "warnings. Use this when a custom tool is missing or not working "
        "as expected."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    permission=None,
    category="diagnostics",
)
async def custom_tools_status(ctx: ToolContext) -> ToolResult:
    """Return custom tool loading diagnostics for the current project."""
    from src.infrastructure.agent.state.agent_worker_state import (
        get_custom_tool_diagnostics,
    )

    project_id: str = getattr(ctx, "project_id", None) or ""
    diagnostics = get_custom_tool_diagnostics(project_id)

    if not diagnostics:
        return ToolResult(
            output=(
                "No custom tools diagnostics available. "
                "Either no custom tools directory exists, or tools "
                "have not been loaded yet for this project."
            ),
        )

    lines: list[str] = []
    errors = [d for d in diagnostics if d.level == "error"]
    warnings = [d for d in diagnostics if d.level == "warning"]
    infos = [d for d in diagnostics if d.level == "info"]

    lines.append(
        f"Custom Tools Status: {len(infos)} loaded, {len(errors)} errors, {len(warnings)} warnings"
    )
    lines.append("")

    if errors:
        lines.append("ERRORS:")
        for d in errors:
            lines.append(f"  [{d.code}] {d.message}")
            lines.append(f"    File: {d.file_path}")
        lines.append("")

    if warnings:
        lines.append("WARNINGS:")
        for d in warnings:
            lines.append(f"  [{d.code}] {d.message}")
            lines.append(f"    File: {d.file_path}")
        lines.append("")

    if infos:
        lines.append("LOADED:")
        for d in infos:
            lines.append(f"  [{d.code}] {d.message}")
            lines.append(f"    File: {d.file_path}")

    return ToolResult(output="\n".join(lines))
