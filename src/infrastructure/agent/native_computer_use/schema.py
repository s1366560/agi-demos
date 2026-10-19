"""Device schemas have local references and cannot perform network retrieval."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry

from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError


def validator(schema: dict[str, Any]) -> Draft202012Validator:
    pending: list[object] = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            for key in ("$ref", "$dynamicRef", "$recursiveRef"):
                reference = node.get(key)
                if reference is not None and (
                    not isinstance(reference, str) or not reference.startswith("#")
                ):
                    raise DeviceBridgeError("computer_use_external_schema_reference")
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    try:
        Draft202012Validator.check_schema(schema)
        # Empty Registry's retrieval function always rejects missing resources.
        return Draft202012Validator(schema, registry=Registry())
    except Exception as exc:
        raise DeviceBridgeError("computer_use_invalid_schema") from exc
