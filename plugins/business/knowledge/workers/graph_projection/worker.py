#!/usr/local/bin/python
"""Build portable graph records from one project-authorized extraction result."""

import json
import sys
from pathlib import Path
from typing import Any


def project(inputs: dict[str, Any]) -> dict[str, Any]:
    nodes = inputs["nodes"]
    positions = {n["uuid"]: i for i, n in enumerate(nodes)}
    relationships = []
    for edge in inputs["edges"]:
        if edge["source"] not in positions or edge["target"] not in positions:
            continue
        relationships.append(
            {
                "source_index": positions[edge["source"]],
                "target_index": positions[edge["target"]],
                "relation_type": edge["kind"],
                "fact": edge["fact"] or edge["kind"],
                "score": edge["score"],
            }
        )
    return {
        "entities": [{"name": n["name"], "kind": n["kind"]} for n in nodes],
        "relationships": relationships,
    }


def main() -> None:
    tools = json.loads(Path(__file__).with_name("contributions.json").read_bytes())["tools"]
    tool = tools[0]
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue
        params = message.get("params", {})
        method = message["method"]
        if method == "initialize":
            result = {
                "protocolVersion": params["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "graph-projection", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": item["name"],
                        "inputSchema": item["input_schema"],
                        "outputSchema": item["output_schema"],
                    }
                    for item in tools
                ]
            }
        elif method == "tools/call" and params["name"] == tool["name"]:
            result = {"content": [], "structuredContent": project(params["arguments"])}
        else:
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32601, "message": "unknown method"},
                    }
                ),
                flush=True,
            )
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)


if __name__ == "__main__":
    main()
