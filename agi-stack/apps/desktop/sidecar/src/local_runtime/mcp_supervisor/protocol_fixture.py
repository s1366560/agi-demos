"""Owned stdio MCP fixture; no network, credentials, or user data."""
import json
import sys
import time
from pathlib import Path

mode = sys.argv[1]
root = Path(__file__).parent
collections = {
    "tools/list": ("tools", [
        {"name": "read_record", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
        {"name": "write_record", "inputSchema": {"type": "object"}},
    ]),
    "resources/list": ("resources", [
        {"name": "First", "uri": "fixture://first"},
        {"name": "Second", "uri": "fixture://second"},
    ]),
    "resources/templates/list": ("resourceTemplates", [
        {"name": "Item", "uriTemplate": "fixture://item/{id}"},
        {"name": "Record", "uriTemplate": "fixture://record/{id}"},
    ]),
    "prompts/list": ("prompts", [
        {"name": "describe"},
        {"name": "summarize", "arguments": [{"name": "text", "required": True}]},
    ]),
}
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    params = request.get("params", {})
    if method != "initialize":
        with (root / "requests.jsonl").open("a") as audit:
            audit.write(json.dumps({"method": method, "params": params}) + "\n")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}, "resources": {}, "prompts": {}}, "serverInfo": {"name": "pagination-fixture", "version": "1"}}
    elif method in collections:
        field, values = collections[method]
        cursor = params.get("cursor")
        if mode == "slow_page" and method == "tools/list":
            values[0]["_meta"] = {"ui": {"resourceUri": "ui://candidate/view.html"}}
            if cursor is None:
                (root / "page-started").touch()
                deadline = time.monotonic() + 10
                while not (root / "page-release").exists():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("owned fixture page was not released")
                    time.sleep(0.01)
        if cursor not in (None, "opaque + / cursor =="):
            raise ValueError("cursor was changed")
        result = {field: [values[0 if cursor is None else 1]]}
        if cursor is None or mode == "repeated":
            result["nextCursor"] = "opaque + / cursor =="
        if mode == "malformed":
            result["nextCursor"] = 42
    elif method == "prompts/get":
        result = {"messages": [
            {"role": "system" if mode == "bad_prompt" else "user", "content": {"type": "text", "text": params.get("arguments", {}).get("text", "")}},
            {"role": "assistant", "content": {"type": "resource", "resource": {"uri": "fixture://source", "text": "owned source"}}},
        ]}
    else:
        result = {"contents": []}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
