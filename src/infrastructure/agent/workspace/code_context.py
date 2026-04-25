"""Sandbox code-root context for software workspace workers."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from src.application.services.workspace_autonomy_profiles import resolve_sandbox_code_root

logger = logging.getLogger(__name__)

_MAX_AGENTS_FILE_CHARS = 8_000
_MAX_AGENTS_TOTAL_CHARS = 20_000
_WORKSPACE_ROOT = PurePosixPath("/workspace")


@dataclass(frozen=True)
class AgentsInstructionFile:
    """AGENTS.md content loaded from the resolved code-root chain."""

    sandbox_path: str
    content: str
    truncated: bool = False


@dataclass(frozen=True)
class WorkspaceCodeContext:
    """Runtime context that pins software work to one sandbox code root."""

    sandbox_code_root: str | None
    host_code_root: Path | None = None
    agents_files: tuple[AgentsInstructionFile, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def agents_digest(self) -> str | None:
        if not self.agents_files:
            return None
        hasher = hashlib.sha256()
        for file in self.agents_files:
            hasher.update(file.sandbox_path.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(file.content.encode("utf-8"))
            hasher.update(b"\0")
        return hasher.hexdigest()

    @property
    def loaded_agents_paths(self) -> tuple[str, ...]:
        return tuple(file.sandbox_path for file in self.agents_files)

    @property
    def agents_excerpt(self) -> str | None:
        if not self.agents_files:
            return None
        excerpt = "\n\n".join(f"{file.sandbox_path}\n{file.content}" for file in self.agents_files)
        return excerpt[:2000]


def _fallback_host_workspace_root(project_id: str) -> Path:
    return Path(f"/tmp/memstack_{project_id}")


def resolve_host_workspace_root(project_id: str) -> Path:
    """Resolve the host directory mounted into the sandbox as `/workspace`."""

    candidate = _fallback_host_workspace_root(project_id)
    if candidate.exists():
        return candidate

    from src.infrastructure.agent.state.agent_worker_state import resolve_project_base_path

    return resolve_project_base_path(project_id)


def host_path_for_sandbox_code_root(
    *,
    project_id: str,
    sandbox_code_root: str,
) -> Path:
    """Map `/workspace/...` to the host-side bind mount path."""

    host_workspace_root = resolve_host_workspace_root(project_id)
    sandbox_path = PurePosixPath(sandbox_code_root)
    relative = sandbox_path.relative_to(_WORKSPACE_ROOT)
    return host_workspace_root.joinpath(*relative.parts)


def _sandbox_path_for_host_path(
    *,
    host_workspace_root: Path,
    host_path: Path,
) -> str:
    relative = host_path.relative_to(host_workspace_root)
    if not relative.parts:
        return "/workspace"
    return "/" + str(PurePosixPath("workspace", *relative.parts))


def _truncate_agents_content(content: str) -> tuple[str, bool]:
    trimmed = content.rstrip()
    if len(trimmed) <= _MAX_AGENTS_FILE_CHARS:
        return trimmed, False
    keep_head = int(_MAX_AGENTS_FILE_CHARS * 0.7)
    keep_tail = _MAX_AGENTS_FILE_CHARS - keep_head
    return (
        trimmed[:keep_head]
        + "\n[...truncated AGENTS.md for worker brief...]\n"
        + trimmed[-keep_tail:],
        True,
    )


def _candidate_agents_paths(
    *,
    host_workspace_root: Path,
    host_code_root: Path,
    include_workspace_root_agents: bool,
) -> list[Path]:
    candidates: list[Path] = []
    current = host_code_root
    while True:
        if current == host_workspace_root and not include_workspace_root_agents:
            break
        agents_path = current / "AGENTS.md"
        if agents_path.is_file():
            candidates.append(agents_path)
        if current == host_workspace_root:
            break
        try:
            _ = current.relative_to(host_workspace_root)
        except ValueError:
            break
        current = current.parent
    candidates.reverse()
    return candidates


def load_agents_instruction_files(
    *,
    project_id: str,
    sandbox_code_root: str,
    include_workspace_root_agents: bool = False,
) -> tuple[tuple[AgentsInstructionFile, ...], tuple[str, ...], Path | None]:
    """Load AGENTS.md files scoped to the isolated sandbox code root."""

    warnings: list[str] = []
    try:
        host_workspace_root = resolve_host_workspace_root(project_id).resolve(strict=False)
        host_code_root = host_path_for_sandbox_code_root(
            project_id=project_id,
            sandbox_code_root=sandbox_code_root,
        ).resolve(strict=False)
    except Exception as exc:
        logger.debug("workspace_code_context.host_mapping_failed", exc_info=True)
        return (), (f"Failed to map sandbox_code_root to host path: {exc}",), None

    if not host_code_root.exists():
        warnings.append(f"sandbox_code_root host path does not exist: {host_code_root}")
    elif not host_code_root.is_dir():
        warnings.append(f"sandbox_code_root host path is not a directory: {host_code_root}")

    try:
        _ = host_code_root.relative_to(host_workspace_root)
    except ValueError:
        return (), ("sandbox_code_root is not inside the project workspace mount",), host_code_root

    loaded: list[AgentsInstructionFile] = []
    total_chars = 0
    for agents_path in _candidate_agents_paths(
        host_workspace_root=host_workspace_root,
        host_code_root=host_code_root,
        include_workspace_root_agents=include_workspace_root_agents,
    ):
        try:
            content = agents_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = agents_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(f"Failed to read {agents_path}: {exc}")
            continue
        content, truncated = _truncate_agents_content(content)
        remaining = _MAX_AGENTS_TOTAL_CHARS - total_chars
        if remaining <= 0:
            warnings.append("AGENTS.md instruction budget exhausted")
            break
        if len(content) > remaining:
            content = content[:remaining] + "\n[...truncated AGENTS.md total budget...]"
            truncated = True
        total_chars += len(content)
        sandbox_agents_path = _sandbox_path_for_host_path(
            host_workspace_root=host_workspace_root,
            host_path=agents_path,
        )
        loaded.append(
            AgentsInstructionFile(
                sandbox_path=sandbox_agents_path,
                content=content,
                truncated=truncated,
            )
        )

    return tuple(loaded), tuple(warnings), host_code_root


def load_workspace_code_context(
    *,
    project_id: str,
    root_metadata: Mapping[str, Any] | None,
    workspace_metadata: Mapping[str, Any] | None,
) -> WorkspaceCodeContext:
    """Resolve sandbox code root and scoped AGENTS.md files for a worker brief."""

    sandbox_code_root = resolve_sandbox_code_root(root_metadata, workspace_metadata)
    if not sandbox_code_root:
        return WorkspaceCodeContext(sandbox_code_root=None)
    include_workspace_root_agents = False
    code_context = (
        workspace_metadata.get("code_context") if workspace_metadata is not None else None
    )
    if isinstance(code_context, Mapping):
        code_context_mapping = cast(Mapping[str, Any], code_context)
        include_workspace_root_agents = (
            code_context_mapping.get("include_workspace_root_agents") is True
        )
    agents_files, warnings, host_code_root = load_agents_instruction_files(
        project_id=project_id,
        sandbox_code_root=sandbox_code_root,
        include_workspace_root_agents=include_workspace_root_agents,
    )
    return WorkspaceCodeContext(
        sandbox_code_root=sandbox_code_root,
        host_code_root=host_code_root,
        agents_files=agents_files,
        warnings=warnings,
    )
