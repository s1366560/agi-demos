"""Workspace run contract resolution and workspace path guards.

The contract is the durable operating envelope for autonomous workspace runs.
It deliberately stays small and JSON-serializable so it can live in workspace
metadata and be surfaced through diagnostics without a schema migration.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, SupportsInt

_DEFAULT_CONCURRENCY = 4
_DEFAULT_MAX_ITERATIONS = 80
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_STALL_TIMEOUT_SECONDS = 900
_DEFAULT_COMPLETION_EVIDENCE_POLICY = "required_acceptance_criteria"
_CONTRACT_KEYS = ("workspace_run_contract", "run_contract")


@dataclass(frozen=True)
class WorkspacePathValidation:
    """Result of checking a path against the run contract boundary."""

    allowed: bool
    reason: str | None = None
    workspace_root: str | None = None
    code_root: str | None = None
    worktree_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "workspace_root": self.workspace_root,
            "code_root": self.code_root,
            "worktree_path": self.worktree_path,
        }


@dataclass(frozen=True)
class WorkspaceRunContract:
    """Execution envelope for one autonomous workspace goal run."""

    concurrency: int = _DEFAULT_CONCURRENCY
    max_iterations: int = _DEFAULT_MAX_ITERATIONS
    max_retries: int = _DEFAULT_MAX_RETRIES
    stall_timeout_seconds: int = _DEFAULT_STALL_TIMEOUT_SECONDS
    workspace_root: str | None = None
    hooks: dict[str, Any] = field(default_factory=dict)
    completion_evidence_policy: str = _DEFAULT_COMPLETION_EVIDENCE_POLICY

    @classmethod
    def from_sources(
        cls,
        *,
        workspace_metadata: Mapping[str, Any] | None = None,
        root_metadata: Mapping[str, Any] | None = None,
        workflow_text: str | None = None,
    ) -> WorkspaceRunContract:
        """Resolve contract values from metadata plus optional WORKFLOW text.

        Workspace metadata is the default source. Root-goal metadata and
        `.memstack/workspace/WORKFLOW.md` style text may override it.
        """

        data: dict[str, Any] = {}
        for source in (
            _contract_mapping(workspace_metadata),
            _contract_mapping(root_metadata),
            _parse_workflow_contract(workflow_text),
        ):
            data.update(source)
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> WorkspaceRunContract:
        data = dict(payload or {})
        return cls(
            concurrency=_positive_int(
                data.get("concurrency"),
                default=_DEFAULT_CONCURRENCY,
                field_name="concurrency",
            ),
            max_iterations=_positive_int(
                data.get("max_iterations"),
                default=_DEFAULT_MAX_ITERATIONS,
                field_name="max_iterations",
            ),
            max_retries=_non_negative_int(
                data.get("max_retries"),
                default=_DEFAULT_MAX_RETRIES,
                field_name="max_retries",
            ),
            stall_timeout_seconds=_positive_int(
                data.get("stall_timeout_seconds"),
                default=_DEFAULT_STALL_TIMEOUT_SECONDS,
                field_name="stall_timeout_seconds",
            ),
            workspace_root=_optional_absolute_path(data.get("workspace_root"), "workspace_root"),
            hooks=_mapping_dict(data.get("hooks")),
            completion_evidence_policy=_completion_policy(data.get("completion_evidence_policy")),
        )

    def resolved_workspace_root(self, *, code_root: str | None = None) -> str | None:
        if self.workspace_root:
            return _normalize_absolute_path(self.workspace_root)
        normalized_code_root = _normalize_absolute_path(code_root)
        if not normalized_code_root:
            return None
        return posixpath.dirname(normalized_code_root.rstrip("/")) or "/"

    def validate_paths(
        self,
        *,
        code_root: str | None,
        worktree_path: str | None,
    ) -> WorkspacePathValidation:
        workspace_root = self.resolved_workspace_root(code_root=code_root)
        normalized_code_root = _normalize_absolute_path(code_root)
        normalized_worktree_path = _normalize_absolute_path(worktree_path)
        if not workspace_root:
            return WorkspacePathValidation(
                allowed=False,
                reason="workspace_root cannot be resolved",
                code_root=normalized_code_root,
                worktree_path=normalized_worktree_path,
            )
        if not normalized_code_root:
            return WorkspacePathValidation(
                allowed=False,
                reason="code_root must be an absolute path",
                workspace_root=workspace_root,
                worktree_path=normalized_worktree_path,
            )
        if not normalized_worktree_path:
            return WorkspacePathValidation(
                allowed=False,
                reason="worktree_path must be an absolute path",
                workspace_root=workspace_root,
                code_root=normalized_code_root,
            )
        for label, value in (
            ("code_root", normalized_code_root),
            ("worktree_path", normalized_worktree_path),
        ):
            if value == workspace_root:
                return WorkspacePathValidation(
                    allowed=False,
                    reason=f"{label} cannot equal workspace_root",
                    workspace_root=workspace_root,
                    code_root=normalized_code_root,
                    worktree_path=normalized_worktree_path,
                )
            if not _is_within_root(value, workspace_root):
                return WorkspacePathValidation(
                    allowed=False,
                    reason=f"{label} is outside workspace_root",
                    workspace_root=workspace_root,
                    code_root=normalized_code_root,
                    worktree_path=normalized_worktree_path,
                )
        return WorkspacePathValidation(
            allowed=True,
            workspace_root=workspace_root,
            code_root=normalized_code_root,
            worktree_path=normalized_worktree_path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "concurrency": self.concurrency,
            "max_iterations": self.max_iterations,
            "max_retries": self.max_retries,
            "stall_timeout_seconds": self.stall_timeout_seconds,
            "workspace_root": self.workspace_root,
            "hooks": dict(self.hooks),
            "completion_evidence_policy": self.completion_evidence_policy,
        }


def _contract_mapping(source: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        return {}
    for key in _CONTRACT_KEYS:
        value = source.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _parse_workflow_contract(workflow_text: str | None) -> dict[str, Any]:
    """Parse a small `key: value` contract block from WORKFLOW.md text."""

    if not workflow_text:
        return {}
    parsed: dict[str, Any] = {}
    in_contract_block = False
    for raw_line in workflow_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        header = line.strip("# ").lower()
        if header in {"workspace run contract", "run contract"}:
            in_contract_block = True
            continue
        if in_contract_block and line.startswith("#"):
            break
        if not in_contract_block or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace("-", "_")
        if key in {
            "concurrency",
            "max_iterations",
            "max_retries",
            "stall_timeout_seconds",
            "workspace_root",
            "completion_evidence_policy",
        }:
            parsed[key] = value.strip().strip("`")
    return parsed


def _mapping_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return dict(value)


def _positive_int(value: object, *, default: int, field_name: str) -> int:
    parsed = _int_value(value, default=default, field_name=field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return parsed


def _non_negative_int(value: object, *, default: int, field_name: str) -> int:
    parsed = _int_value(value, default=default, field_name=field_name)
    if parsed < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return parsed


def _int_value(value: object, *, default: int, field_name: str) -> int:
    if value is None or value == "":
        return default
    if not isinstance(value, str | bytes | bytearray | SupportsInt):
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _optional_absolute_path(value: object, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    path = str(value)
    normalized = _normalize_absolute_path(path)
    if normalized is None:
        raise ValueError(f"{field_name} must be an absolute path")
    return normalized


def _completion_policy(value: object) -> str:
    if value is None or value == "":
        return _DEFAULT_COMPLETION_EVIDENCE_POLICY
    policy = str(value)
    allowed = {"required_acceptance_criteria", "any_verifier_evidence", "none"}
    if policy not in allowed:
        raise ValueError(f"completion_evidence_policy must be one of {sorted(allowed)}")
    return policy


def _normalize_absolute_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    path = value.strip()
    if not path or "${" in path or not path.startswith("/"):
        return None
    return _canonical_absolute_path(path)


def _canonical_absolute_path(path: str) -> str:
    try:
        return Path(path).expanduser().resolve(strict=False).as_posix()
    except (OSError, RuntimeError, ValueError):
        return posixpath.normpath(path)


def _is_within_root(path: str, root: str) -> bool:
    try:
        return posixpath.commonpath([root, path]) == root
    except ValueError:
        return False


__all__ = [
    "WorkspacePathValidation",
    "WorkspaceRunContract",
]
