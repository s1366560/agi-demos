"""Signed MCP tool schemas shared between the package builder and the isolated worker."""

from typing import Any


def obj(properties: dict[str, Any], *required: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


IDENTIFIER = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
TEXT = {"type": "string", "maxLength": 64}
MONEY = {"type": "integer", "minimum": 0, "maximum": 2147483647}
FIELDS = {
    "id": IDENTIFIER,
    "amount": MONEY,
    "currency": {"type": "string"},
    "status": {"enum": ["pending"]},
    "period_start": TEXT,
    "period_end": TEXT,
    "created_at": TEXT,
    "due_at": TEXT,
    "paid_at": {"type": "null"},
    "invoice_url": {"type": "null"},
}
INVOICE = obj(FIELDS, *FIELDS)
RESULT = obj(
    {
        "invoice": {"oneOf": [INVOICE, {"type": "null"}]},
        "error": {"enum": ["not_found", "invalid_period", "idempotency_conflict", None]},
    },
    "invoice",
    "error",
)
CREATE = {
    "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
    "amount": MONEY,
    "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
    "period_start": TEXT,
    "period_end": TEXT,
}


def contribution(plans: dict[str, int]) -> dict[str, Any]:
    def tool(
        name: str, inputs: dict[str, Any], output: dict[str, Any], *access: str
    ) -> dict[str, Any]:
        return {
            "name": name,
            "abi": "mcp.stdio",
            "input_schema": inputs,
            "output_schema": output,
            "permissions": ["tools.execute", *access],
        }

    return {
        "schema": "memstack.plugin.contributions/1",
        "tools": [
            tool(
                "quote",
                obj({"plan": {"enum": list(plans)}}, "plan"),
                obj(
                    {"plan": TEXT, "storage_limit": {"type": "integer", "minimum": 0}},
                    "plan",
                    "storage_limit",
                ),
            ),
            tool("invoice.create", obj(CREATE, *CREATE), RESULT, "storage.read", "storage.write"),
            tool("invoice.get", obj({"id": IDENTIFIER}, "id"), RESULT, "storage.read"),
            tool(
                "invoice.list",
                obj(
                    {"after": IDENTIFIER, "limit": {"type": "integer", "minimum": 1, "maximum": 16}}
                ),
                obj(
                    {
                        "invoices": {"type": "array", "items": INVOICE, "maxItems": 16},
                        "next_cursor": {"oneOf": [IDENTIFIER, {"type": "null"}]},
                    },
                    "invoices",
                    "next_cursor",
                ),
                "storage.read",
            ),
        ],
        "storage": {"schema_version": 1, "permissions": ["storage.read", "storage.write"]},
    }
