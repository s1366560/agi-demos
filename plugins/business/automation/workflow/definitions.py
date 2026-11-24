"""Persist schedule workflow revisions through the worker's private project record channel."""

from __future__ import annotations

import json
import sys
from typing import Any
from uuid import uuid4


def records(method: str, **params: object) -> dict[str, Any]:
    request_id = str(uuid4())
    print(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": f"memstack/records/{method}",
                "params": params,
            },
            allow_nan=False,
        ),
        flush=True,
    )
    response = json.loads(sys.stdin.readline())
    if response.get("id") != request_id or not isinstance(response.get("result"), dict):
        raise ValueError("Project record request failed")
    return response["result"]


def save(arguments: dict[str, Any]) -> dict[str, Any]:
    workflow_id = arguments["id"]
    prior_revision = arguments["expected_revision"]
    if prior_revision and not records("get", key=key(workflow_id, prior_revision))["document"]:
        return {"saved": False, "revision": prior_revision}
    revision = prior_revision + 1
    document = {
        "id": workflow_id,
        "revision": revision,
        "name": arguments["name"],
        "intervals": arguments["intervals"],
    }
    new_key = key(workflow_id, revision)
    created = records("create", key=new_key, document=document)["created"]
    saved = created or records("get", key=new_key)["document"] == document
    return {"saved": saved, "revision": revision}


def key(workflow_id: str, revision: int) -> str:
    return f"{workflow_id}_{revision:09d}"


def load(workflow_id: str, revision: int) -> dict[str, Any]:
    result = records("get", key=key(workflow_id, revision))["document"]
    if not isinstance(result, dict):
        raise ValueError("Workflow revision does not exist")
    return result


def list_revisions(arguments: dict[str, Any]) -> dict[str, Any]:
    page = records("list", **arguments)
    return {
        "items": [records("get", key=item)["document"] for item in page["keys"]],
        "next_cursor": page["next_cursor"],
    }
