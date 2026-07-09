"""Helpers for tool-result metadata used by agent timeline UIs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

_READ_TOOLS = frozenset({"read", "file_read", "batch_read"})
_WRITE_TOOLS = frozenset({"write", "file_write", "create_file"})
_EDIT_TOOLS = frozenset({"edit", "file_edit", "edit_by_ast", "batch_edit", "patch", "apply_patch"})
_LIST_TOOLS = frozenset({"glob", "list", "ls", "list_files"})
_SEARCH_TOOLS = frozenset({"grep"})


def build_sandbox_tool_metadata(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    raw_result: Mapping[str, Any],
    output: str,
) -> dict[str, Any]:
    """Build compact metadata for a sandbox MCP tool result."""
    source_metadata = raw_result.get("metadata")
    metadata = dict(source_metadata) if isinstance(source_metadata, Mapping) else {}

    if artifact := raw_result.get("artifact"):
        metadata["artifact"] = artifact
    if results := raw_result.get("results"):
        metadata["results"] = results

    if file_metadata := build_file_metadata(
        tool_name=tool_name,
        arguments=arguments,
        result_metadata=metadata,
        output=output,
    ):
        metadata["fileMetadata"] = file_metadata

    if tool_name == "bash":
        command_metadata = _build_command_metadata(arguments, metadata, output)
        if command_metadata:
            metadata["commandMetadata"] = command_metadata

    return metadata


def build_file_metadata(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    result_metadata: Mapping[str, Any],
    output: str,
) -> dict[str, Any] | None:
    """Normalize structural file facts from known file-system tools."""
    operation = _operation_for_tool(tool_name)
    if operation is None:
        return None

    workspace_root = _string_value(result_metadata, "workspace_root") or _string_value(
        arguments, "_workspace_dir"
    )
    paths = _paths_for_tool(
        tool_name=tool_name,
        arguments=arguments,
        result_metadata=result_metadata,
        output=output,
    )

    file_metadata: dict[str, Any] = {
        "operation": operation,
        "paths": paths,
    }
    if workspace_root:
        file_metadata["workspaceRoot"] = workspace_root

    if operation == "search":
        matches = _grep_matches(output)
        if matches:
            file_metadata["matches"] = matches
        match_count = _int_value(result_metadata, "matches_found")
        if match_count is not None:
            file_metadata["matchCount"] = match_count

    total_matches = _int_value(result_metadata, "total_matches")
    if total_matches is not None:
        file_metadata["matchCount"] = total_matches

    if _bool_value(result_metadata, "search_truncated"):
        file_metadata["truncated"] = True
    elif tool_name in _READ_TOOLS:
        total_lines = _int_value(result_metadata, "total_lines")
        lines_returned = _int_value(result_metadata, "lines_returned")
        if total_lines is not None and lines_returned is not None:
            file_metadata["truncated"] = lines_returned < total_lines

    return file_metadata


def _operation_for_tool(tool_name: str) -> str | None:
    if tool_name in _READ_TOOLS:
        return "read"
    if tool_name in _WRITE_TOOLS:
        return "create" if tool_name == "create_file" else "write"
    if tool_name in _EDIT_TOOLS:
        return "edit"
    if tool_name in _LIST_TOOLS:
        return "list"
    if tool_name in _SEARCH_TOOLS:
        return "search"
    return None


def _paths_for_tool(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    result_metadata: Mapping[str, Any],
    output: str,
) -> list[dict[str, Any]]:
    if tool_name in _LIST_TOOLS:
        paths = [_path_entry(path) for path in _output_paths(output)]
        if paths:
            return paths
    if tool_name in _SEARCH_TOOLS:
        paths_by_name = {
            match["path"]: _path_entry(match["path"]) for match in _grep_matches(output)
        }
        if paths_by_name:
            return list(paths_by_name.values())

    resolved_path = _string_value(result_metadata, "resolved_path")
    relative_path = _string_value(result_metadata, "workspace_relative_path")
    requested_path = (
        _string_value(arguments, "file_path")
        or _string_value(arguments, "path")
        or _string_value(result_metadata, "requested_path")
    )
    path = resolved_path or requested_path or relative_path
    if not path:
        return []

    entry = _path_entry(path, relative_path=relative_path)
    bytes_written = _int_value(result_metadata, "bytes_written")
    if bytes_written is not None:
        entry["bytesWritten"] = bytes_written
        entry["changed"] = True
    total_lines = _int_value(result_metadata, "total_lines")
    if total_lines is not None:
        entry["lineCount"] = total_lines
    lines_returned = _int_value(result_metadata, "lines_returned")
    if lines_returned is not None:
        offset = _int_value(result_metadata, "offset") or 0
        entry["lineStart"] = offset + 1
        entry["lineEnd"] = offset + lines_returned
    replacements = _int_value(result_metadata, "replacements")
    if replacements is not None:
        entry["changed"] = replacements > 0
    return [entry]


def _path_entry(path: str, *, relative_path: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": path}
    if relative_path:
        entry["relativePath"] = relative_path
    elif not path.startswith("/"):
        entry["relativePath"] = path
    suffix = PurePosixPath(path).suffix.lstrip(".")
    if suffix:
        entry["language"] = suffix
    return entry


def _grep_matches(output: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for line in output.splitlines():
        path, line_number, preview = _split_grep_line(line)
        if path is None:
            continue
        match: dict[str, Any] = {"path": path}
        if line_number is not None:
            match["lineNumber"] = line_number
        if preview:
            match["preview"] = preview
        matches.append(match)
    return matches


def _split_grep_line(line: str) -> tuple[str | None, int | None, str]:
    first, separator, tail = line.partition(":")
    if not separator:
        return None, None, ""
    number_text, separator, preview = tail.partition(":")
    if not separator:
        return None, None, ""
    try:
        line_number = int(number_text)
    except ValueError:
        return None, None, ""
    return first, line_number, preview.strip()


def _output_paths(output: str) -> list[str]:
    paths: list[str] = []
    for line in output.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("..."):
            continue
        paths.append(candidate)
    return paths


def _build_command_metadata(
    arguments: Mapping[str, Any],
    metadata: Mapping[str, Any],
    output: str,
) -> dict[str, Any]:
    command_metadata: dict[str, Any] = {}
    if command := _string_value(arguments, "command"):
        command_metadata["command"] = command
    if cwd := _string_value(arguments, "working_dir") or _string_value(arguments, "cwd"):
        command_metadata["cwd"] = cwd
    elif working_dir := _string_value(metadata, "working_dir"):
        command_metadata["cwd"] = working_dir
    exit_code = _int_value(metadata, "exit_code")
    if exit_code is not None:
        command_metadata["exitCode"] = exit_code
        command_metadata["status"] = "failed" if exit_code != 0 else "success"
    command_metadata["outputBytes"] = len(output.encode("utf-8"))
    return command_metadata


def _string_value(source: Mapping[str, Any], key: str) -> str | None:
    value = source.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _int_value(source: Mapping[str, Any], key: str) -> int | None:
    value = source.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _bool_value(source: Mapping[str, Any], key: str) -> bool:
    value = source.get(key)
    return value if isinstance(value, bool) else False
