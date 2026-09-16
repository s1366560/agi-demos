"""Reverse-apply recorded run changes to the Cloud sandbox workspace.

The Cloud changes snapshot is an attribution replay of recorded change events;
each recorded file carries its full unified-diff hunks plus a content digest.
Revert therefore reconstructs a unified patch from the *server-recomputed*
snapshot (never from client-supplied content) and reverse-applies it with
``git apply --reverse`` inside the project sandbox, checking the whole request
before writing anything.  Files recorded without hunk content (untracked or
empty creations) revert by deleting the recorded path.

Every failure mode fails closed with a structured reason; nothing is written
unless the complete selection passes ``git apply --check --reverse`` and every
recorded deletion target exists.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from src.application.schemas.agent_run_authority import ChangeFileResponse, ChangeHunkResponse
from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

CHANGE_REVERTED_EVENT_TYPE = "change_reverted"
CHANGE_REVERT_EVENT_SOURCE = "run_change_revert"
REVERT_PATCH_PATH = "/tmp/.memstack-change-revert.patch"
_MAX_PATCH_BYTES = 2_000_000
_MAX_RENDERED_PATH = 4096


class RevertPlanError(Exception):
    """Base class for fail-closed revert planning errors."""

    reason_code = "revert_plan_failed"


class UnknownChangeSelectorError(RevertPlanError):
    reason_code = "unknown_change_selector"


class ChangeContentNotRecordedError(RevertPlanError):
    reason_code = "change_content_not_recorded"


class InvalidSelectorPathError(RevertPlanError):
    reason_code = "invalid_selector_path"


@dataclass(frozen=True)
class RevertFilePlan:
    """One validated file-level revert derived from recorded change content."""

    path: str
    patch_digest: str
    status: str
    hunks: tuple[ChangeHunkResponse, ...]
    reverted_indices: tuple[int, ...]
    file_hunk_count: int
    delete_file: bool


@dataclass(frozen=True)
class RevertScriptResult:
    """Parsed markers from the sandbox revert script output."""

    kind: str
    head_commit: str | None
    detail: str | None


def validate_selector_path(path: str) -> str:
    """Accept only repository-relative paths that cannot escape the root."""

    if not path or len(path) > _MAX_RENDERED_PATH:
        raise InvalidSelectorPathError(path)
    if path.startswith(("/", "~")) or "\x00" in path or "\n" in path or "\r" in path:
        raise InvalidSelectorPathError(path)
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise InvalidSelectorPathError(path)
    return path


def plan_change_revert(
    files: Sequence[ChangeFileResponse],
    selectors: Sequence[tuple[str, tuple[int, ...] | None]],
) -> list[RevertFilePlan]:
    """Resolve selectors against the recomputed snapshot, failing closed.

    ``selectors`` pairs a path with either ``None`` (whole file) or explicit
    hunk indices into the snapshot's recorded hunk list.
    """

    by_path: dict[str, ChangeFileResponse] = {}
    for file in files:
        by_path.setdefault(file.path, file)
    plans: list[RevertFilePlan] = []
    for raw_path, hunk_indices in selectors:
        path = validate_selector_path(raw_path)
        matched = by_path.get(path)
        if matched is None:
            raise UnknownChangeSelectorError(path)
        file = matched
        if file.binary:
            raise ChangeContentNotRecordedError(path)
        if file.old_path is not None and file.old_path != file.path:
            # Recorded rename payloads lack the extended headers git apply
            # needs to reverse them; refuse rather than guess.
            raise ChangeContentNotRecordedError(path)
        if hunk_indices is None:
            indices = tuple(range(len(file.hunks)))
        else:
            indices = tuple(sorted(set(hunk_indices)))
            if any(index < 0 or index >= len(file.hunks) for index in indices):
                raise UnknownChangeSelectorError(path)
        if not file.hunks:
            if file.status not in {"added", "untracked"}:
                raise ChangeContentNotRecordedError(path)
            plans.append(
                RevertFilePlan(
                    path=file.path,
                    patch_digest=file.patch_digest,
                    status=file.status,
                    hunks=(),
                    reverted_indices=(),
                    file_hunk_count=0,
                    delete_file=True,
                )
            )
            continue
        plans.append(
            RevertFilePlan(
                path=file.path,
                patch_digest=file.patch_digest,
                status=file.status,
                hunks=tuple(file.hunks[index] for index in indices),
                reverted_indices=indices,
                file_hunk_count=len(file.hunks),
                delete_file=False,
            )
        )
    return plans


def _hunk_header(hunk: ChangeHunkResponse) -> str:
    old_count = sum(1 for line in hunk.lines if line.kind in ("context", "deletion"))
    new_count = sum(1 for line in hunk.lines if line.kind in ("context", "addition"))
    old_span = f"{hunk.old_start},{old_count}"
    new_span = f"{hunk.new_start},{new_count}"
    return f"@@ -{old_span} +{new_span} @@"


def _hunk_body(hunk: ChangeHunkResponse) -> Iterable[str]:
    for line in hunk.lines:
        prefix = " " if line.kind == "context" else "+" if line.kind == "addition" else "-"
        yield f"{prefix}{line.text}"


def _file_patch(plan: RevertFilePlan) -> str:
    if plan.status in {"added", "untracked"}:
        old_name = "/dev/null"
        new_name = f"b/{plan.path}"
    elif plan.status == "deleted":
        old_name = f"a/{plan.path}"
        new_name = "/dev/null"
    else:
        old_name = f"a/{plan.path}"
        new_name = f"b/{plan.path}"
    sections = [f"--- {old_name}", f"+++ {new_name}"]
    for hunk in plan.hunks:
        sections.append(_hunk_header(hunk))
        sections.extend(_hunk_body(hunk))
    return "\n".join(sections) + "\n"


def build_reverse_patch(plans: Sequence[RevertFilePlan]) -> tuple[str, list[str]]:
    """Render one combined forward patch plus the guarded deletion list.

    The patch is applied with ``git apply --reverse``; deletions are paths
    recorded without hunk content whose revert removes the created file.
    """

    patch_parts: list[str] = []
    deletions: list[str] = []
    for plan in plans:
        if plan.delete_file:
            deletions.append(plan.path)
            continue
        patch_parts.append(_file_patch(plan))
    patch = "".join(patch_parts)
    if len(patch.encode("utf-8")) > _MAX_PATCH_BYTES:
        raise ChangeContentNotRecordedError("patch too large to reconstruct safely")
    return patch, deletions


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def render_revert_script(
    *,
    repository_root: str,
    patch: str,
    deletions: Sequence[str],
) -> str:
    """Render the atomic check-then-apply sandbox script.

    Marker lines on stdout drive structured error reporting:
    ``REVERT_ROOT_UNAVAILABLE`` / ``REVERT_CHECK_FAILED`` / ``REVERT_DELETE_MISSING``
    leave the workspace untouched; ``REVERT_PARTIAL`` means the reverse patch was
    restored forward again after a deletion failure (best-effort rollback);
    ``REVERT_OK <head>`` reports the resulting HEAD commit.
    """

    lines = [
        "set -u",
        f"cd {_shell_quote(repository_root)} || {{ echo REVERT_ROOT_UNAVAILABLE; exit 2; }}",
    ]
    has_patch = bool(patch)
    if has_patch:
        encoded = base64.b64encode(patch.encode("utf-8")).decode("ascii")
        lines.append(
            f"printf '%s' {_shell_quote(encoded)} | base64 -d > {_shell_quote(REVERT_PATCH_PATH)}"
        )
    for path in deletions:
        lines.append(
            f"[ -e {_shell_quote(path)} ] || {{ echo 'REVERT_DELETE_MISSING {path}'; exit 5; }}"
        )
    if has_patch:
        lines.append(
            f"git apply --check --reverse --whitespace=nowarn {_shell_quote(REVERT_PATCH_PATH)}"
            " || { echo REVERT_CHECK_FAILED; exit 3; }"
        )
        lines.append(
            f"git apply --reverse --whitespace=nowarn {_shell_quote(REVERT_PATCH_PATH)}"
            " || { echo REVERT_CHECK_FAILED; exit 4; }"
        )
    for path in deletions:
        rollback = ""
        if has_patch:
            rollback = (
                f"git apply --whitespace=nowarn {_shell_quote(REVERT_PATCH_PATH)} >/dev/null 2>&1; "
            )
        lines.append(
            f"rm -- {_shell_quote(path)} || {{ {rollback}echo 'REVERT_PARTIAL {path}'; exit 6; }}"
        )
    lines.append("head=$(git rev-parse HEAD 2>/dev/null) || head=")
    lines.append('echo "REVERT_OK $head"')
    return "\n".join(lines) + "\n"


def parse_revert_script_output(output: str) -> RevertScriptResult:
    """Extract the first revert marker from sandbox output."""

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("REVERT_OK"):
            parts = line.split(maxsplit=1)
            head = parts[1].strip() if len(parts) > 1 else ""
            return RevertScriptResult(
                kind="ok",
                head_commit=head or None,
                detail=None,
            )
        for marker in (
            "REVERT_ROOT_UNAVAILABLE",
            "REVERT_CHECK_FAILED",
            "REVERT_DELETE_MISSING",
            "REVERT_PARTIAL",
        ):
            if line.startswith(marker):
                parts = line.split(maxsplit=1)
                return RevertScriptResult(
                    kind=marker.removeprefix("REVERT_").lower(),
                    head_commit=None,
                    detail=parts[1].strip() if len(parts) > 1 else None,
                )
    return RevertScriptResult(kind="no_marker", head_commit=None, detail=None)


def change_revert_exclusions(
    events: Iterable[AgentExecutionEvent],
) -> tuple[set[tuple[str, str]], set[tuple[str, str, int]]]:
    """Collect recorded revert selectors as file- and hunk-level exclusions."""

    file_level: set[tuple[str, str]] = set()
    hunk_level: set[tuple[str, str, int]] = set()
    for event in events:
        if event.event_type != CHANGE_REVERTED_EVENT_TYPE:
            continue
        data = event.event_data
        if not isinstance(data, dict) or data.get("source") != CHANGE_REVERT_EVENT_SOURCE:
            continue
        reverted = data.get("reverted")
        if not isinstance(reverted, list):
            continue
        for entry in reverted:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            digest = entry.get("patch_digest")
            if not isinstance(path, str) or not isinstance(digest, str):
                continue
            indices = entry.get("hunk_indices")
            if indices is None:
                file_level.add((path, digest))
            elif isinstance(indices, list):
                for index in indices:
                    if isinstance(index, int) and not isinstance(index, bool):
                        hunk_level.add((path, digest, index))
    return file_level, hunk_level


def apply_change_revert_exclusions(
    files: Sequence[ChangeFileResponse],
    exclusions: tuple[set[tuple[str, str]], set[tuple[str, str, int]]],
) -> list[ChangeFileResponse]:
    """Subtract recorded reverts from a replayed snapshot's file list."""

    file_level, hunk_level = exclusions
    if not file_level and not hunk_level:
        return list(files)
    visible: list[ChangeFileResponse] = []
    for file in files:
        key = (file.path, file.patch_digest)
        if key in file_level:
            continue
        kept_hunks = [
            hunk
            for index, hunk in enumerate(file.hunks)
            if (file.path, file.patch_digest, index) not in hunk_level
        ]
        if len(kept_hunks) == len(file.hunks):
            visible.append(file)
            continue
        if not kept_hunks and file.hunks:
            continue
        additions = sum(1 for hunk in kept_hunks for line in hunk.lines if line.kind == "addition")
        deletions = sum(1 for hunk in kept_hunks for line in hunk.lines if line.kind == "deletion")
        visible.append(
            file.model_copy(
                update={"hunks": kept_hunks, "additions": additions, "deletions": deletions}
            )
        )
    return visible


__all__ = [
    "CHANGE_REVERTED_EVENT_TYPE",
    "CHANGE_REVERT_EVENT_SOURCE",
    "ChangeContentNotRecordedError",
    "InvalidSelectorPathError",
    "RevertFilePlan",
    "RevertPlanError",
    "RevertScriptResult",
    "UnknownChangeSelectorError",
    "apply_change_revert_exclusions",
    "build_reverse_patch",
    "change_revert_exclusions",
    "parse_revert_script_output",
    "plan_change_revert",
    "render_revert_script",
    "validate_selector_path",
]
