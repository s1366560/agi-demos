"""Run the Skill validation contribution over MCP stdio."""

from __future__ import annotations

import asyncio
import json
from importlib.resources import files
from typing import Any

from .execution_statistics.aggregate import summarize
from .react_loop import react_loop
from .skill_validation.validator import AgentSkillsValidator


def validate_skill(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate caller-supplied Markdown in memory."""
    content = arguments.get("content")
    strict = arguments.get("strict", False)
    if set(arguments) - {"content", "strict"} or not isinstance(content, str):
        raise ValueError("expected SKILL.md content")
    if not isinstance(strict, bool):
        raise ValueError("strict must be a boolean")
    return AgentSkillsValidator(strict=strict).validate_content(content).to_dict()


async def _run() -> None:
    from mcp import types
    from mcp.server import Server, ServerRequestContext
    from mcp.server.stdio import stdio_server

    contributions = json.loads(files(__package__).joinpath("contributions.json").read_text())
    tools = [
        types.Tool(
            name=item["name"],
            description=item.get("description"),
            input_schema=item["input_schema"],
            output_schema=item["output_schema"],
        )
        for item in contributions["tools"]
    ]

    async def list_tools(
        _ctx: ServerRequestContext, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def call_tool(
        _ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        arguments = params.arguments or {}
        if params.name == "validate_skill":
            result = validate_skill(arguments)
        elif params.name == "react_loop":
            result = react_loop(arguments)
        elif params.name == "execution_statistics":
            result = summarize(arguments["events"])
        elif params.name.startswith("agent."):
            raise ValueError("agent commands run outside the OCI worker")
        else:
            raise ValueError("unknown tool")
        return types.CallToolResult(content=[], structured_content=result)

    server = Server("memstack-agent", on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


def main() -> None:
    asyncio.run(_run())
