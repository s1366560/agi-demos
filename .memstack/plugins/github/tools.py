"""GitHub REST tools provided by the local GitHub plugin."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, Literal

from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.context import ToolContext

logger = logging.getLogger(__name__)

GITHUB_TOOL_NAME = "github"

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
    except Exception as exc:
        logger.exception("GitHub plugin request failed")
        return _error(str(exc) or exc.__class__.__name__, code="github_request_failed")

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


__all__ = ["GITHUB_PARAMETERS", "GITHUB_TOOL_NAME", "github_tool"]
