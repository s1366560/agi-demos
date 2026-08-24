"""GitHub tool and Skill contributions owned by a protocol-v2 Fiber."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from src.domain.model.agent.skill import Skill
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
from src.infrastructure.agent.tools.result import ToolResult

from .agent_capabilities import AgentCapabilityCatalogProtocolV2
from .packaged_skill import build_packaged_skill_v2
from .runtime import ContextV2, RuntimeV2Error
from .tool_set import ToolSetCatalogProtocolV2, ToolSetV2

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.context import ToolContext

logger = logging.getLogger(__name__)

GITHUB_TOOL_NAME = "github"
GITHUB_TOOL_MODULE_V2 = "builtin://memstack/agent/tool/github"
GITHUB_SKILL_MODULE_V2 = "builtin://memstack/agent/skill/github"
GITHUB_TOOL_SERVICE_V2 = "service:agent-tool.github"
GITHUB_DEFAULTS_SERVICE_V2 = "service:github-defaults"
GITHUB_SECRET_PATHS_SERVICE_V2 = "service:github-secret-paths"

_GITHUB_SKILL_DIGEST_V2 = (
    "sha256:d2172a1c63aa7abc68c754df3a0421790f50cf016461dceaa29def89c87d1af6"
)
_GITHUB_TOOL_SOURCE_V2 = "builtin-github-tool"
_GITHUB_SKILL_SOURCE_V2 = "builtin-github-skill"
_GITHUB_PROFILE_DEFAULTS_V2: dict[str, object] = {
    "api_base_url": "https://api.github.com",
    "token_env": "GITHUB_TOKEN",
    "timeout_seconds": 30,
    "output_limit_chars": 40000,
}
_GITHUB_CONFIG_TO_TOOL_KWARGS_V2 = {
    "api_base_url": "api_base_url",
    "token_env": "token_env",
    "default_owner": "owner",
    "default_repo": "repo",
    "timeout_seconds": "timeout_seconds",
    "output_limit_chars": "output_limit_chars",
}

GitHubOperation = Literal[
    "get_repo",
    "list_issues",
    "get_issue",
    "create_issue",
    "list_pull_requests",
    "get_pull_request",
    "create_issue_comment",
    "search_repositories",
    "get_file",
    "list_commits",
]

_READ_OPERATIONS = {
    "get_repo",
    "list_issues",
    "get_issue",
    "list_pull_requests",
    "get_pull_request",
    "search_repositories",
    "get_file",
    "list_commits",
}
_WRITE_OPERATIONS = {"create_issue", "create_issue_comment"}
_DEFAULT_API_BASE_URL = "https://api.github.com"
_DEFAULT_TOKEN_ENV = "GITHUB_TOKEN"
_DEFAULT_TIMEOUT_SECONDS = 30
_DEFAULT_OUTPUT_LIMIT = 40000

GITHUB_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "operation": {
            "type": "string",
            "enum": sorted(_READ_OPERATIONS | _WRITE_OPERATIONS),
            "description": "GitHub operation to run.",
        },
        "owner": {"type": "string", "description": "Repository owner or organization."},
        "repo": {"type": "string", "description": "Repository name."},
        "issue_number": {"type": "integer", "minimum": 1},
        "pull_number": {"type": "integer", "minimum": 1},
        "title": {"type": "string", "description": "Issue title for create_issue."},
        "body": {"type": "string", "description": "Issue or comment body."},
        "state": {
            "type": "string",
            "enum": ["open", "closed", "all"],
            "description": "Issue or pull-request state filter.",
        },
        "query": {"type": "string", "description": "Search query for search_repositories."},
        "path": {"type": "string", "description": "Repository file path for get_file."},
        "ref": {"type": "string", "description": "Branch, tag, or SHA for file/commit queries."},
        "per_page": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
        "page": {"type": "integer", "minimum": 1, "default": 1},
        "include_content": {
            "type": "boolean",
            "default": False,
            "description": "Decode and include file content for get_file.",
        },
        "confirm_write": {
            "type": "boolean",
            "default": False,
            "description": "Required for mutating operations.",
        },
        "token_env": {
            "type": "string",
            "description": "Environment variable containing a GitHub token.",
        },
        "api_base_url": {"type": "string", "description": "GitHub API base URL."},
        "timeout_seconds": {"type": "integer", "minimum": 1},
        "output_limit_chars": {"type": "integer", "minimum": 1},
        "dry_run": {"type": "boolean", "default": False},
    },
    "required": ["operation"],
}


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _error(message: str, *, code: str, **metadata: object) -> ToolResult:
    payload = {"ok": False, "code": code, "error": message, **metadata}
    return ToolResult(
        output=_json(payload), title="GitHub request failed", metadata=payload, is_error=True
    )


def _limit_output(payload: dict[str, Any], limit: int) -> str:
    output = _json(payload)
    if len(output) <= limit:
        return output
    truncated = dict(payload)
    truncated["truncated"] = True
    truncated["original_chars"] = len(output)
    truncated["data"] = output[: max(0, limit - 200)]
    return _json(truncated)


def _clean_api_base_url(value: str | None) -> str | ToolResult:
    api_base_url = (value or os.environ.get("GITHUB_API_BASE_URL") or _DEFAULT_API_BASE_URL).rstrip(
        "/"
    )
    parsed = urllib.parse.urlparse(api_base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return _error(
            "api_base_url must be an http(s) URL",
            code="github_api_base_url_invalid",
            api_base_url=api_base_url,
        )
    return api_base_url


def _token_from_env(token_env: str | None) -> tuple[str | None, str]:
    env_name = (token_env or os.environ.get("GITHUB_TOKEN_ENV") or _DEFAULT_TOKEN_ENV).strip()
    return os.environ.get(env_name), env_name


def _require_repo(owner: str | None, repo: str | None) -> tuple[str, str] | ToolResult:
    if not owner or not repo:
        return _error(
            "owner and repo are required for this operation",
            code="github_repository_required",
        )
    return owner, repo


def _query(params: dict[str, object | None]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "", [])}
    return f"?{urllib.parse.urlencode(clean)}" if clean else ""


def _build_request(  # noqa: C901, PLR0911, PLR0912, PLR0913
    *,
    operation: str,
    api_base_url: str,
    token: str | None,
    owner: str | None,
    repo: str | None,
    issue_number: int | None,
    pull_number: int | None,
    title: str | None,
    body: str | None,
    state: str | None,
    query: str | None,
    path: str | None,
    ref: str | None,
    per_page: int,
    page: int,
) -> tuple[str, str, dict[str, object] | None] | ToolResult:
    method = "GET"
    payload: dict[str, object] | None = None

    if operation == "search_repositories":
        if not query:
            return _error("query is required", code="github_query_required")
        endpoint = f"/search/repositories{_query({'q': query, 'per_page': per_page, 'page': page})}"
    else:
        repo_ref = _require_repo(owner, repo)
        if isinstance(repo_ref, ToolResult):
            return repo_ref
        safe_owner = urllib.parse.quote(repo_ref[0], safe="")
        safe_repo = urllib.parse.quote(repo_ref[1], safe="")
        repo_path = f"/repos/{safe_owner}/{safe_repo}"

        if operation == "get_repo":
            endpoint = repo_path
        elif operation == "list_issues":
            endpoint = f"{repo_path}/issues{_query({'state': state or 'open', 'per_page': per_page, 'page': page})}"
        elif operation == "get_issue":
            if issue_number is None:
                return _error("issue_number is required", code="github_issue_number_required")
            endpoint = f"{repo_path}/issues/{issue_number}"
        elif operation == "create_issue":
            if not title:
                return _error("title is required", code="github_title_required")
            method = "POST"
            endpoint = f"{repo_path}/issues"
            payload = {"title": title, "body": body or ""}
        elif operation == "list_pull_requests":
            endpoint = f"{repo_path}/pulls{_query({'state': state or 'open', 'per_page': per_page, 'page': page})}"
        elif operation == "get_pull_request":
            if pull_number is None:
                return _error("pull_number is required", code="github_pull_number_required")
            endpoint = f"{repo_path}/pulls/{pull_number}"
        elif operation == "create_issue_comment":
            if issue_number is None:
                return _error("issue_number is required", code="github_issue_number_required")
            if not body:
                return _error("body is required", code="github_body_required")
            method = "POST"
            endpoint = f"{repo_path}/issues/{issue_number}/comments"
            payload = {"body": body}
        elif operation == "get_file":
            if not path:
                return _error("path is required", code="github_path_required")
            safe_path = urllib.parse.quote(path.lstrip("/"), safe="/")
            endpoint = f"{repo_path}/contents/{safe_path}{_query({'ref': ref})}"
        elif operation == "list_commits":
            endpoint = (
                f"{repo_path}/commits{_query({'sha': ref, 'per_page': per_page, 'page': page})}"
            )
        else:
            return _error(
                f"unsupported operation: {operation}", code="github_operation_unsupported"
            )

    url = f"{api_base_url}{endpoint}"
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "memstack-github-plugin",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
    return method, url, payload if payload is not None else None, request


def _request_json(request: urllib.request.Request, *, timeout_seconds: int) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return exc.code, {"error": body}


def _summarize_file_response(data: object, *, include_content: bool) -> object:
    if not isinstance(data, dict) or include_content is False:
        if isinstance(data, dict) and "content" in data:
            summarized = dict(data)
            summarized.pop("content", None)
            summarized["content_omitted"] = True
            return summarized
        return data
    content = data.get("content")
    encoding = data.get("encoding")
    if isinstance(content, str) and encoding == "base64":
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
        summarized = dict(data)
        summarized["decoded_content"] = decoded
        summarized.pop("content", None)
        return summarized
    return data


@tool_define(
    name=GITHUB_TOOL_NAME,
    description=(
        "Call common GitHub REST API operations for repositories, issues, pull requests, "
        "commits, search, and repository files. Mutating operations require confirm_write=true."
    ),
    parameters=GITHUB_PARAMETERS,
    permission=None,
    category="developer",
    tags=frozenset({"github", "repository", "developer"}),
)
async def github_tool(  # noqa: PLR0911, PLR0913
    ctx: ToolContext,
    *,
    operation: GitHubOperation,
    owner: str | None = None,
    repo: str | None = None,
    issue_number: int | None = None,
    pull_number: int | None = None,
    title: str | None = None,
    body: str | None = None,
    state: str | None = None,
    query: str | None = None,
    path: str | None = None,
    ref: str | None = None,
    per_page: int = 30,
    page: int = 1,
    include_content: bool = False,
    confirm_write: bool = False,
    token_env: str | None = None,
    api_base_url: str | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    output_limit_chars: int = _DEFAULT_OUTPUT_LIMIT,
    dry_run: bool = False,
) -> ToolResult:
    del ctx

    if operation in _WRITE_OPERATIONS and not confirm_write:
        return _error(
            "confirm_write=true is required for mutating GitHub operations",
            code="github_write_confirmation_required",
            operation=operation,
        )

    token, resolved_token_env = _token_from_env(token_env)
    if operation in _WRITE_OPERATIONS and not token:
        return _error(
            f"{resolved_token_env} is required for mutating GitHub operations",
            code="github_token_required",
            token_env=resolved_token_env,
        )

    resolved_api_base_url = _clean_api_base_url(api_base_url)
    if isinstance(resolved_api_base_url, ToolResult):
        return resolved_api_base_url

    request_info = _build_request(
        operation=operation,
        api_base_url=resolved_api_base_url,
        token=token,
        owner=owner,
        repo=repo,
        issue_number=issue_number,
        pull_number=pull_number,
        title=title,
        body=body,
        state=state,
        query=query,
        path=path,
        ref=ref,
        per_page=max(1, min(100, per_page)),
        page=max(1, page),
    )
    if isinstance(request_info, ToolResult):
        return request_info

    method, url, payload, request = request_info
    metadata: dict[str, Any] = {
        "ok": True,
        "operation": operation,
        "method": method,
        "url": url,
        "token_env": resolved_token_env,
        "authenticated": bool(token),
    }
    if payload is not None:
        metadata["request"] = payload
    if dry_run:
        return ToolResult(output=_json(metadata), title="GitHub request dry run", metadata=metadata)

    try:
        status, data = await asyncio.to_thread(
            _request_json,
            request,
            timeout_seconds=max(1, timeout_seconds),
        )
    except Exception:
        logger.exception("GitHub V2 contribution request failed")
        return _error("GitHub request failed", code="github_request_failed")

    if operation == "get_file":
        data = _summarize_file_response(data, include_content=include_content)
    ok = 200 <= status < 300
    result_payload = {**metadata, "ok": ok, "status": status, "data": data}
    return ToolResult(
        output=_limit_output(result_payload, max(1, output_limit_chars)),
        title="GitHub request completed" if ok else "GitHub request failed",
        metadata=result_payload,
        is_error=not ok,
    )


@dataclass(frozen=True, kw_only=True)
class GitHubToolCapabilityV2:
    """Immutable marker and defaults exposed by the active GitHub Fiber."""

    source_id: str
    defaults: Mapping[str, object]


def _configured_github_tool_v2(config: Mapping[str, object]) -> ToolInfo:
    merged_config = {**_GITHUB_PROFILE_DEFAULTS_V2, **dict(config)}
    defaults = {
        tool_key: value
        for config_key, tool_key in _GITHUB_CONFIG_TO_TOOL_KWARGS_V2.items()
        if (value := merged_config.get(config_key)) not in (None, "", [])
    }

    async def execute(ctx: ToolContext, **kwargs: object) -> object:
        merged = dict(defaults)
        merged.update({key: value for key, value in kwargs.items() if value is not None})
        return await github_tool.execute(ctx, **merged)

    wrapped = ToolInfo(
        name=github_tool.name,
        description=github_tool.description,
        parameters=github_tool.parameters,
        execute=execute,
        permission=github_tool.permission,
        category=github_tool.category,
        model_filter=github_tool.model_filter,
        tags=github_tool.tags,
        execution_context=github_tool.execution_context,
        dependencies=github_tool.dependencies,
        aliases=github_tool.aliases,
        sandbox_id=github_tool.sandbox_id,
        _sandbox_id=github_tool._sandbox_id,
    )
    return wrapped


def _github_tool_set_v2(tool: ToolInfo) -> ToolSetV2:
    from src.infrastructure.agent.core.tool_converter import convert_tools

    tools = {GITHUB_TOOL_NAME: tool}
    return ToolSetV2(
        tools=MappingProxyType(tools),
        definitions=tuple(convert_tools(tools)),
    )


def _apply_github_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> object:
    source_id = config.get("source_id")
    if source_id != _GITHUB_TOOL_SOURCE_V2:
        raise ValueError("GitHub tool contribution requires source_id builtin-github-tool")
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "GitHub tool contribution received an invalid tool catalog",
        )
    contribution_config = {
        key: value for key, value in config.items() if key != "source_id"
    }
    defaults = MappingProxyType({**_GITHUB_PROFILE_DEFAULTS_V2, **contribution_config})
    capability = GitHubToolCapabilityV2(source_id=source_id, defaults=defaults)
    _ = context.provide(
        GITHUB_TOOL_SERVICE_V2,
        capability,
        label="github-tool-capability",
    )
    _ = context.provide(
        GITHUB_DEFAULTS_SERVICE_V2,
        defaults,
        label="github-defaults",
    )
    _ = context.provide(
        GITHUB_SECRET_PATHS_SERVICE_V2,
        ("token_env",),
        label="github-secret-paths",
    )
    tool = _configured_github_tool_v2(defaults)
    return catalog.register_tools(source_id, lambda **_kwargs: _github_tool_set_v2(tool))


def _github_skills_v2(
    *,
    tenant_id: str,
    project_id: str,
    **_kwargs: object,
) -> list[Skill]:
    return [
        build_packaged_skill_v2(
            skill_name="github",
            expected_digest=_GITHUB_SKILL_DIGEST_V2,
            tenant_id=tenant_id,
            project_id=None,
        )
    ]


def _apply_github_skill_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> object:
    source_id = config.get("source_id")
    if source_id != _GITHUB_SKILL_SOURCE_V2:
        raise ValueError("GitHub Skill contribution requires source_id builtin-github-skill")
    catalog = context.require("catalog")
    if not isinstance(catalog, AgentCapabilityCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "GitHub Skill contribution received an invalid capability catalog",
        )
    tool = context.require("tool")
    if not isinstance(tool, GitHubToolCapabilityV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "GitHub Skill contribution requires the GitHub tool capability",
        )
    return catalog.register_skills(source_id, _github_skills_v2)


__all__ = [
    "GITHUB_DEFAULTS_SERVICE_V2",
    "GITHUB_PARAMETERS",
    "GITHUB_SECRET_PATHS_SERVICE_V2",
    "GITHUB_SKILL_MODULE_V2",
    "GITHUB_TOOL_MODULE_V2",
    "GITHUB_TOOL_NAME",
    "GITHUB_TOOL_SERVICE_V2",
    "GitHubToolCapabilityV2",
    "github_tool",
]
