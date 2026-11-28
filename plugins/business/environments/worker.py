#!/usr/local/bin/python
"""Serve the Environments package's cluster health projection over MCP stdio."""

import json
import sys
from pathlib import Path

from backend.cluster_health import project_health
from text_patch import patch_text


def main() -> None:
    tools = json.loads(Path(__file__).with_name("contributions.json").read_bytes())["tools"]
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
                "serverInfo": {"name": "cluster-health", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": tool["name"],
                        "inputSchema": tool["input_schema"],
                        "outputSchema": tool["output_schema"],
                    }
                    for tool in tools
                ]
            }
        elif method == "tools/call" and params["name"] == "patch_text":
            try:
                result = {"content": [], "structuredContent": patch_text(**params["arguments"])}
            except ValueError as error:
                result = {"isError": True, "content": [{"type": "text", "text": str(error)}]}
        elif method == "tools/call" and params["name"] == "cluster_health":
            result = {"content": [], "structuredContent": project_health(params["arguments"])}
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
