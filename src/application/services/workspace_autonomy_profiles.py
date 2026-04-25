"""Scenario profiles for workspace autonomy completion rules.

The central blackboard can orchestrate many kinds of work. Software delivery
needs code artifacts and test evidence, while research or operations work may
ship documents, citations, runbooks, or incident records. This module keeps
those proof rules data-driven and rooted in workspace/root-goal metadata.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

WorkspaceType = Literal["general", "software_development", "research", "operations"]
VerificationGrade = Literal["pass", "warn", "fail"]

_DEFAULT_WORKSPACE_TYPE: WorkspaceType = "general"
_GRADE_RANK: dict[str, int] = {"fail": 0, "warn": 1, "pass": 2}
_INTERNAL_ARTIFACT_PREFIXES = ("workspace_task:",)
_SANDBOX_WORKSPACE_ROOT = "/workspace"
_CODE_CONTEXT_KEY = "code_context"
_SANDBOX_CODE_ROOT_KEY = "sandbox_code_root"


@dataclass(frozen=True)
class EvidencePolicy:
    """Completion-evidence rules for one autonomy scenario."""

    allow_internal_task_artifacts: bool
    required_artifact_prefixes: tuple[str, ...] = ()
    requires_external_artifact: bool = False
    minimum_verification_grade: VerificationGrade = "warn"
    stream_completion_reports_success: bool = True


@dataclass(frozen=True)
class WorkspaceAutonomyProfile:
    """Resolved profile used by runtime completion/adjudication gates."""

    workspace_type: WorkspaceType
    evidence: EvidencePolicy


@dataclass(frozen=True)
class CompletionEvidenceEvaluation:
    """Result of applying a profile to root-goal completion evidence."""

    allowed: bool
    reason: str | None
    profile: WorkspaceAutonomyProfile
    accepted_artifacts: tuple[str, ...]


@dataclass(frozen=True)
class WorkspaceCodeContextEvaluation:
    """Resolved code-root readiness for scenario-specific execution."""

    allowed: bool
    reason: str | None
    workspace_type: WorkspaceType
    sandbox_code_root: str | None


_BUILTIN_PROFILES: dict[WorkspaceType, WorkspaceAutonomyProfile] = {
    "general": WorkspaceAutonomyProfile(
        workspace_type="general",
        evidence=EvidencePolicy(
            allow_internal_task_artifacts=True,
            minimum_verification_grade="warn",
            stream_completion_reports_success=True,
        ),
    ),
    "software_development": WorkspaceAutonomyProfile(
        workspace_type="software_development",
        evidence=EvidencePolicy(
            allow_internal_task_artifacts=False,
            required_artifact_prefixes=(
                "git_diff:",
                "patch:",
                "commit:",
                "pull_request:",
                "test_run:",
                "file_snapshot:",
                "sandbox_repo:",
                "codebase:",
            ),
            requires_external_artifact=True,
            minimum_verification_grade="pass",
            stream_completion_reports_success=False,
        ),
    ),
    "research": WorkspaceAutonomyProfile(
        workspace_type="research",
        evidence=EvidencePolicy(
            allow_internal_task_artifacts=False,
            required_artifact_prefixes=("document:", "citation:", "url:", "artifact:", "file:"),
            requires_external_artifact=True,
            minimum_verification_grade="warn",
            stream_completion_reports_success=False,
        ),
    ),
    "operations": WorkspaceAutonomyProfile(
        workspace_type="operations",
        evidence=EvidencePolicy(
            allow_internal_task_artifacts=False,
            required_artifact_prefixes=(
                "runbook:",
                "incident:",
                "dashboard:",
                "artifact:",
                "file:",
            ),
            requires_external_artifact=True,
            minimum_verification_grade="warn",
            stream_completion_reports_success=False,
        ),
    ),
}


def _mapping_value(source: Mapping[str, Any] | None, key: str) -> Any:  # noqa: ANN401
    if not isinstance(source, Mapping):
        return None
    return source.get(key)


def _source_profile_mapping(source: Mapping[str, Any] | None) -> Mapping[str, Any]:
    value = _mapping_value(source, "autonomy_profile")
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _source_code_context_mapping(source: Mapping[str, Any] | None) -> Mapping[str, Any]:
    value = _mapping_value(source, _CODE_CONTEXT_KEY)
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _profile_mapping(
    root_metadata: Mapping[str, Any] | None,
    workspace_metadata: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    for source in (root_metadata, workspace_metadata):
        profile = _source_profile_mapping(source)
        if profile:
            return profile
    return {}


def _coerce_workspace_type(value: Any) -> WorkspaceType | None:  # noqa: ANN401
    if value == "software_development":
        return "software_development"
    if value == "research":
        return "research"
    if value == "operations":
        return "operations"
    if value == "general":
        return "general"
    return None


def normalize_sandbox_code_root(value: Any) -> str | None:  # noqa: ANN401
    """Normalize a sandbox code root without allowing workspace escapes."""

    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if not raw.startswith("/"):
        raw = f"{_SANDBOX_WORKSPACE_ROOT}/{raw}"
    normalized = posixpath.normpath(raw)
    if normalized == _SANDBOX_WORKSPACE_ROOT:
        return normalized
    if not normalized.startswith(f"{_SANDBOX_WORKSPACE_ROOT}/"):
        return None
    return normalized


def _is_isolated_sandbox_code_root(path: str | None) -> bool:
    return bool(path and path != _SANDBOX_WORKSPACE_ROOT and path.startswith("/workspace/"))


def resolve_sandbox_code_root(
    root_metadata: Mapping[str, Any] | None,
    workspace_metadata: Mapping[str, Any] | None = None,
) -> str | None:
    """Resolve the effective sandbox-visible code root for software work."""

    root_code_context = _source_code_context_mapping(root_metadata)
    workspace_code_context = _source_code_context_mapping(workspace_metadata)
    for value in (
        _mapping_value(root_metadata, _SANDBOX_CODE_ROOT_KEY),
        _mapping_value(root_code_context, _SANDBOX_CODE_ROOT_KEY),
        _mapping_value(workspace_metadata, _SANDBOX_CODE_ROOT_KEY),
        _mapping_value(workspace_code_context, _SANDBOX_CODE_ROOT_KEY),
    ):
        normalized = normalize_sandbox_code_root(value)
        if normalized is not None:
            return normalized
    return None


def resolve_workspace_type(
    root_metadata: Mapping[str, Any] | None,
    workspace_metadata: Mapping[str, Any] | None = None,
) -> WorkspaceType:
    """Resolve the scenario type from root overrides, then workspace defaults."""

    root_profile = _source_profile_mapping(root_metadata)
    workspace_profile = _source_profile_mapping(workspace_metadata)
    for value in (
        _mapping_value(root_metadata, "workspace_type"),
        _mapping_value(root_profile, "workspace_type"),
        _mapping_value(workspace_metadata, "workspace_type"),
        _mapping_value(workspace_profile, "workspace_type"),
    ):
        workspace_type = _coerce_workspace_type(value)
        if workspace_type is not None:
            return workspace_type
    return _DEFAULT_WORKSPACE_TYPE


def _tuple_override(value: Any) -> tuple[str, ...]:  # noqa: ANN401
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    items = cast(Sequence[Any], value)
    return tuple(str(item) for item in items if str(item))


def _bool_override(value: Any, fallback: bool) -> bool:  # noqa: ANN401
    return value if isinstance(value, bool) else fallback


def _grade_override(value: Any, fallback: VerificationGrade) -> VerificationGrade:  # noqa: ANN401
    if isinstance(value, str) and value in _GRADE_RANK:
        return value  # type: ignore[return-value]
    return fallback


def resolve_autonomy_profile(
    root_metadata: Mapping[str, Any] | None,
    workspace_metadata: Mapping[str, Any] | None = None,
) -> WorkspaceAutonomyProfile:
    """Return the effective autonomy profile with metadata overrides applied."""

    workspace_type = resolve_workspace_type(root_metadata, workspace_metadata)
    base = _BUILTIN_PROFILES[workspace_type]
    profile_mapping = _profile_mapping(root_metadata, workspace_metadata)
    policy_mapping = _mapping_value(profile_mapping, "completion_policy")
    if not isinstance(policy_mapping, Mapping):
        return base
    policy_mapping = cast(Mapping[str, Any], policy_mapping)

    required_prefixes = _tuple_override(policy_mapping.get("required_artifact_prefixes"))
    if not required_prefixes:
        required_prefixes = base.evidence.required_artifact_prefixes

    evidence = EvidencePolicy(
        allow_internal_task_artifacts=_bool_override(
            policy_mapping.get("allow_internal_task_artifacts"),
            base.evidence.allow_internal_task_artifacts,
        ),
        required_artifact_prefixes=required_prefixes,
        requires_external_artifact=_bool_override(
            policy_mapping.get("requires_external_artifact"),
            base.evidence.requires_external_artifact,
        ),
        minimum_verification_grade=_grade_override(
            policy_mapping.get("minimum_verification_grade"),
            base.evidence.minimum_verification_grade,
        ),
        stream_completion_reports_success=_bool_override(
            policy_mapping.get("stream_completion_reports_success"),
            base.evidence.stream_completion_reports_success,
        ),
    )
    return WorkspaceAutonomyProfile(workspace_type=workspace_type, evidence=evidence)


def evaluate_workspace_code_context(
    *,
    root_metadata: Mapping[str, Any] | None,
    workspace_metadata: Mapping[str, Any] | None = None,
) -> WorkspaceCodeContextEvaluation:
    """Validate scenario-specific code-root readiness.

    Programming tasks run inside the project sandbox, whose `/workspace` root
    can contain old files, caches, or other projects. Software work therefore
    needs an isolated child directory such as `/workspace/my-evo`.
    """

    workspace_type = resolve_workspace_type(root_metadata, workspace_metadata)
    sandbox_code_root = resolve_sandbox_code_root(root_metadata, workspace_metadata)
    if workspace_type != "software_development":
        return WorkspaceCodeContextEvaluation(
            allowed=True,
            reason=None,
            workspace_type=workspace_type,
            sandbox_code_root=sandbox_code_root,
        )

    if not sandbox_code_root:
        return WorkspaceCodeContextEvaluation(
            allowed=False,
            reason=(
                "software_development workspaces require metadata.sandbox_code_root "
                "or metadata.code_context.sandbox_code_root"
            ),
            workspace_type=workspace_type,
            sandbox_code_root=None,
        )
    if not _is_isolated_sandbox_code_root(sandbox_code_root):
        return WorkspaceCodeContextEvaluation(
            allowed=False,
            reason=(
                "software_development sandbox_code_root must be an isolated "
                "subdirectory under /workspace, not /workspace itself"
            ),
            workspace_type=workspace_type,
            sandbox_code_root=sandbox_code_root,
        )

    return WorkspaceCodeContextEvaluation(
        allowed=True,
        reason=None,
        workspace_type=workspace_type,
        sandbox_code_root=sandbox_code_root,
    )


def is_internal_task_artifact(artifact: str) -> bool:
    return artifact.startswith(_INTERNAL_ARTIFACT_PREFIXES)


def accepted_artifacts_for_profile(
    artifacts: Sequence[str],
    profile: WorkspaceAutonomyProfile,
) -> list[str]:
    """Filter artifacts that count toward the resolved profile's proof rule."""

    accepted: list[str] = []
    for artifact in artifacts:
        if not artifact:
            continue
        if is_internal_task_artifact(artifact):
            if profile.evidence.allow_internal_task_artifacts:
                accepted.append(artifact)
            continue
        prefixes = profile.evidence.required_artifact_prefixes
        if not prefixes or artifact.startswith(prefixes):
            accepted.append(artifact)
    return list(dict.fromkeys(accepted))


def grade_at_least(actual: str, minimum: str) -> bool:
    return _GRADE_RANK.get(actual, -1) >= _GRADE_RANK.get(minimum, 1)


def artifact_references_sandbox_code_root(artifact: str, sandbox_code_root: str) -> bool:
    """Return whether an artifact references the exact sandbox code-root boundary."""

    start = artifact.find(sandbox_code_root)
    if start < 0:
        return False
    end = start + len(sandbox_code_root)
    if end >= len(artifact):
        return True
    return artifact[end] in {"#", "/", ":", "?", "&", "|", " ", "\t", "\n"}


def evaluate_completion_evidence(
    *,
    root_metadata: Mapping[str, Any] | None,
    evidence: Mapping[str, Any],
    workspace_metadata: Mapping[str, Any] | None = None,
) -> CompletionEvidenceEvaluation:
    """Decide whether root-goal evidence is sufficient for completion."""

    profile = resolve_autonomy_profile(root_metadata, workspace_metadata)
    code_context = evaluate_workspace_code_context(
        root_metadata=root_metadata,
        workspace_metadata=workspace_metadata,
    )
    if not code_context.allowed:
        return CompletionEvidenceEvaluation(
            allowed=False,
            reason=code_context.reason,
            profile=profile,
            accepted_artifacts=(),
        )
    artifacts_raw = evidence.get("artifacts")
    artifacts = []
    if isinstance(artifacts_raw, list):
        artifacts = [str(item) for item in cast(list[Any], artifacts_raw) if item]
    accepted = accepted_artifacts_for_profile(artifacts, profile)
    grade = str(evidence.get("verification_grade") or "fail")

    if not grade_at_least(grade, profile.evidence.minimum_verification_grade):
        return CompletionEvidenceEvaluation(
            allowed=False,
            reason=(
                "goal_evidence.verification_grade must be at least "
                f"{profile.evidence.minimum_verification_grade} for "
                f"{profile.workspace_type} workspaces"
            ),
            profile=profile,
            accepted_artifacts=tuple(accepted),
        )

    if profile.evidence.requires_external_artifact and not accepted:
        return CompletionEvidenceEvaluation(
            allowed=False,
            reason=(
                f"{profile.workspace_type} workspaces require completion artifacts "
                "matching the configured evidence policy"
            ),
            profile=profile,
            accepted_artifacts=(),
        )

    if profile.workspace_type == "software_development":
        sandbox_code_root = code_context.sandbox_code_root
        rooted_artifacts = [
            artifact
            for artifact in accepted
            if sandbox_code_root is not None
            and artifact_references_sandbox_code_root(artifact, sandbox_code_root)
        ]
        if not rooted_artifacts:
            return CompletionEvidenceEvaluation(
                allowed=False,
                reason=(
                    "software_development completion artifacts must reference "
                    f"sandbox_code_root {sandbox_code_root}"
                ),
                profile=profile,
                accepted_artifacts=tuple(accepted),
            )
        verifications_raw = evidence.get("verifications")
        verifications = []
        if isinstance(verifications_raw, list):
            verifications = [str(item) for item in cast(list[Any], verifications_raw) if item]
        if not _has_software_test_evidence(
            artifacts=rooted_artifacts,
            verifications=verifications,
            sandbox_code_root=sandbox_code_root,
        ):
            return CompletionEvidenceEvaluation(
                allowed=False,
                reason=(
                    "software_development completion requires a test_run artifact "
                    f"or test verification for sandbox_code_root {sandbox_code_root}"
                ),
                profile=profile,
                accepted_artifacts=tuple(accepted),
            )

    return CompletionEvidenceEvaluation(
        allowed=True,
        reason=None,
        profile=profile,
        accepted_artifacts=tuple(accepted),
    )


def _has_software_test_evidence(
    *,
    artifacts: Sequence[str],
    verifications: Sequence[str],
    sandbox_code_root: str | None,
) -> bool:
    for artifact in artifacts:
        if not artifact.startswith("test_run:"):
            continue
        if sandbox_code_root is None or artifact_references_sandbox_code_root(
            artifact,
            sandbox_code_root,
        ):
            return True
    for verification in verifications:
        normalized = verification.lower()
        if (
            normalized.startswith("test_run:")
            or "npm test" in normalized
            or "pytest" in normalized
            or "vitest" in normalized
            or "jest" in normalized
        ):
            return True
    return False


def stream_completion_reports_success(
    *,
    root_metadata: Mapping[str, Any] | None,
    workspace_metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Whether a normal model stream completion may become a worker success."""

    return resolve_autonomy_profile(
        root_metadata, workspace_metadata
    ).evidence.stream_completion_reports_success
