#!/usr/local/bin/python
"""Preview a schedule through MCP stdio without creating jobs or dispatching any work."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from triggers import next_scheduled_run
from workflow.engine import AsyncioWorkflowEngine
from workflow.tasks import TaskManager

TOOLS = json.loads(Path(__file__).with_name("contributions.json").read_text())["tools"]


async def run_schedule_workflow(steps: list[dict[str, Any]]) -> dict[str, Any]:
    manager = TaskManager()
    engine = AsyncioWorkflowEngine(manager=manager)

    async def evaluate(step: dict[str, Any]) -> dict[str, str | None]:
        return next_scheduled_run(step)

    engine.register_handler("next_scheduled_run", evaluate)
    results = []
    try:
        for index, step in enumerate(steps):
            execution = await engine.start_workflow(
                "next_scheduled_run", str(index), step, task_queue="automation"
            )
            finished = await engine.get_workflow_result(execution.workflow_id)
            results.append(finished["result"])
    finally:
        await manager.close()
    return {"results": results}


def dispatch(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": params["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "memstack-automation", "version": "1"},
        }
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": tool["name"],
                    "inputSchema": tool["input_schema"],
                    "outputSchema": tool["output_schema"],
                }
                for tool in TOOLS
            ]
        }
    if method == "tools/call" and params.get("name") == "run_schedule_workflow":
        return {
            "content": [],
            "structuredContent": asyncio.run(run_schedule_workflow(params["arguments"]["steps"])),
        }
    if method == "tools/call" and params.get("name") == "next_scheduled_run":
        return {"content": [], "structuredContent": next_scheduled_run(params["arguments"])}
    raise ValueError("unsupported operation")


def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        response = {"jsonrpc": "2.0", "id": request["id"]}
        try:
            response["result"] = dispatch(request["method"], request.get("params", {}))
        except (KeyError, TypeError, ValueError, OverflowError):
            response["error"] = {"code": -32602, "message": "Invalid schedule"}
        print(json.dumps(response, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
