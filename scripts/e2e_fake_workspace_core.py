"""Serve the frozen Workspace public API capability document for browser E2E."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = _ROOT / "docs/architecture/workspace-core-route-manifest.json"
_CONTRACT = "a0d6fb2d3ae01d30e767c184b29f07544cb33d86b9c55ee04391cb7f40117c30"
_KEYS = "d58c38e884a298e4dc9b9aa4ab8ff7ab4694adb3def80719d9c71c4646ae02db"


def _payload() -> bytes:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    routes = [{"method": route["method"], "path": route["path"]} for route in manifest["routes"]]
    body = {
        "protocol_version": 1,
        "manifest_version": manifest["manifestVersion"],
        "required_contract_sha256": _CONTRACT,
        "required_route_count": manifest["routeCount"],
        "required_route_keys_sha256": _KEYS,
        "implemented_contract_sha256": _CONTRACT,
        "implemented_route_count": manifest["routeCount"],
        "implemented_route_keys_sha256": _KEYS,
        "implemented_routes": routes,
        "complete": True,
    }
    return json.dumps(body).encode()


_BODY = _payload()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        capability = self.path.startswith("/internal/v1/capabilities/workspace-public-api")
        body = _BODY if capability else b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    ThreadingHTTPServer(("127.0.0.1", 4321), _Handler).serve_forever()


if __name__ == "__main__":
    main()
