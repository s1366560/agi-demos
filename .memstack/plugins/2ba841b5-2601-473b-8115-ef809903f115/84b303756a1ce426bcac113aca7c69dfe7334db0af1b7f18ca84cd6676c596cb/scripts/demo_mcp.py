"""Dependency-free JSON-lines MCP example for actual marketplace acceptance."""

import json
import sys

HTML = "<!doctype html><html><body><h1>Marketplace Demo</h1><p>Plugin app is available.</p></body></html>"
RESOURCE = {"uri": "ui://demo/example.html", "name": "Marketplace Demo", "mimeType": "text/html;profile=mcp-app"}


def dispatch(method, params):
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}, "resources": {}}, "serverInfo": {"name": "marketplace-demo", "version": "1.0.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": "echo", "description": "Return the supplied text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, "_meta": {"ui": {"resourceUri": RESOURCE["uri"]}}}]}
    if method == "tools/call" and params.get("name") == "echo":
        return {"content": [{"type": "text", "text": str(params.get("arguments", {}).get("text", ""))}]}
    if method == "resources/list":
        return {"resources": [RESOURCE]}
    if method == "resources/read" and params.get("uri") == RESOURCE["uri"]:
        return {"contents": [{**RESOURCE, "text": HTML}]}
    raise ValueError("Unknown method or resource")


for line in sys.stdin:
    try:
        request = json.loads(line)
        if "id" not in request:
            continue
        try:
            response = {"jsonrpc": "2.0", "id": request["id"], "result": dispatch(request["method"], request.get("params", {}))}
        except ValueError as error:
            response = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": str(error)}}
        print(json.dumps(response), flush=True)
    except (ValueError, KeyError):
        print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid request"}}), flush=True)
