#!/usr/local/bin/python
"""Invoice lifecycle and pricing operations over the package's private MCP connection."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

# Distributed as a standalone program with these two package-owned modules.
from invoice_contract import contribution
from invoice_record import BillingInvoiceRecordV2, invoice_payload

ROOT = Path(__file__).resolve().parent
PLANS = json.loads((ROOT / "plans.json").read_bytes())
TERMS_DAYS = json.loads((ROOT / "invoice_terms.json").read_bytes())["due_days"]
if type(TERMS_DAYS) is not int or not 0 <= TERMS_DAYS <= 365:
    raise ValueError("invoice terms must be between zero and 365 days")


def _release_tools() -> list[dict[str, Any]]:
    """Worker operations plus the host tools declared beside this package."""
    worker_tools = contribution(PLANS)["tools"]
    names = {tool["name"] for tool in worker_tools}
    for candidate in (ROOT / "contributions.json", ROOT.parent / "contributions.json"):
        if candidate.is_file():
            document = json.loads(candidate.read_bytes())
            return [
                *worker_tools,
                *(tool for tool in document["tools"] if tool["name"] not in names),
            ]
    return worker_tools


def _wire_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "inputSchema": tool["input_schema"],
        "outputSchema": tool["output_schema"],
    }


def send(message: dict[str, Any]) -> None:
    print(
        json.dumps({"jsonrpc": "2.0", **message}, separators=(",", ":"), allow_nan=False),
        flush=True,
    )


def host_call(method: str, **params: object) -> dict[str, Any]:
    identity = str(uuid4())
    send({"id": identity, "method": method, "params": params})
    result = json.loads(sys.stdin.readline())
    if result.get("id") != identity or not isinstance(result.get("result"), dict):
        raise ValueError("host request did not complete")
    return result["result"]


def records(method: str, **params: object) -> dict[str, Any]:
    return host_call("memstack/records/" + method, **params)


def moment(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if not instant.tzinfo:
        raise ValueError("expected a timezone")
    return instant.astimezone(UTC)


def create(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        start = moment(arguments["period_start"])
        end = moment(arguments["period_end"])
        due = end + timedelta(days=TERMS_DAYS)
        if start >= end:
            raise ValueError("invalid period")
    except (OverflowError, ValueError):
        return {"invoice": None, "error": "invalid_period"}
    identity = hashlib.sha256(arguments["idempotency_key"].encode()).hexdigest()
    invoice = invoice_payload(
        BillingInvoiceRecordV2(
            id=identity,
            amount=arguments["amount"],
            currency=arguments["currency"],
            status="pending",
            period_start=start,
            period_end=end,
            created_at=datetime.now(UTC),
            invoice_url=None,
            paid_at=None,
        )
    )
    invoice["due_at"] = due.isoformat()
    if records("create", key=identity, document=invoice)["created"]:
        return {"invoice": invoice, "error": None}
    prior = records("get", key=identity)["document"]
    if any(
        prior[key] != invoice[key] for key in ("amount", "currency", "period_start", "period_end")
    ):
        return {"invoice": None, "error": "idempotency_conflict"}
    return {"invoice": prior, "error": None}


def invoke(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "quote":
        if sys.argv[0] == "/app/invoice-worker-with-plan-service":
            return host_call("memstack/services/call", alias="plans", input=args)
        return {"plan": args["plan"], "storage_limit": PLANS[args["plan"]]}
    if name == "invoice.create":
        return create(args)
    if name == "invoice.get":
        value = records("get", key=args["id"])["document"]
        return {"invoice": value, "error": None if value else "not_found"}
    if name == "invoice.list":
        page = records("list", **args)
        return {
            "invoices": [records("get", key=key)["document"] for key in page["keys"]],
            "next_cursor": page["next_cursor"],
        }
    raise ValueError("unsupported invoice operation")


def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        params = request.get("params", {})
        if "id" not in request:
            continue
        if method == "initialize":
            result = {
                "protocolVersion": params["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memstack-billing", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": [_wire_tool(tool) for tool in _release_tools()]}
        elif method == "tools/call":
            progress = params.get("_meta", {}).get("progressToken")
            if (
                progress
                and params["name"] == "quote"
                and sys.argv[0] == "/app/invoice-worker-with-plan-service"
            ):
                send(
                    {
                        "method": "notifications/progress",
                        "params": {"progressToken": progress, "progress": 0, "total": 1},
                    }
                )
            result = {
                "content": [],
                "structuredContent": invoke(params["name"], params["arguments"]),
            }
        else:
            send({"id": request["id"], "error": {"code": -32601, "message": "unknown method"}})
            continue
        send({"id": request["id"], "result": result})


if __name__ == "__main__":
    main()
