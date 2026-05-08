"""Sandbox MCP Tool Wrapper.

Wraps MCP tools from a sandbox instance as Agent tools with namespacing.
"""

from __future__ import annotations

import asyncio
import logging
import posixpath
import re
import shlex
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort
    from src.infrastructure.agent.tools.context import ToolContext
    from src.infrastructure.agent.tools.define import ToolInfo


from src.infrastructure.agent.permission.rules import classify_sandbox_tool_permission
from src.infrastructure.agent.tools.mcp_errors import (
    MCPToolError,
    MCPToolErrorClassifier,
    RetryConfig,
)

logger = logging.getLogger(__name__)

WORKSPACE_HARNESS_MAX_SINGLE_WRITE_CHARS = 64_000
WORKSPACE_HARNESS_MAX_BASH_COMMAND_CHARS = 6_000
WORKSPACE_HARNESS_MAX_EDIT_OLD_STRING_CHARS = 12_000
WORKSPACE_HARNESS_MAX_EDIT_NEW_STRING_CHARS = 64_000

_WORKSPACE_CODE_ROOT_DEFAULT_WORKDIR_TOOLS = frozenset(
    {
        "bash",
        "create_file",
        "read",
        "write",
        "edit",
        "glob",
        "grep",
        "list",
        "ls",
        "file_read",
        "file_write",
        "file_edit",
        "list_files",
    }
)
_WORKSPACE_CODE_ROOT_WRITE_TOOLS = frozenset(
    {"create_file", "write", "edit", "file_write", "file_edit"}
)
_PATH_ARGUMENT_KEYS = ("file_path", "path")
_WORKDIR_ARGUMENT_KEYS = ("working_dir", "cwd", "_workspace_dir")
_WORKSPACE_VERIFICATION_INTEGRITY_PHASES = frozenset({"test", "review"})
_WORKSPACE_VERIFICATION_SCRIPT_NAME_PATTERN = re.compile(
    r"(^|/)([^/]*(test|spec|e2e|integration|audit|benchmark)[^/]*"
    r"\.(js|jsx|ts|tsx|mjs|cjs|py|sh)|"
    r"(tests?|spec|e2e|integration|audit|benchmarks?)/.+"
    r"\.(js|jsx|ts|tsx|mjs|cjs|py|sh))$",
    re.I,
)
_WORKSPACE_VERIFICATION_OUTPUT_PATH_PREFIXES = (
    "coverage/",
    "playwright-report/",
    "reports/",
    "screenshots/",
    "test-results/",
)
_WORKSPACE_BASH_SCRIPT_MUTATION_PATTERN = re.compile(
    r"\b(?:sed\s+-i|perl\s+-pi|python\s+-c|node\s+-e|rm\s+|mv\s+|cp\s+|git\s+add\s+)",
    re.I,
)
_WORKSPACE_BASH_REDIRECT_TARGET_PATTERN = re.compile(r"(?:^|[\s;&|])(?:>|>>)\s*([^\s;&|]+)")
_WORKSPACE_BASH_ALLOWED_REDIRECT_TARGETS = frozenset({"/dev/null"})
_WORKSPACE_OUTPUT_ABSOLUTE_PATH_PATTERN = re.compile(r"/workspace(?:/[^\s'\"`<>{}\[\]|]+)?")
_WORKSPACE_OUTPUT_ARTIFACT_WRITE_HINTS = (
    "[screenshot]",
    "report saved",
    "reports saved",
    "results saved",
    "saved report",
    "saved results",
    "screenshot saved",
)
_WORKSPACE_OUTPUT_ARTIFACT_COMMAND_TOKENS = frozenset(
    {
        "bun",
        "jest",
        "node",
        "npm",
        "npx",
        "playwright",
        "pnpm",
        "pytest",
        "uv",
        "vitest",
        "yarn",
    }
)


def _convert_mcp_schema(input_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert MCP input_schema to agent tool JSON Schema format.

    Preserves the full JSON Schema structure including nested
    ``items`` for arrays and ``properties`` for objects so the LLM
    can generate correctly-shaped arguments (e.g. ``batch_edit``'s
    ``edits`` array of objects).

    Args:
        input_schema: Raw MCP tool input schema.

    Returns:
        Normalised JSON Schema dict with type/properties/required.
    """
    # The MCP input_schema is already valid JSON Schema.  We only
    # normalise top-level keys so the caller always sees a consistent
    # shape.  Critically, we preserve nested "items", "enum",
    # "properties", "required", "anyOf", etc. that previous code
    # was dropping.
    return {
        "type": input_schema.get("type", "object"),
        "properties": input_schema.get("properties", {}),
        "required": input_schema.get("required", []),
    }


def _append_limit_hint(description: str | None, hint: str) -> str:
    base = (description or "").strip()
    if hint in base:
        return base
    return f"{base} {hint}".strip()


def _apply_workspace_harness_limits(
    tool_name: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Inject hard argument limits for tools that commonly overflow JSON streams."""
    if tool_name not in {"write", "bash", "edit"}:
        return parameters

    limited = dict(parameters)
    properties = dict(limited.get("properties") or {})

    if tool_name == "write" and isinstance(properties.get("content"), dict):
        content_schema = dict(properties["content"])
        content_schema["maxLength"] = WORKSPACE_HARNESS_MAX_SINGLE_WRITE_CHARS
        content_schema["description"] = _append_limit_hint(
            content_schema.get("description"),
            (
                "HARD LIMIT: at most "
                f"{WORKSPACE_HARNESS_MAX_SINGLE_WRITE_CHARS} characters per call. "
                "Prefer one complete file write when the file fits; for longer files, "
                "write the first chunk then use mode='append' or focused edits."
            ),
        )
        properties["content"] = content_schema

    if tool_name == "bash" and isinstance(properties.get("command"), dict):
        command_schema = dict(properties["command"])
        command_schema["maxLength"] = WORKSPACE_HARNESS_MAX_BASH_COMMAND_CHARS
        command_schema["description"] = _append_limit_hint(
            command_schema.get("description"),
            (
                "HARD LIMIT: at most 6000 characters per command. "
                "Do not embed large heredocs; use short append/edit steps instead. "
                "Do not run dev servers or watch commands in the foreground. For "
                "long-running processes, use nohup with log redirection and write "
                "the PID, then verify with a separate short health-check command."
            ),
        )
        properties["command"] = command_schema

    if tool_name == "edit":
        if isinstance(properties.get("old_string"), dict):
            old_string_schema = dict(properties["old_string"])
            old_string_schema["maxLength"] = WORKSPACE_HARNESS_MAX_EDIT_OLD_STRING_CHARS
            old_string_schema["description"] = _append_limit_hint(
                old_string_schema.get("description"),
                (
                    "HARD LIMIT: at most "
                    f"{WORKSPACE_HARNESS_MAX_EDIT_OLD_STRING_CHARS} characters. "
                    "Use the smallest exact snippet copied from a fresh read. "
                    "Prefer one unique line or a small adjacent block; avoid replacing "
                    "whole functions when whitespace may differ."
                ),
            )
            properties["old_string"] = old_string_schema
        if isinstance(properties.get("new_string"), dict):
            new_string_schema = dict(properties["new_string"])
            new_string_schema["maxLength"] = WORKSPACE_HARNESS_MAX_EDIT_NEW_STRING_CHARS
            new_string_schema["description"] = _append_limit_hint(
                new_string_schema.get("description"),
                (
                    "HARD LIMIT: at most "
                    f"{WORKSPACE_HARNESS_MAX_EDIT_NEW_STRING_CHARS} characters. "
                    "For larger rewrites, use write for the complete file or split into "
                    "multiple focused edit calls."
                ),
            )
            properties["new_string"] = new_string_schema

    limited["properties"] = properties
    return limited


def _normalize_workspace_harness_kwargs(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Normalize common agent argument variants before MCP execution."""
    if tool_name != "write":
        return kwargs

    normalized = dict(kwargs)
    path = normalized.get("path")
    if "file_path" not in normalized and isinstance(path, str) and path:
        normalized["file_path"] = path

    if normalized.get("append") is True and not normalized.get("mode"):
        normalized["mode"] = "append"

    return normalized


def _sandbox_code_root_from_context(ctx: ToolContext) -> str | None:
    if override := _workspace_root_override_from_context(ctx):
        return override

    return _declared_sandbox_code_root_from_context(ctx)


def _declared_sandbox_code_root_from_context(ctx: ToolContext) -> str | None:
    runtime = ctx.runtime_context if isinstance(ctx.runtime_context, Mapping) else {}
    raw = runtime.get("sandbox_code_root")
    if not isinstance(raw, str) or not raw.strip():
        code_context = runtime.get("code_context")
        if isinstance(code_context, Mapping):
            raw = code_context.get("sandbox_code_root")
    if not isinstance(raw, str):
        return None
    value = raw.strip().rstrip("/")
    if not value or value == "/workspace" or not value.startswith("/workspace/"):
        return None
    return value


def _workspace_root_override_from_context(ctx: ToolContext) -> str | None:
    runtime = ctx.runtime_context if isinstance(ctx.runtime_context, Mapping) else {}
    if not runtime.get("workspace_root_override"):
        return None

    rendered_extra = runtime.get("additional_instructions")
    if not isinstance(rendered_extra, str):
        return None
    for raw_line in rendered_extra.splitlines():
        line = raw_line.strip()
        if "worktree_path=" not in line:
            continue
        value_part = line.split("worktree_path=", 1)[1].strip()
        raw_value = value_part.split(maxsplit=1)[0].strip("'\"").rstrip("/")
        value = posixpath.normpath(raw_value)
        if value and value != "/workspace" and value.startswith("/workspace/"):
            return value
    return None


def _path_is_inside_code_root(path: str, code_root: str) -> bool:
    if not path.startswith("/"):
        return True
    return path == code_root or path.startswith(f"{code_root}/")


def _path_relative_to_code_root(path: str, code_root: str | None) -> str:
    normalized_path = posixpath.normpath(path)
    if code_root:
        normalized_root = posixpath.normpath(code_root.rstrip("/"))
        if normalized_path == normalized_root:
            return ""
        if normalized_path.startswith(f"{normalized_root}/"):
            return normalized_path[len(normalized_root) + 1 :]
    return normalized_path.lstrip("/")


def _is_verification_script_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    if normalized.startswith(_WORKSPACE_VERIFICATION_OUTPUT_PATH_PREFIXES):
        return False
    return bool(_WORKSPACE_VERIFICATION_SCRIPT_NAME_PATTERN.search(normalized))


def _workspace_verification_integrity_policy_from_context(
    ctx: ToolContext,
) -> Mapping[str, Any] | None:
    runtime = ctx.runtime_context if isinstance(ctx.runtime_context, Mapping) else {}
    policy = runtime.get("workspace_verification_integrity")
    if not isinstance(policy, Mapping):
        return None
    phase = policy.get("iteration_phase")
    if not isinstance(phase, str) or phase.strip().lower() not in (
        _WORKSPACE_VERIFICATION_INTEGRITY_PHASES
    ):
        return None
    if policy.get("allow_verification_script_changes") is True:
        return None
    if policy.get("protected_script_changes") is False:
        return None
    return policy


def _workspace_absolute_paths(command: str) -> tuple[str, ...]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()

    paths: list[str] = []
    for token in tokens:
        cleaned = token.strip("'\"")
        if cleaned == "/workspace" or cleaned.startswith("/workspace/"):
            raw_path = cleaned
        elif "/workspace/" in cleaned:
            start = cleaned.find("/workspace/")
            raw_path = cleaned[start:]
        else:
            continue
        raw_path = raw_path.rstrip(";,|&)")
        if raw_path:
            paths.append(posixpath.normpath(raw_path))
    return tuple(paths)


def _workspace_absolute_redirect_targets(command: str) -> tuple[str, ...]:
    paths: list[str] = []
    for match in _WORKSPACE_BASH_REDIRECT_TARGET_PATTERN.finditer(command):
        raw_path = match.group(1).strip("'\"")
        if not raw_path.startswith("/"):
            continue
        path = posixpath.normpath(raw_path)
        if path in _WORKSPACE_BASH_ALLOWED_REDIRECT_TARGETS:
            continue
        paths.append(path)
    return tuple(paths)


def _workspace_output_absolute_paths(output: str) -> tuple[str, ...]:
    paths: list[str] = []
    for match in _WORKSPACE_OUTPUT_ABSOLUTE_PATH_PATTERN.finditer(output):
        raw_path = match.group(0).rstrip(".,:;)")
        if raw_path:
            paths.append(posixpath.normpath(raw_path))
    return tuple(dict.fromkeys(paths))


def _workspace_output_artifact_escape_error(
    output: str,
    *,
    command: str | None,
    root_override: str | None,
    declared_code_root: str | None,
) -> str | None:
    if not root_override or not declared_code_root or not output:
        return None
    if not command or not _workspace_bash_may_emit_verification_artifacts(command):
        return None
    lower_output = output.lower()
    if not any(hint in lower_output for hint in _WORKSPACE_OUTPUT_ARTIFACT_WRITE_HINTS):
        return None
    normalized_root = posixpath.normpath(root_override.rstrip("/"))
    normalized_code_root = posixpath.normpath(declared_code_root.rstrip("/"))
    for path in _workspace_output_absolute_paths(output):
        if _path_is_inside_code_root(path, normalized_root):
            continue
        if not _path_is_inside_code_root(path, normalized_code_root):
            continue
        relative_path = _path_relative_to_code_root(path, normalized_code_root)
        if not relative_path.startswith(_WORKSPACE_VERIFICATION_OUTPUT_PATH_PREFIXES):
            continue
        return (
            f"bash.output references verification artifact path {path}, which is outside "
            f"the active attempt worktree {normalized_root}. Configure reports, coverage, "
            "screenshots, and test-results to stay inside the attempt worktree, then rerun."
        )
    return None


def _workspace_bash_may_emit_verification_artifacts(command: str) -> bool:
    tokens = _command_tokens(command)
    for token in tokens:
        basename = posixpath.basename(token).lower()
        if basename in _WORKSPACE_OUTPUT_ARTIFACT_COMMAND_TOKENS:
            return True
        if basename.endswith((".test.js", ".spec.js", ".test.ts", ".spec.ts")):
            return True
    return False


def _command_path_tokens(command: str) -> tuple[str, ...]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    paths: list[str] = []
    for token in tokens:
        cleaned = token.strip("'\"")
        cleaned = cleaned.rstrip(";,|&)")
        if cleaned:
            paths.append(posixpath.normpath(cleaned))
    for match in _WORKSPACE_BASH_REDIRECT_TARGET_PATTERN.finditer(command):
        paths.append(posixpath.normpath(match.group(1).strip("'\"")))
    return tuple(paths)


def _command_tokens(command: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(command, posix=True))
    except ValueError:
        return tuple(command.split())


def _command_tail_until_separator(tokens: tuple[str, ...], start: int) -> tuple[str, ...]:
    tail: list[str] = []
    for token in tokens[start:]:
        if token in {"&&", ";", "||", "|"}:
            break
        tail.append(token)
    return tuple(tail)


def _workspace_verification_dependency_install_error(
    tool_name: str,
    kwargs: dict[str, Any],
    policy: Mapping[str, Any] | None,
) -> str | None:
    if policy is None:
        return None
    if tool_name == "deps_install":
        package_type = kwargs.get("package_type")
        package_label = f" {package_type}" if isinstance(package_type, str) and package_type else ""
        return (
            f"deps_install cannot install{package_label} packages in a protected workspace "
            "test/review node. Use repository-declared immutable setup such as 'npm ci' from "
            "the attempt worktree, or report the missing dependency as an environment blocker."
        )
    if tool_name != "bash":
        return None
    command = kwargs.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    tokens = _command_tokens(command)
    normalized = tuple(posixpath.basename(token).lower() for token in tokens)
    error: str | None = None
    for index, token in enumerate(normalized):
        next_token = normalized[index + 1] if index + 1 < len(normalized) else ""
        tail = tuple(item.lower() for item in _command_tail_until_separator(tokens, index + 2))
        if token == "npm" and next_token in {"install", "i", "add"}:
            error = (
                "bash.command uses mutable dependency install 'npm install' in a protected "
                "workspace test/review node. Use 'npm ci' from the attempt worktree so "
                "verification does not rewrite package-lock.json."
            )
            break
        if token == "pnpm" and next_token == "install" and "--frozen-lockfile" not in tail:
            error = (
                "bash.command uses mutable dependency install 'pnpm install' in a protected "
                "workspace test/review node. Add '--frozen-lockfile' so verification does not "
                "rewrite lockfiles."
            )
            break
        if token == "yarn" and next_token in {"", "install", "add"} and not (
            "--immutable" in tail or "--frozen-lockfile" in tail
        ):
            error = (
                "bash.command uses mutable dependency install 'yarn install' in a protected "
                "workspace test/review node. Add '--immutable' or '--frozen-lockfile' so "
                "verification does not rewrite lockfiles."
            )
            break
        if token == "bun" and next_token == "install" and "--frozen-lockfile" not in tail:
            error = (
                "bash.command uses mutable dependency install 'bun install' in a protected "
                "workspace test/review node. Add '--frozen-lockfile' so verification does not "
                "rewrite lockfiles."
            )
            break
    return error


def _workspace_bash_escape_error(command: str, root_override: str | None) -> str | None:
    if not root_override:
        return None
    normalized_root = posixpath.normpath(root_override.rstrip("/"))
    for path in _workspace_absolute_paths(command):
        if _path_is_inside_code_root(path, normalized_root):
            continue
        return (
            f"bash.command references {path}, which is outside the active attempt "
            f"worktree {normalized_root}. Retry from inside {normalized_root}. Do not read, "
            "link, or reuse dependencies from the main checkout; if dependencies are missing, "
            "run an immutable setup command inside the attempt worktree or report an "
            "environment blocker."
        )
    for path in _workspace_absolute_redirect_targets(command):
        if _path_is_inside_code_root(path, normalized_root):
            continue
        return (
            f"bash.command redirects output to {path}, which is outside the active attempt "
            f"worktree {normalized_root}. Write logs, pid files, reports, and temporary "
            "artifacts inside the attempt worktree instead."
        )
    return None


def _workspace_workdir_argument_error(kwargs: dict[str, Any], root_override: str | None) -> str | None:
    if not root_override:
        return None
    normalized_root = posixpath.normpath(root_override.rstrip("/"))
    for key in _WORKDIR_ARGUMENT_KEYS:
        value = kwargs.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = posixpath.normpath(value.strip())
        if not path.startswith("/") or _path_is_inside_code_root(path, normalized_root):
            continue
        return (
            f"bash.{key} targets {path}, which is outside the active attempt "
            f"worktree {normalized_root}. Retry with {key} under {normalized_root} "
            "or omit it so the workspace wrapper can scope the command."
        )
    return None


def _workspace_verification_script_argument_error(
    tool_name: str,
    kwargs: dict[str, Any],
    code_root: str | None,
    policy: Mapping[str, Any] | None,
) -> str | None:
    if policy is None:
        return None
    if tool_name in _WORKSPACE_CODE_ROOT_WRITE_TOOLS:
        for key in _PATH_ARGUMENT_KEYS:
            value = kwargs.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            path = value.strip()
            scoped_path = (
                _path_scoped_to_code_root(path, code_root)
                if code_root and not path.startswith("/")
                else posixpath.normpath(path)
            )
            relative_path = _path_relative_to_code_root(scoped_path, code_root)
            if _is_verification_script_path(relative_path):
                return (
                    f"{tool_name}.{key} targets verification script {relative_path}. "
                    "This workspace test/review node is protected from changing test, "
                    "E2E, integration, audit, or benchmark scripts. Fix product behavior "
                    "or report the remaining failure; only an explicit "
                    "allow_verification_script_changes contract can permit this edit."
                )
    if tool_name == "bash":
        command = kwargs.get("command")
        if not isinstance(command, str) or not _WORKSPACE_BASH_SCRIPT_MUTATION_PATTERN.search(
            command
        ):
            return None
        for path in _command_path_tokens(command):
            relative_path = _path_relative_to_code_root(
                _path_scoped_to_code_root(path, code_root)
                if code_root and not path.startswith("/")
                else path,
                code_root,
            )
            if _is_verification_script_path(relative_path):
                return (
                    f"bash.command attempts to modify verification script {relative_path}. "
                    "This workspace test/review node is protected from changing test, "
                    "E2E, integration, audit, or benchmark scripts. Fix product behavior "
                    "or report the remaining failure; only an explicit "
                    "allow_verification_script_changes contract can permit this mutation."
                )
    return None


def _workspace_bash_harness_argument_error(
    command: str,
    root_override: str | None,
) -> str | None:
    if len(command) > WORKSPACE_HARNESS_MAX_BASH_COMMAND_CHARS:
        return (
            "bash.command exceeds the workspace harness hard limit "
            f"({len(command)} > {WORKSPACE_HARNESS_MAX_BASH_COMMAND_CHARS} characters). "
            "Retry with a short command; do not embed large heredocs."
        )
    if root_override and "<<" in command:
        return (
            "bash.command uses a heredoc while an attempt worktree override is active. "
            f"Retry with write/edit/append tools under {root_override}, or run a short "
            "bash command that executes an existing script in that worktree."
        )
    return _workspace_bash_escape_error(command, root_override)


def _path_scoped_to_code_root(path: str, code_root: str) -> str:
    return posixpath.normpath(f"{code_root.rstrip('/')}/{path}")


def _workspace_code_root_argument_error(
    tool_name: str,
    kwargs: dict[str, Any],
    code_root: str | None,
    *,
    enforce_all_path_tools: bool = False,
) -> str | None:
    scoped_tools = (
        _WORKSPACE_CODE_ROOT_DEFAULT_WORKDIR_TOOLS
        if enforce_all_path_tools
        else _WORKSPACE_CODE_ROOT_WRITE_TOOLS
    )
    if not code_root or tool_name not in scoped_tools:
        return None
    for key in _PATH_ARGUMENT_KEYS:
        value = kwargs.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = value.strip()
        scoped_path = (
            _path_scoped_to_code_root(path, code_root) if not path.startswith("/") else path
        )
        if _path_is_inside_code_root(scoped_path, code_root):
            continue
        return (
            f"{tool_name}.{key} targets {path}, which is outside the configured "
            f"workspace sandbox_code_root {code_root}. Retry inside {code_root} "
            "or use a relative path from that directory."
        )
    return None


def _apply_workspace_code_root_defaults(
    tool_name: str,
    kwargs: dict[str, Any],
    code_root: str | None,
) -> dict[str, Any]:
    if not code_root or tool_name not in _WORKSPACE_CODE_ROOT_DEFAULT_WORKDIR_TOOLS:
        return kwargs
    scoped = dict(kwargs)
    for key in _PATH_ARGUMENT_KEYS:
        value = scoped.get(key)
        if isinstance(value, str) and value.strip() and not value.strip().startswith("/"):
            scoped[key] = _path_scoped_to_code_root(value.strip(), code_root)
    if not scoped.get("_workspace_dir"):
        scoped["_workspace_dir"] = code_root
    return scoped


def _with_bash_timeout_guard(
    tool_name: str,
    kwargs: dict[str, Any],
    configured_timeout_s: float | None,
) -> dict[str, Any]:
    """Wrap sandbox bash commands so transport timeouts also stop the process tree."""
    if tool_name != "bash" or configured_timeout_s is None:
        return kwargs

    command = kwargs.get("command")
    if not isinstance(command, str) or not command.strip():
        return kwargs

    timeout_seconds = max(1, int(configured_timeout_s))
    kill_after_seconds = 5
    guarded = dict(kwargs)
    quoted_command = shlex.quote(command)
    guarded["command"] = (
        "if command -v timeout >/dev/null 2>&1; then "
        "set +e; "
        f"timeout --kill-after={kill_after_seconds}s {timeout_seconds}s "
        f"bash -lc {quoted_command}; "
        "status=$?; "
        'case "$status" in '
        "124|137|143) "
        "printf '\\n[workspace_harness_timeout] bash command exceeded "
        f'{timeout_seconds}s and was terminated (exit=%s)\\n\' "$status" >&2; '
        ";; "
        "esac; "
        'exit "$status"; '
        "else "
        f"bash -lc {quoted_command}; "
        "fi"
    )
    return guarded


def _workspace_harness_argument_error(
    tool_name: str,
    kwargs: dict[str, Any],
    *,
    root_override: str | None = None,
) -> str | None:
    if tool_name == "write":
        content = kwargs.get("content")
        if isinstance(content, str) and len(content) > WORKSPACE_HARNESS_MAX_SINGLE_WRITE_CHARS:
            return (
                "write.content exceeds the workspace harness hard limit "
                f"({len(content)} > {WORKSPACE_HARNESS_MAX_SINGLE_WRITE_CHARS} characters). "
                "Retry by splitting content into chunks under the limit; use write "
                "mode='append' for follow-up chunks when creating a long file."
            )
    if tool_name == "bash":
        command = kwargs.get("command")
        if isinstance(command, str):
            return _workspace_bash_harness_argument_error(command, root_override)
    if tool_name == "edit":
        old_string = kwargs.get("old_string")
        if (
            isinstance(old_string, str)
            and len(old_string) > WORKSPACE_HARNESS_MAX_EDIT_OLD_STRING_CHARS
        ):
            return (
                "edit.old_string exceeds the workspace harness hard limit "
                f"({len(old_string)} > {WORKSPACE_HARNESS_MAX_EDIT_OLD_STRING_CHARS} "
                "characters). Retry with a smaller exact snippet copied from a fresh read."
            )
        new_string = kwargs.get("new_string")
        if (
            isinstance(new_string, str)
            and len(new_string) > WORKSPACE_HARNESS_MAX_EDIT_NEW_STRING_CHARS
        ):
            return (
                "edit.new_string exceeds the workspace harness hard limit "
                f"({len(new_string)} > {WORKSPACE_HARNESS_MAX_EDIT_NEW_STRING_CHARS} "
                "characters). Retry with multiple focused edits or write the full file."
            )
    return None


def _extract_error_msg(result: dict[str, Any]) -> str:
    """Extract error message from an MCP error result.

    Args:
        result: The MCP result dict with is_error/isError flag set.

    Returns:
        The extracted error message string.
    """
    content_list = result.get("content", [])

    if content_list and len(content_list) > 0:
        first_content = content_list[0]
        if isinstance(first_content, dict):
            error_msg = first_content.get("text", "")
        else:
            error_msg = str(first_content)
    else:
        error_msg = ""

    if not error_msg:
        error_msg = f"Tool execution failed (no details provided). Raw result: {result}"

    return str(error_msg)


def _augment_tool_error_message(tool_name: str, error_msg: str) -> str:
    """Add recovery guidance for common sandbox tool failures."""
    if tool_name == "edit" and "String not found" in error_msg:
        hint = (
            "Hint: Retry with a smaller exact old_string copied from a fresh read result. "
            "Replace one unique line or a short adjacent block, and preserve whitespace "
            "exactly. If the change spans much of the file, write the complete file "
            "instead of using sed/heredoc shell commands."
        )
        if hint not in error_msg:
            return f"{error_msg}\n{hint}"
    return error_msg


def _extract_ok_output(result: dict[str, Any]) -> str:
    """Extract output string from a successful MCP result.

    Args:
        result: The MCP result dict (no error flag set).

    Returns:
        String representation of the result.
    """
    artifact = result.get("artifact")
    content_list = result.get("content", [])

    if artifact:
        filename = artifact.get("filename", "unknown")
        mime_type = artifact.get("mime_type", "unknown")
        size = artifact.get("size", 0)
        category = artifact.get("category", "file")
        return f"Exported artifact: {filename} ({mime_type}, {size} bytes, category: {category})"

    if content_list and len(content_list) > 0:
        return str(content_list[0].get("text", ""))

    return "Success"


async def _execute_with_retry(
    sandbox_id: str,
    tool_name: str,
    sandbox_port: SandboxPort,
    retry_config: RetryConfig,
    kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Execute a sandbox MCP tool call with error classification and retry.

    Args:
        sandbox_id: The sandbox instance ID.
        tool_name: Original MCP tool name.
        sandbox_port: SandboxPort for routing calls.
        retry_config: Retry configuration.
        kwargs: Tool arguments.

    Returns:
        Tuple of (output_string, raw_result_dict_or_None).
        The raw dict is returned when the result contains an artifact.
    Raises:
        RuntimeError: When execution fails after all retries.
    """
    import time as _time

    last_error: MCPToolError | None = None
    tool_timeout = kwargs.get("timeout")
    configured_timeout_s: float | None = (
        float(tool_timeout) if tool_timeout and isinstance(tool_timeout, (int, float)) else None
    )
    execution_kwargs = _with_bash_timeout_guard(tool_name, kwargs, configured_timeout_s)

    for attempt in range(retry_config.max_retries + 1):
        start_time = _time.time()
        try:
            call_kwargs: dict[str, Any] = {}
            if configured_timeout_s is not None:
                call_kwargs["timeout"] = configured_timeout_s + 5.0

            result = await sandbox_port.call_tool(
                sandbox_id,
                tool_name,
                execution_kwargs,
                **call_kwargs,
            )
            elapsed_ms = int((_time.time() - start_time) * 1000)

            if result.get("is_error") or result.get("isError"):
                error_msg = _augment_tool_error_message(tool_name, _extract_error_msg(result))
                mcp_err = MCPToolErrorClassifier.classify(
                    error=Exception(error_msg),
                    tool_name=tool_name,
                    sandbox_id=sandbox_id,
                    context={
                        "kwargs": kwargs,
                        "execution_kwargs": execution_kwargs,
                        "attempt": attempt,
                        "execution_duration_ms": elapsed_ms,
                        "configured_timeout_s": configured_timeout_s,
                    },
                )
                mcp_err.retry_count = attempt
                last_error = mcp_err

                if mcp_err.is_retryable and attempt < retry_config.max_retries:
                    await asyncio.sleep(retry_config.get_delay(attempt))
                    continue
                break

            raw = result if (result.get("artifact") or result.get("results")) else None
            return _extract_ok_output(result), raw

        except Exception as exc:
            elapsed_ms = int((_time.time() - start_time) * 1000)
            mcp_err = MCPToolErrorClassifier.classify(
                error=exc,
                tool_name=tool_name,
                sandbox_id=sandbox_id,
                context={
                    "kwargs": kwargs,
                    "execution_kwargs": execution_kwargs,
                    "attempt": attempt,
                    "execution_duration_ms": elapsed_ms,
                    "configured_timeout_s": configured_timeout_s,
                },
            )
            mcp_err.retry_count = attempt

            if mcp_err.is_retryable and attempt < retry_config.max_retries:
                await asyncio.sleep(retry_config.get_delay(attempt))
                last_error = mcp_err
                continue

            raise RuntimeError(f"Tool execution failed: {mcp_err.get_user_message()}") from exc

    if last_error:
        raise RuntimeError(
            f"Tool execution failed after {last_error.retry_count + 1} "
            f"attempts: {last_error.get_user_message()}"
        )
    raise RuntimeError("Tool execution failed: Unknown error")


def create_sandbox_mcp_tool(
    sandbox_id: str,
    tool_name: str,
    tool_schema: dict[str, Any],
    sandbox_port: SandboxPort,
    retry_config: RetryConfig | None = None,
) -> ToolInfo:
    """Create a ToolInfo for a sandbox MCP tool.

    This is the ``@tool_define`` migration equivalent of
    :class:`SandboxMCPToolWrapper`. Each sandbox tool has a unique
    name/description/parameters so we build :class:`ToolInfo` directly
    rather than using the ``@tool_define`` decorator.

    Args:
        sandbox_id: The sandbox instance ID.
        tool_name: Original MCP tool name (e.g. ``bash``, ``file_read``).
        tool_schema: MCP tool schema dict (name, description, input_schema).
        sandbox_port: SandboxPort instance for routing calls.
        retry_config: Optional retry configuration for transient errors.

    Returns:
        A :class:`ToolInfo` instance representing this sandbox tool.
    """
    from src.infrastructure.agent.tools.define import ToolInfo
    from src.infrastructure.agent.tools.result import ToolResult

    cfg = retry_config or RetryConfig()
    description = tool_schema.get("description", f"{tool_name} tool")
    parameters = _apply_workspace_harness_limits(
        tool_name,
        _convert_mcp_schema(tool_schema.get("input_schema", {})),
    )
    permission = classify_sandbox_tool_permission(tool_name)

    async def execute(ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the sandbox MCP tool with retry logic."""
        try:
            normalized_kwargs = _normalize_workspace_harness_kwargs(tool_name, kwargs)
            root_override = _workspace_root_override_from_context(ctx)
            declared_code_root = _declared_sandbox_code_root_from_context(ctx)
            code_root = _sandbox_code_root_from_context(ctx)
            if argument_error := _workspace_code_root_argument_error(
                tool_name,
                normalized_kwargs,
                code_root,
                enforce_all_path_tools=root_override is not None,
            ):
                return ToolResult(output=argument_error, is_error=True)
            normalized_kwargs = _apply_workspace_code_root_defaults(
                tool_name, normalized_kwargs, code_root
            )
            verification_policy = _workspace_verification_integrity_policy_from_context(ctx)
            if argument_error := _workspace_verification_script_argument_error(
                tool_name,
                normalized_kwargs,
                code_root,
                verification_policy,
            ):
                return ToolResult(output=argument_error, is_error=True)
            if argument_error := _workspace_verification_dependency_install_error(
                tool_name,
                normalized_kwargs,
                verification_policy,
            ):
                return ToolResult(output=argument_error, is_error=True)
            if argument_error := _workspace_harness_argument_error(
                tool_name,
                normalized_kwargs,
                root_override=root_override,
            ):
                return ToolResult(output=argument_error, is_error=True)
            if tool_name == "bash":
                if argument_error := _workspace_workdir_argument_error(
                    normalized_kwargs,
                    root_override,
                ):
                    raise RuntimeError(argument_error)
            output, raw_result = await _execute_with_retry(
                sandbox_id=sandbox_id,
                tool_name=tool_name,
                sandbox_port=sandbox_port,
                retry_config=cfg,
                kwargs=normalized_kwargs,
            )
            if tool_name == "bash":
                if artifact_error := _workspace_output_artifact_escape_error(
                    output,
                    command=(
                        normalized_kwargs.get("command")
                        if isinstance(normalized_kwargs.get("command"), str)
                        else None
                    ),
                    root_override=root_override,
                    declared_code_root=declared_code_root,
                ):
                    raise RuntimeError(artifact_error)
            metadata = raw_result if raw_result else {}
            return ToolResult(output=output, metadata=metadata)
        except RuntimeError as exc:
            return ToolResult(output=str(exc), is_error=True)

    info = ToolInfo(
        name=tool_name,
        description=description,
        parameters=parameters,
        execute=execute,
        permission=permission,
        category="mcp",
        tags=frozenset({"mcp", "sandbox"}),
    )
    # Expose sandbox identity for downstream helpers (e.g. register_mcp_server wiring).
    info.sandbox_id = sandbox_id
    info._sandbox_id = sandbox_id
    return info
