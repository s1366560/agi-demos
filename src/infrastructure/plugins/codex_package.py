"""Inspect immutable Codex-style plugin directories without executing plugin code.

The MemStack hooks/apps dialect is explicit: unsupported components produce compatibility
reasons, never a silently partial installation. Parsing is structural, not semantic routing.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_FILES = 4096
HOOK_EVENTS = frozenset({"session_start", "before_request", "after_tool_execute"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\Z")
_VERSION = re.compile(
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z"
)


class CodexPackageError(ValueError):
    """A package is malformed or escapes its installation root."""


def package_path(root: Path, relative: str) -> Path:
    """Resolve a declared package path, rejecting links and traversal."""
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise CodexPackageError("Package paths must stay inside the plugin directory")
    current = root
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise CodexPackageError("Package symlinks are not supported")
    if not current.resolve().is_relative_to(root.resolve()):
        raise CodexPackageError("Package path escaped its root")
    return current


def package_digest(root: Path) -> str:
    """Hash every file, including resource names, with bounded aggregate size."""
    if root.is_symlink() or not root.is_dir():
        raise CodexPackageError("Package root must be a real directory")
    digest = hashlib.sha256()
    total = count = 0
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise CodexPackageError("Package symlinks are not supported")
        if path.is_dir():
            continue
        if not path.is_file():
            raise CodexPackageError("Package contains a non-regular file")
        count += 1
        total += path.stat().st_size
        if count > MAX_FILES or total > MAX_PACKAGE_BYTES:
            raise CodexPackageError("Package exceeds the file or byte limit")
        name = path.relative_to(root).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise CodexPackageError(f"{label} must be an object")
    return value


def _json(path: Path) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), path.name)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexPackageError(f"Cannot read package JSON: {path.name}") from exc


def _text(value: object, label: str, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise CodexPackageError(f"{label} must be text")
    return value


def _skills(root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    paths = {"skills"}
    if "skills" in manifest:
        paths.add(_text(manifest["skills"], "skills"))
    result: dict[str, dict[str, str]] = {}
    for relative in sorted(paths):
        directory = package_path(root, relative)
        if not directory.exists() and relative == "skills":
            continue
        if not directory.exists():
            raise CodexPackageError("Declared skills path does not exist")
        files = [directory] if directory.is_file() else sorted(directory.rglob("SKILL.md"))
        for file in files:
            content = file.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            if len(parts) != 3 or parts[0].strip():
                raise CodexPackageError("Skills require YAML front matter")
            try:
                metadata = _object(yaml.safe_load(parts[1]), "Skill metadata")
            except yaml.YAMLError as exc:
                raise CodexPackageError("Invalid skill metadata") from exc
            name = _text(metadata.get("name"), "skill name", file.parent.name)
            if not _IDENTIFIER.fullmatch(name):
                raise CodexPackageError("Invalid skill name")
            item = {
                "name": name,
                "description": _text(metadata.get("description"), "skill description"),
                "content": content,
                "path": file.relative_to(root).as_posix(),
            }
            if name in result and result[name] != item:
                raise CodexPackageError("Duplicate skill name")
            result[name] = item
    return list(result.values())


def _servers(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    servers: dict[str, Any] = {}
    paths = {".mcp.json"} if (root / ".mcp.json").exists() else set()
    value = manifest.get("mcpServers")
    if isinstance(value, str):
        paths.add(value)
    elif value is not None:
        servers.update(_object(value, "mcpServers"))
    for path in sorted(paths):
        entries = _object(_json(package_path(root, path)).get("mcpServers"), "mcpServers")
        for name, config in entries.items():
            if name in servers and config != servers[name]:
                raise CodexPackageError("Conflicting MCP server declaration")
            servers[name] = config
    for name, config in servers.items():
        if not _IDENTIFIER.fullmatch(name):
            raise CodexPackageError("Invalid MCP server name")
        _object(config, "MCP server")
        if not (isinstance(config.get("command"), str) or isinstance(config.get("url"), str)):
            raise CodexPackageError("MCP server requires command or URL")
        args = config.get("args", [])
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise CodexPackageError("MCP arguments must be a list of strings")
        for field in ("env", "headers"):
            values = _object(config.get(field, {}), f"MCP {field}")
            if any(not isinstance(value, str) for value in values.values()):
                raise CodexPackageError(f"MCP {field} values must be strings")
    return servers


def _hooks(root: Path, manifest: dict[str, Any], reasons: list[str]) -> list[dict[str, Any]]:
    paths = {"hooks/hooks.json"} if (root / "hooks/hooks.json").exists() else set()
    if "hooks" in manifest:
        paths.add(_text(manifest["hooks"], "hooks"))
    hooks: list[dict[str, Any]] = []
    for path in sorted(paths):
        payload = _json(package_path(root, path)).get("hooks", [])
        if not isinstance(payload, list):
            reasons.append("hooks_require_memstack_event_list")
            continue
        for item in payload:
            hook = _object(item, "hook")
            event = _text(hook.get("event"), "hook event")
            command = _text(hook.get("command"), "hook command")
            if event not in HOOK_EVENTS:
                reasons.append(f"unsupported_hook_event:{event}")
            if not command.strip():
                raise CodexPackageError("Hook command is required")
            timeout = hook.get("timeout_seconds", 30)
            if type(timeout) is not int or not 1 <= timeout <= 30:
                raise CodexPackageError("Hook timeout must be between 1 and 30 seconds")
            hooks.append({"event": event, "command": command, "timeout_seconds": timeout})
    return hooks


def inspect_codex_package(
    root: Path, *, source_id: str = "", targets: tuple[str, ...] = ("local", "cloud")
) -> dict[str, Any]:
    """Return validated metadata, runtime contributions and an immutable content digest."""
    digest = package_digest(root)
    manifest = _json(package_path(root, ".codex-plugin/plugin.json"))
    name = _text(manifest.get("name"), "name")
    version = _text(manifest.get("version"), "version")
    if not _IDENTIFIER.fullmatch(name) or not _VERSION.fullmatch(version):
        raise CodexPackageError("Package requires a valid name and semantic version")
    interface = _object(manifest.get("interface", {}), "interface")
    author = _object(manifest.get("author", {}), "author")
    reasons: list[str] = []
    skills = _skills(root, manifest)
    servers = _servers(root, manifest)
    for server_name, server in servers.items():
        auth = server.get("oauth", server.get("auth"))
        declares_oauth = isinstance(auth, dict) and (
            "oauth" in server or auth.get("type") in ("oauth", "oauth2")
        )
        transport = server.get("type", "stdio" if "command" in server else "http")
        if declares_oauth and (transport != "http" or "command" in server):
            reasons.append(f"oauth_requires_streamable_http:{server_name}")
    hooks = _hooks(root, manifest, reasons)
    app_path = manifest.get("apps", ".app.json" if (root / ".app.json").exists() else None)
    apps = (
        _object(_json(package_path(root, _text(app_path, "apps"))).get("apps", {}), "apps")
        if app_path
        else {}
    )
    for app_name, app_value in apps.items():
        app = _object(app_value, "app")
        server = app.get("mcp_server")
        if not isinstance(server, str) or server not in servers:
            reasons.append(f"app_requires_accessible_mcp_server:{app_name}")
    capabilities = [
        key
        for key, value in (("skills", skills), ("mcp", servers), ("hooks", hooks), ("apps", apps))
        if value
    ]
    permissions = (["skills:read"] if skills else []) + (
        ["process:execute"] if hooks or any("command" in s for s in servers.values()) else []
    )
    if any("url" in server for server in servers.values()):
        permissions.append("network:connect")
    if apps:
        permissions.append("apps:connect")
    declared = manifest.get("permissions", [])
    if not isinstance(declared, list) or any(not isinstance(p, str) for p in declared):
        raise CodexPackageError("permissions must be a list of strings")
    permissions = sorted(set(permissions + declared))
    declared_targets = manifest.get("targets", list(targets))
    if (
        not isinstance(declared_targets, list)
        or not declared_targets
        or any(
            not isinstance(target, str) or target not in {"local", "cloud"}
            for target in declared_targets
        )
    ):
        raise CodexPackageError("targets must declare local and/or cloud")
    descriptor = {
        "id": name,
        "name": _text(interface.get("displayName"), "displayName", name),
        "description": _text(manifest.get("description"), "description"),
        "version": version,
        "publisher": _text(author.get("name"), "author name"),
        "source_id": source_id,
        "format": "codex",
        "category": _text(interface.get("category"), "category", "Other"),
        "capabilities": capabilities,
        "targets": list(dict.fromkeys(declared_targets)),
        "permissions": permissions,
        "compatible": not reasons,
        "reasons": reasons,
        "readme": (root / "README.md").read_text(encoding="utf-8")
        if (root / "README.md").is_file()
        else "",
        "changelog": (root / "CHANGELOG.md").read_text(encoding="utf-8")
        if (root / "CHANGELOG.md").is_file()
        else "",
    }
    return {
        "descriptor": descriptor,
        "resources": {"skills": skills, "mcp_servers": servers, "hooks": hooks, "apps": apps},
        "digest": digest,
    }
