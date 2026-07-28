"""Structured, workspace-scoped file browser tools for trusted platform APIs."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from src.server.websocket_server import MCPTool

_MAX_LIST_LIMIT = 500
_MAX_READ_BYTES = 1_048_576
_MAX_DOWNLOAD_BYTES = 25 * 1_048_576
_MAX_PATH_LENGTH = 4096
_TEXT_APPLICATION_MIME_TYPES = {
    "application/javascript",
    "application/json",
    "application/ld+json",
    "application/sql",
    "application/toml",
    "application/x-httpd-php",
    "application/x-javascript",
    "application/x-sh",
    "application/x-yaml",
    "application/xhtml+xml",
    "application/xml",
    "application/yaml",
}
_MIME_TYPE_OVERRIDES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".toml": "application/toml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


@dataclass(frozen=True)
class WorkspaceFileContractError(Exception):
    """Stable structural error returned through the MCP result envelope."""

    reason_code: str
    message: str


def _tool_error(error: WorkspaceFileContractError) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": error.message}],
        "isError": True,
        "reason_code": error.reason_code,
    }


def _tool_success(summary: str, key: str, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": summary}],
        "isError": False,
        key: value,
    }


def _validated_limit(value: int, maximum: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise WorkspaceFileContractError(
            "sandbox_file_limit_invalid",
            f"{field} is outside the supported range",
        )
    return value


def _resolve_workspace_path(path: str, workspace_dir: str) -> tuple[Path, Path]:
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or len(path) > _MAX_PATH_LENGTH
        or "\x00" in path
        or "\\" in path
    ):
        raise WorkspaceFileContractError(
            "sandbox_file_path_invalid",
            "workspace file path is invalid",
        )
    pure_path = PurePosixPath(path)
    if any(part in {".", ".."} for part in pure_path.parts):
        raise WorkspaceFileContractError(
            "sandbox_file_path_invalid",
            "workspace file path is invalid",
        )

    root = Path(workspace_dir).resolve(strict=True)
    candidate = root
    for part in pure_path.parts[1:]:
        candidate = candidate / part
        if candidate.is_symlink():
            raise WorkspaceFileContractError(
                "sandbox_file_symlink_rejected",
                "symbolic links are not available through the file browser",
            )
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise WorkspaceFileContractError(
            "sandbox_file_path_invalid",
            "workspace file path is invalid",
        ) from exc
    return root, candidate


def _contract_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return "/" if relative == "." else f"/{relative}"


def _mime_type(path: Path) -> str:
    override = _MIME_TYPE_OVERRIDES.get(path.suffix.lower())
    return (override or mimetypes.guess_type(path.name)[0] or "application/octet-stream").lower()


def _is_text_mime(mime_type: str) -> bool:
    return mime_type.startswith("text/") or mime_type in _TEXT_APPLICATION_MIME_TYPES


def _revision(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _listing_snapshot(root: Path, directory: Path) -> tuple[list[dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    for child in directory.iterdir():
        if child.is_symlink():
            continue
        stat = child.stat()
        if child.is_dir():
            kind = "directory"
            size_bytes = None
            mime_type = None
        elif child.is_file():
            kind = "file"
            size_bytes = stat.st_size
            mime_type = _mime_type(child)
        else:
            continue
        entries.append(
            {
                "path": _contract_path(root, child),
                "name": child.name,
                "kind": kind,
                "size_bytes": size_bytes,
                "mime_type": mime_type,
                "_mtime_ns": stat.st_mtime_ns,
            }
        )
    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
    revision = _revision(entries)
    return [
        {key: value for key, value in item.items() if key != "_mtime_ns"} for item in entries
    ], revision


def _parse_cursor(cursor: str | None, revision: str) -> int:
    if cursor is None:
        return 0
    try:
        cursor_revision, raw_offset = cursor.split(".", 1)
        offset = int(raw_offset)
    except (AttributeError, TypeError, ValueError) as exc:
        raise WorkspaceFileContractError(
            "sandbox_file_cursor_invalid",
            "workspace file cursor is invalid",
        ) from exc
    if cursor_revision != revision:
        raise WorkspaceFileContractError(
            "sandbox_file_cursor_stale",
            "workspace directory changed before the next page was read",
        )
    if offset < 0:
        raise WorkspaceFileContractError(
            "sandbox_file_cursor_invalid",
            "workspace file cursor is invalid",
        )
    return offset


def _file_revision(path: Path) -> str:
    stat = path.stat()
    return _revision(
        {
            "name": path.name,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    )


async def list_workspace_files(
    path: str = "/",
    limit: int = 200,
    cursor: str | None = None,
    _workspace_dir: str = "/workspace",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Return a deterministic, paginated directory listing."""
    try:
        bounded_limit = _validated_limit(limit, _MAX_LIST_LIMIT, "limit")
        root, directory = _resolve_workspace_path(path, _workspace_dir)
        if not directory.exists():
            raise WorkspaceFileContractError(
                "sandbox_file_not_found",
                "workspace directory was not found",
            )
        if not directory.is_dir():
            raise WorkspaceFileContractError(
                "sandbox_file_not_directory",
                "workspace file path is not a directory",
            )
        entries, revision = await asyncio.to_thread(_listing_snapshot, root, directory)
        offset = _parse_cursor(cursor, revision)
        page = entries[offset : offset + bounded_limit]
        next_offset = offset + len(page)
        next_cursor = f"{revision}.{next_offset}" if next_offset < len(entries) else None
        listing = {
            "contract_version": 1,
            "authority": "sandbox",
            "isolation": "isolated",
            "root": "/",
            "path": _contract_path(root, directory),
            "entries": page,
            "cursor": next_cursor,
            "revision": revision,
        }
        return _tool_success("Workspace directory listed", "listing", listing)
    except WorkspaceFileContractError as error:
        return _tool_error(error)
    except OSError:
        return _tool_error(
            WorkspaceFileContractError(
                "sandbox_file_io_error",
                "workspace directory could not be read",
            )
        )


async def read_workspace_file(
    path: str,
    max_bytes: int = _MAX_READ_BYTES,
    _workspace_dir: str = "/workspace",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Read a bounded UTF-8 text file without following symbolic links."""
    try:
        bounded_limit = _validated_limit(max_bytes, _MAX_READ_BYTES, "max_bytes")
        root, file_path = _resolve_workspace_path(path, _workspace_dir)
        if not file_path.exists():
            raise WorkspaceFileContractError(
                "sandbox_file_not_found",
                "workspace file was not found",
            )
        if not file_path.is_file():
            raise WorkspaceFileContractError(
                "sandbox_file_not_file",
                "workspace file path is not a regular file",
            )
        mime_type = _mime_type(file_path)
        if not _is_text_mime(mime_type):
            raise WorkspaceFileContractError(
                "sandbox_file_mime_not_text",
                "workspace file is not a supported text type",
            )
        raw = await asyncio.to_thread(file_path.read_bytes)
        truncated = len(raw) > bounded_limit
        bounded = raw[:bounded_limit]
        while truncated:
            try:
                content = bounded.decode("utf-8")
                break
            except UnicodeDecodeError as exc:
                if exc.start < max(0, len(bounded) - 4):
                    raise WorkspaceFileContractError(
                        "sandbox_file_encoding_invalid",
                        "workspace file is not valid UTF-8",
                    ) from exc
                bounded = bounded[: exc.start]
        else:
            try:
                content = bounded.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkspaceFileContractError(
                    "sandbox_file_encoding_invalid",
                    "workspace file is not valid UTF-8",
                ) from exc
        file_contract = {
            "contract_version": 1,
            "authority": "sandbox",
            "isolation": "isolated",
            "path": _contract_path(root, file_path),
            "encoding": "utf-8",
            "content": content,
            "mime_type": mime_type,
            "size_bytes": len(bounded),
            "revision": _file_revision(file_path),
            "truncated": truncated,
        }
        return _tool_success("Workspace text file read", "file", file_contract)
    except WorkspaceFileContractError as error:
        return _tool_error(error)
    except OSError:
        return _tool_error(
            WorkspaceFileContractError(
                "sandbox_file_io_error",
                "workspace file could not be read",
            )
        )


async def download_workspace_file(
    path: str,
    max_bytes: int = _MAX_DOWNLOAD_BYTES,
    _workspace_dir: str = "/workspace",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Return bounded file bytes for an authenticated platform download route."""
    try:
        bounded_limit = _validated_limit(max_bytes, _MAX_DOWNLOAD_BYTES, "max_bytes")
        root, file_path = _resolve_workspace_path(path, _workspace_dir)
        if not file_path.exists():
            raise WorkspaceFileContractError(
                "sandbox_file_not_found",
                "workspace file was not found",
            )
        if not file_path.is_file():
            raise WorkspaceFileContractError(
                "sandbox_file_not_file",
                "workspace file path is not a regular file",
            )
        stat = file_path.stat()
        if stat.st_size > bounded_limit:
            raise WorkspaceFileContractError(
                "sandbox_file_too_large",
                "workspace file exceeds the download limit",
            )
        raw = await asyncio.to_thread(file_path.read_bytes)
        if len(raw) > bounded_limit:
            raise WorkspaceFileContractError(
                "sandbox_file_too_large",
                "workspace file exceeds the download limit",
            )
        download = {
            "contract_version": 1,
            "authority": "sandbox",
            "isolation": "isolated",
            "path": _contract_path(root, file_path),
            "filename": file_path.name,
            "mime_type": _mime_type(file_path),
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "base64": base64.b64encode(raw).decode("ascii"),
        }
        return _tool_success("Workspace file prepared for download", "download", download)
    except WorkspaceFileContractError as error:
        return _tool_error(error)
    except OSError:
        return _tool_error(
            WorkspaceFileContractError(
                "sandbox_file_io_error",
                "workspace file could not be read",
            )
        )


def create_list_workspace_files_tool() -> MCPTool:
    return MCPTool(
        name="platform_list_workspace_files",
        description="List workspace files for the authenticated platform file-browser API.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "/"},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIST_LIMIT},
                "cursor": {"type": ["string", "null"]},
            },
        },
        handler=list_workspace_files,
    )


def create_read_workspace_file_tool() -> MCPTool:
    return MCPTool(
        name="platform_read_workspace_file",
        description="Read a bounded UTF-8 workspace file for the platform file-browser API.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_READ_BYTES,
                },
            },
            "required": ["path"],
        },
        handler=read_workspace_file,
    )


def create_download_workspace_file_tool() -> MCPTool:
    return MCPTool(
        name="platform_download_workspace_file",
        description="Return bounded workspace bytes for an authenticated platform download.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_DOWNLOAD_BYTES,
                },
            },
            "required": ["path"],
        },
        handler=download_workspace_file,
    )
