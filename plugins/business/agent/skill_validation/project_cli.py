"""Validate explicit local skill documents with their selected project's signed release."""

import json
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path


def validate_project(documents: Iterable[Path], *, tenant: str, project: str, strict: bool) -> bool:
    from memstack_cli.auth import resolve_api_key
    from memstack_cli.client import request

    base = "/platform-plugins/v2/optional-business/memstack-agent"
    key = resolve_api_key(None)
    scope = {"tenant_id": tenant, "project_id": project}
    view = request("GET", base, api_key=key, params=scope)
    digest = view.get("actual_digest")
    if not digest:
        raise ValueError("The project has no active Skill validation release.")
    contract = json.loads(
        files("plugins.business.agent").joinpath("contributions.json").read_text()
    )
    operation = next(tool for tool in contract["tools"] if tool["name"] == "validate_skill")
    limit = operation["input_schema"]["properties"]["content"]["maxLength"]
    all_valid = True
    for document in documents:
        with document.open(encoding="utf-8") as stream:
            content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValueError(f"{document} exceeds the signed tool input limit")
        result = request(
            "POST",
            base + "/invoke",
            api_key=key,
            json={
                **scope,
                "expected_digest": digest,
                "tool_name": "validate_skill",
                "payload": {"content": content, "strict": strict},
            },
        )
        print(json.dumps(result, ensure_ascii=False))
        all_valid = all_valid and result["is_valid"] is True
    return all_valid
