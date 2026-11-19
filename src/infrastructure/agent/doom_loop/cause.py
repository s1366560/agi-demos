"""Structural fingerprints for unrecoverable tool failures.

The fingerprint identifies a root cause and the repository the call
addressed. Commit message text is not part of the key, so editing only
that field cannot reset the count. A different working_dir or repo_path
is a different key.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

NOT_A_GIT_REPOSITORY = "not_a_git_repository"
_NOT_A_GIT_REPOSITORY_SENTINEL = "Not a git repository"
_UNRECOVERABLE_CODES = frozenset({NOT_A_GIT_REPOSITORY})


@dataclass(frozen=True)
class UnrecoverableToolCause:
    """One structured failure the existing error budget can count."""

    code: str
    repo_key: str
    hint: str

    @property
    def fingerprint(self) -> str:
        return f"{self.code}|{self.repo_key}"

    @property
    def diagnosis(self) -> str:
        return f"{self.code}: {self.hint}"


def repo_key(arguments: Mapping[str, object] | None) -> str:
    """Return the repository the call addressed, defaulting to the workspace root."""
    if not isinstance(arguments, Mapping):
        return "."
    for field in ("repo_path", "working_dir"):
        value = arguments.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "."


def not_a_git_repository_fingerprint(arguments: Mapping[str, object] | None) -> str:
    return f"{NOT_A_GIT_REPOSITORY}|{repo_key(arguments)}"


def classify_unrecoverable_tool_cause(
    tool_name: str,
    arguments: Mapping[str, object] | None,
    *,
    output: str,
    metadata: Mapping[str, object] | None,
    is_error: bool,
) -> UnrecoverableToolCause | None:
    """Return a cause when the tool result carries a known unrecoverable code.

    ``generate_commit`` also matches its own non-repository contract:
    ``metadata.in_git_repo is False`` or the exact sentinel text. Other
    tools are not inferred from prose.
    """
    facts = metadata if isinstance(metadata, Mapping) else {}
    raw_code = facts.get("code")
    code = raw_code if isinstance(raw_code, str) else None
    if (
        code is None
        and tool_name == "generate_commit"
        and _generate_commit_is_not_a_repository(output, facts)
    ):
        code = NOT_A_GIT_REPOSITORY
    if code not in _UNRECOVERABLE_CODES:
        return None
    key = repo_key(arguments)
    supplied_hint = facts.get("hint")
    hint = supplied_hint if isinstance(supplied_hint, str) and supplied_hint.strip() else _hint(key)
    _ = is_error
    return UnrecoverableToolCause(code=code, repo_key=key, hint=hint)


def _generate_commit_is_not_a_repository(output: str, facts: Mapping[str, object]) -> bool:
    if facts.get("in_git_repo") is False:
        return True
    return output.strip() == _NOT_A_GIT_REPOSITORY_SENTINEL and facts.get("in_git_repo") is not True


def _hint(repo_key_value: str) -> str:
    return (
        "Not a git repository. Pass working_dir or repo_path as a workspace-relative "
        f"directory that contains .git. This call used {repo_key_value}. "
        "This tool does not search other directories, run git init, or create a commit."
    )
