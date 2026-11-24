#!/usr/local/bin/python
"""Preview a schedule through MCP stdio without creating jobs or dispatching any work."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from triggers import next_scheduled_run
from workflow import definitions
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
    if method == "tools/call":
        args, name = params["arguments"], params["name"]
        if name == "save_schedule_workflow":
            result = definitions.save(args)
        elif name == "list_schedule_workflows":
            result = definitions.list_revisions(args)
        elif name == "execute_schedule_workflow":
            definition = definitions.load(args["id"], args["revision"])
            steps = [
                {"kind": "every", "config": {"interval_seconds": interval}, "start": args["start"]}
                for interval in definition["intervals"]
            ]
            result = asyncio.run(run_schedule_workflow(steps))
        elif name == "run_schedule_workflow":
            result = asyncio.run(run_schedule_workflow(args["steps"]))
        elif name == "next_scheduled_run":
            result = next_scheduled_run(args)
        else:
            raise ValueError("unsupported operation")
        return {"content": [], "structuredContent": result}
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
