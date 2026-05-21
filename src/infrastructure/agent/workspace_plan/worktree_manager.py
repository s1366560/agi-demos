"""Attempt worktree preparation and integration helpers for workspace plans."""

from __future__ import annotations

import posixpath
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, Protocol, SupportsInt, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttemptStatus,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
    SqlWorkspaceRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.agent.workspace.code_context import load_workspace_code_context
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    ACTIVE_EXECUTION_ROOT,
    ATTEMPT_WORKTREE,
    ROOT_GOAL_TASK_ID,
    WORKTREE_SETUP,
)
from src.infrastructure.agent.workspace_plan.run_contract import WorkspaceRunContract

_GENERATED_DIRTY_PATH_PATTERNS = (
    "ITERATION-REPORT-*.md",
    "*.tsbuildinfo",
    "frontend/tests/e2e-results.json",
    "frontend/tests/screenshots/*",
    "frontend/test-results/*",
    "frontend/playwright-report/*",
    "frontend/coverage/*",
    "test-results/*",
    "playwright-report/*",
    "coverage/*",
)


def is_generated_dirty_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    return any(fnmatchcase(normalized, pattern) for pattern in _GENERATED_DIRTY_PATH_PATTERNS)


class WorkspaceCommandRunner(Protocol):
    async def run_command(self, command: str, *, timeout: int) -> dict[str, object]: ...


class WorkspaceCommandRunnerFactory(Protocol):
    def __call__(self, *, project_id: str, tenant_id: str) -> WorkspaceCommandRunner: ...


@dataclass(frozen=True)
class WorkspaceExecutionRoot:
    """Resolved execution root for a workspace worker attempt."""

    workspace_root: str | None
    sandbox_code_root: str | None
    active_root: str | None
    is_isolated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace_root": self.workspace_root,
            "sandbox_code_root": self.sandbox_code_root,
            "active_root": self.active_root,
            "is_isolated": self.is_isolated,
        }


@dataclass(frozen=True)
class AttemptWorktreeContext:
    """Structured runtime context for one attempt worktree."""

    workspace_root: str | None
    sandbox_code_root: str | None
    active_root: str | None
    worktree_path: str | None
    branch_name: str | None
    base_ref: str | None
    attempt_id: str | None
    is_isolated: bool
    setup_status: str
    setup_reason: str | None = None
    setup_output: str | None = None

    @property
    def execution_root(self) -> WorkspaceExecutionRoot:
        return WorkspaceExecutionRoot(
            workspace_root=self.workspace_root,
            sandbox_code_root=self.sandbox_code_root,
            active_root=self.active_root,
            is_isolated=self.is_isolated,
        )

    @property
    def setup_failed(self) -> bool:
        return self.setup_status == "failed"

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace_root": self.workspace_root,
            "sandbox_code_root": self.sandbox_code_root,
            "active_root": self.active_root,
            "worktree_path": self.worktree_path,
            "branch_name": self.branch_name,
            "base_ref": self.base_ref,
            "attempt_id": self.attempt_id,
            "is_isolated": self.is_isolated,
            "setup_status": self.setup_status,
            "setup_reason": self.setup_reason,
            "setup_output": self.setup_output,
        }

    def setup_payload(self) -> dict[str, object]:
        return {
            "status": self.setup_status,
            "reason": self.setup_reason,
            "output": self.setup_output,
            "worktree_path": self.worktree_path,
            "branch_name": self.branch_name,
            "base_ref": self.base_ref,
            "attempt_id": self.attempt_id,
        }

    def metadata_patch(self) -> dict[str, object]:
        patch: dict[str, object] = {
            ATTEMPT_WORKTREE: self.to_dict(),
            WORKTREE_SETUP: self.setup_payload(),
        }
        if self.active_root:
            patch[ACTIVE_EXECUTION_ROOT] = self.active_root
        return patch

    def setup_note(self) -> str:
        return worktree_setup_note(
            status=self.setup_status,
            reason=self.setup_reason,
            output=self.setup_output,
            worktree_path=self.worktree_path,
            branch_name=self.branch_name,
            base_ref=self.base_ref,
        )


class WorkspaceWorktreeManager:
    """Prepare attempt git worktrees and return structured runtime context."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        runner_factory: WorkspaceCommandRunnerFactory,
    ) -> None:
        self._session = session
        self._runner_factory = runner_factory

    async def prepare_attempt(  # noqa: C901, PLR0911, PLR0912
        self,
        *,
        workspace_id: str,
        task: WorkspaceTask,
        attempt_id: str | None,
    ) -> AttemptWorktreeContext | None:
        metadata = dict(task.metadata or {})
        feature_checkpoint = metadata.get("feature_checkpoint")
        if not isinstance(feature_checkpoint, Mapping) and not attempt_id:
            return None
        feature_metadata: Mapping[str, Any] = (
            cast(Mapping[str, Any], feature_checkpoint)
            if isinstance(feature_checkpoint, Mapping)
            else {}
        )

        worktree_path_template = _mapping_string(feature_metadata, "worktree_path")
        branch_name = _mapping_string(feature_metadata, "branch_name")
        base_ref = _mapping_string(feature_metadata, "base_ref") or "HEAD"
        if (not worktree_path_template or not branch_name) and not attempt_id:
            return _context(
                setup_status="skipped",
                setup_reason="feature checkpoint does not include worktree_path and branch_name",
                attempt_id=attempt_id,
                base_ref=base_ref,
            )

        workspace = await SqlWorkspaceRepository(self._session).find_by_id(workspace_id)
        if workspace is None:
            return _context(
                setup_status="skipped",
                setup_reason="workspace not found",
                attempt_id=attempt_id,
                base_ref=base_ref,
            )

        root_metadata: Mapping[str, Any] = {}
        root_task_id = _mapping_string(metadata, ROOT_GOAL_TASK_ID)
        if root_task_id:
            root_task = await SqlWorkspaceTaskRepository(self._session).find_by_id(root_task_id)
            if root_task is not None and root_task.workspace_id == workspace_id:
                root_metadata = dict(root_task.metadata or {})

        workspace_metadata = dict(getattr(workspace, "metadata", {}) or {})
        code_context = load_workspace_code_context(
            project_id=workspace.project_id,
            root_metadata=root_metadata,
            workspace_metadata=workspace_metadata,
        )
        sandbox_code_root = code_context.sandbox_code_root
        if not sandbox_code_root:
            return _context(
                setup_status="skipped",
                setup_reason="sandbox_code_root is not available for this workspace",
                attempt_id=attempt_id,
                base_ref=base_ref,
            )

        resolved_attempt_id = str(attempt_id) if attempt_id else None
        if not worktree_path_template:
            worktree_path = default_attempt_worktree_path(
                sandbox_code_root=sandbox_code_root,
                attempt_id=str(resolved_attempt_id),
            )
        else:
            worktree_path = worktree_path_template.replace(
                "${sandbox_code_root}", sandbox_code_root
            )
        if not branch_name:
            branch_name = worktree_branch_name(
                node_id=task.id,
                attempt_id=str(resolved_attempt_id),
            )
        if "${sandbox_code_root}" in worktree_path:
            return _context(
                setup_status="skipped",
                setup_reason="worktree_path still contains an unresolved sandbox_code_root placeholder",
                workspace_root=None,
                sandbox_code_root=sandbox_code_root,
                worktree_path=worktree_path,
                branch_name=branch_name,
                base_ref=base_ref,
                attempt_id=resolved_attempt_id,
            )

        contract = WorkspaceRunContract.from_sources(
            workspace_metadata=workspace_metadata,
            root_metadata=root_metadata,
        )
        path_validation = contract.validate_paths(
            code_root=sandbox_code_root,
            worktree_path=worktree_path,
        )
        if not path_validation.allowed:
            return _context(
                setup_status="failed",
                setup_reason=(
                    "workspace run contract rejected worker launch path: "
                    f"{path_validation.reason}; "
                    f"workspace_root={path_validation.workspace_root}; "
                    f"code_root={path_validation.code_root}; "
                    f"worktree_path={path_validation.worktree_path}"
                ),
                workspace_root=path_validation.workspace_root,
                sandbox_code_root=path_validation.code_root or sandbox_code_root,
                worktree_path=path_validation.worktree_path or worktree_path,
                branch_name=branch_name,
                base_ref=base_ref,
                attempt_id=resolved_attempt_id,
            )

        protected_worktree_names = await self.active_attempt_worktree_names(workspace_id)
        command = worktree_setup_command(
            sandbox_code_root=sandbox_code_root,
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
            protected_worktree_names=protected_worktree_names,
        )
        try:
            result = await self._runner_factory(
                project_id=workspace.project_id,
                tenant_id=workspace.tenant_id,
            ).run_command(command, timeout=120)
        except Exception as exc:
            return _context(
                setup_status="failed",
                setup_reason=str(exc),
                workspace_root=path_validation.workspace_root,
                sandbox_code_root=sandbox_code_root,
                worktree_path=worktree_path,
                branch_name=branch_name,
                base_ref=base_ref,
                attempt_id=resolved_attempt_id,
            )

        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        raw_exit_code = result.get("exit_code") or 0
        exit_code = (
            int(raw_exit_code)
            if isinstance(raw_exit_code, str | bytes | bytearray | SupportsInt)
            else 1
        )
        if exit_code != 0:
            return _context(
                setup_status="failed",
                setup_reason=compact_command_output(stderr or stdout),
                workspace_root=path_validation.workspace_root,
                sandbox_code_root=sandbox_code_root,
                worktree_path=worktree_path,
                branch_name=branch_name,
                base_ref=base_ref,
                attempt_id=resolved_attempt_id,
            )
        return _context(
            setup_status="prepared",
            setup_output=compact_command_output(stdout),
            workspace_root=path_validation.workspace_root,
            sandbox_code_root=sandbox_code_root,
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
            attempt_id=resolved_attempt_id,
        )

    async def active_attempt_worktree_names(self, workspace_id: str) -> tuple[str, ...]:
        rows = await self._session.execute(
            select(WorkspaceTaskSessionAttemptModel.id)
            .where(WorkspaceTaskSessionAttemptModel.workspace_id == workspace_id)
            .where(
                WorkspaceTaskSessionAttemptModel.status.in_(
                    [
                        WorkspaceTaskSessionAttemptStatus.PENDING.value,
                        WorkspaceTaskSessionAttemptStatus.RUNNING.value,
                        WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value,
                    ]
                )
            )
        )
        return tuple(sorted(str(row[0]) for row in rows.all() if row[0]))


def default_attempt_worktree_path(*, sandbox_code_root: str, attempt_id: str) -> str:
    return posixpath.normpath(
        posixpath.join(sandbox_code_root.rstrip("/"), "..", ".memstack", "worktrees", attempt_id)
    )


def worktree_branch_name(*, node_id: str, attempt_id: str) -> str:
    node_token = safe_git_token(node_id)[:48]
    attempt_token = safe_git_token(attempt_id)[:12]
    return f"workspace/{node_token}-{attempt_token}"


def safe_git_token(value: str) -> str:
    token = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value)
    token = token.strip("./-")
    return token or "node"


def worktree_setup_command(
    *,
    sandbox_code_root: str,
    worktree_path: str,
    branch_name: str,
    base_ref: str,
    protected_worktree_names: Iterable[str] = (),
) -> str:
    code_root = shlex.quote(sandbox_code_root)
    worktree = shlex.quote(worktree_path)
    branch = shlex.quote(branch_name)
    base = shlex.quote(base_ref)
    _ = protected_worktree_names
    return ";".join(
        [
            "set -e",
            f"C={code_root}",
            f"W={worktree}",
            f"B={branch}",
            f"R={base}",
            'mkdir -p "$C"',
            'cd "$C"',
            "git rev-parse --is-inside-work-tree >/dev/null 2>&1||git init >/dev/null",
            "git config user.email workspace-agent@memstack.local",
            'git config user.name "Workspace Agent"',
            (
                "git rev-parse --verify HEAD >/dev/null 2>&1"
                "||{ git add -A; git commit --allow-empty -m init >/dev/null; }"
            ),
            'N=$(basename "$PWD")',
            'F=$(dirname "$PWD")/.memstack/git-remotes/$N.git',
            (
                'git remote get-url origin >/dev/null 2>&1'
                '||{ mkdir -p "$(dirname "$F")"; git init --bare "$F" >/dev/null; '
                'git remote add origin "$F"; }'
            ),
            'mkdir -p "$(dirname "$W")"',
            (
                'if [ -e "$W/.git" ]||[ -f "$W/.git" ];then '
                'H=$(git rev-parse "$R"); git -C "$W" checkout "$B"; '
                'git -C "$W" merge-base --is-ancestor "$H" HEAD'
                '||git -C "$W" merge --no-edit "$H"; '
                'else git worktree add -B "$B" "$W" "$R"; fi'
            ),
            'printf "git_head=%s\\n" "$(git -C "$W" rev-parse HEAD)"',
        ]
    )


def worktree_integration_command(
    *,
    sandbox_code_root: str,
    worktree_path: str,
    commit_ref: str,
) -> str:
    code_root = shlex.quote(sandbox_code_root)
    worktree = shlex.quote(worktree_path)
    commit = shlex.quote(commit_ref)
    return "\n".join(
        [
            "set -e",
            f"cd {code_root}",
            *_generated_dirty_path_shell_helpers(),
            f"if ! git -C {worktree} cat-file -e {commit}^{{commit}}; then",
            '  echo "status=failed"',
            '  echo "reason=commit_ref not found in attempt worktree"',
            "  exit 65",
            "fi",
            f"if git merge-base --is-ancestor {commit} HEAD; then",
            '  echo "status=already_merged"',
            '  printf "git_head=%s\\n" "$(git rev-parse --short HEAD)"',
            "  exit 0",
            "fi",
            'dirty="$(git status --porcelain)"',
            'dirty_paths="$(printf "%s\\n" "$dirty" | sed "s/^...//")"',
            'classify_dirty_paths "$dirty_paths"',
            'if [ -n "$dirty" ] && [ "$dirty_generated_only" = "true" ]; then',
            '  clean_generated_dirty_paths "$dirty_paths"',
            '  echo "generated_dirty_cleaned=true"',
            '  dirty="$(git status --porcelain)"',
            '  dirty_paths="$(printf "%s\\n" "$dirty" | sed "s/^...//")"',
            '  classify_dirty_paths "$dirty_paths"',
            "fi",
            'if [ -n "$dirty" ]; then',
            '  echo "status=blocked_dirty_main"',
            '  echo "reason=sandbox_code_root has uncommitted changes"',
            '  printf "dirty_signature=%s\\n" "$(printf "%s" "$dirty" | git hash-object --stdin)"',
            '  printf "dirty_generated_only=%s\\n" "$dirty_generated_only"',
            "  git status --short",
            "  exit 66",
            "fi",
            "set +e",
            f'merge_output="$(git merge --no-edit {commit} 2>&1)"',
            'merge_status="$?"',
            'printf "%s\\n" "$merge_output"',
            'if [ "$merge_status" -ne 0 ] && '
            + 'printf "%s\\n" "$merge_output" | '
            + 'grep -qi "refusing to merge unrelated histories"; then',
            "  git merge --abort >/dev/null 2>&1 || true",
            '  echo "unrelated_history_retry=true"',
            'merge_output="$(git merge --no-edit --allow-unrelated-histories '
            + f'-X theirs {commit} 2>&1)"',
            '  merge_status="$?"',
            '  printf "%s\\n" "$merge_output"',
            "fi",
            "set -e",
            'if [ "$merge_status" -ne 0 ]; then',
            '  echo "status=failed"',
            '  echo "reason=merge_failed_aborted"',
            "  git status --short",
            "  git merge --abort >/dev/null 2>&1 || true",
            '  exit "$merge_status"',
            "fi",
            'echo "status=merged"',
            'printf "git_head=%s\\n" "$(git rev-parse --short HEAD)"',
        ]
    )


def worktree_dirty_signature_command(*, sandbox_code_root: str) -> str:
    code_root = shlex.quote(sandbox_code_root)
    return "\n".join(
        [
            "set -e",
            f"cd {code_root}",
            *_generated_dirty_path_shell_helpers(include_cleaner=False),
            'dirty="$(git status --porcelain)"',
            'if [ -n "$dirty" ]; then',
            '  dirty_paths="$(printf "%s\\n" "$dirty" | sed "s/^...//")"',
            '  classify_dirty_paths "$dirty_paths"',
            '  echo "status=dirty"',
            '  printf "dirty_signature=%s\\n" "$(printf "%s" "$dirty" | git hash-object --stdin)"',
            '  printf "dirty_generated_only=%s\\n" "$dirty_generated_only"',
            "  git status --short",
            "  exit 0",
            "fi",
            'echo "status=clean"',
        ]
    )


def _generated_dirty_path_shell_helpers(*, include_cleaner: bool = True) -> list[str]:
    path_case = "|".join(_GENERATED_DIRTY_PATH_PATTERNS)
    lines = [
        "is_generated_dirty_path() {",
        '  case "$1" in',
        f"    {path_case}) return 0 ;;",
        "    *) return 1 ;;",
        "  esac",
        "}",
        "classify_dirty_paths() {",
        '  dirty_paths="$1"',
        "  dirty_generated_only=false",
        '  if [ -n "$dirty_paths" ]; then',
        "    dirty_generated_only=true",
        "    while IFS= read -r dirty_path; do",
        '      [ -n "$dirty_path" ] || continue',
        '      if ! is_generated_dirty_path "$dirty_path"; then',
        "        dirty_generated_only=false",
        "        break",
        "      fi",
        "    done <<EOF_GENERATED_DIRTY_PATHS",
        "$dirty_paths",
        "EOF_GENERATED_DIRTY_PATHS",
        "  fi",
        "}",
    ]
    if include_cleaner:
        lines.extend(
            [
                "clean_generated_dirty_paths() {",
                '  dirty_paths="$1"',
                "  while IFS= read -r dirty_path; do",
                '    [ -n "$dirty_path" ] || continue',
                '    git checkout -- "$dirty_path" 2>/dev/null || true',
                '    git clean -fd -- "$dirty_path" 2>/dev/null || true',
                "  done <<EOF_GENERATED_DIRTY_CLEAN",
                "$dirty_paths",
                "EOF_GENERATED_DIRTY_CLEAN",
                "}",
            ]
        )
    return lines


def worktree_setup_note(
    *,
    status: str,
    reason: str | None = None,
    output: str | None = None,
    worktree_path: str | None = None,
    branch_name: str | None = None,
    base_ref: str | None = None,
) -> str:
    lines = ["[worktree-setup]", f"status={status}"]
    if worktree_path:
        lines.append(f"worktree_path={worktree_path}")
    if branch_name:
        lines.append(f"branch_name={branch_name}")
    if base_ref:
        lines.append(f"base_ref={base_ref}")
    if reason:
        lines.append(f"reason={compact_command_output(reason)}")
    if output:
        lines.append(f"output={compact_command_output(output)}")
    lines.append("[/worktree-setup]")
    return "\n".join(lines)


def compact_command_output(value: str, *, limit: int = 1000) -> str:
    compacted = value.strip().replace("\n", "\\n")
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 15] + "...[truncated]"


def _context(
    *,
    setup_status: str,
    workspace_root: str | None = None,
    sandbox_code_root: str | None = None,
    worktree_path: str | None = None,
    branch_name: str | None = None,
    base_ref: str | None = None,
    attempt_id: str | None = None,
    setup_reason: str | None = None,
    setup_output: str | None = None,
) -> AttemptWorktreeContext:
    active_root = worktree_path or sandbox_code_root
    normalized_active_root = posixpath.normpath(active_root) if active_root else None
    normalized_sandbox_code_root = (
        posixpath.normpath(sandbox_code_root) if sandbox_code_root else None
    )
    normalized_worktree_path = posixpath.normpath(worktree_path) if worktree_path else None
    return AttemptWorktreeContext(
        workspace_root=posixpath.normpath(workspace_root) if workspace_root else None,
        sandbox_code_root=normalized_sandbox_code_root,
        active_root=normalized_active_root,
        worktree_path=normalized_worktree_path,
        branch_name=branch_name,
        base_ref=base_ref,
        attempt_id=attempt_id,
        is_isolated=bool(
            normalized_active_root
            and normalized_sandbox_code_root
            and normalized_active_root != normalized_sandbox_code_root
        ),
        setup_status=setup_status,
        setup_reason=setup_reason,
        setup_output=setup_output,
    )


def _mapping_string(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value.strip() else None


__all__ = [
    "AttemptWorktreeContext",
    "WorkspaceExecutionRoot",
    "WorkspaceWorktreeManager",
    "compact_command_output",
    "default_attempt_worktree_path",
    "safe_git_token",
    "worktree_branch_name",
    "worktree_dirty_signature_command",
    "worktree_integration_command",
    "worktree_setup_command",
    "worktree_setup_note",
]
