"""Agent-first V2 Provider/Consumer coverage for Workspace Context."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.workspace_context import (
    WorkspaceContextAccess,
    WorkspaceContextCandidate,
    WorkspaceContextError,
    WorkspaceContextErrorCode,
    WorkspaceContextSnapshot,
    WorkspaceContextSwitchOutcome,
    WorkspaceContextSwitchRequest,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workspace_context_services import (
    WORKSPACE_CONTEXT_APPLICATION_MODULE_V2,
    WORKSPACE_CONTEXT_APPLICATION_SERVICE_V2,
    WORKSPACE_CONTEXT_JUDGE_MODULE_V2,
    WORKSPACE_CONTEXT_JUDGE_SERVICE_V2,
    WORKSPACE_CONTEXT_PROVIDER_MODULE_V2,
    WORKSPACE_CONTEXT_PROVIDER_SERVICE_V2,
    WorkspaceContextApplicationResolverV2,
    WorkspaceContextApplicationServiceV2,
)
from src.infrastructure.workspace_core.context_judge import (
    WorkspaceContextJudgeRequest,
    WorkspaceContextJudgeUnavailable,
    WorkspaceContextJudgeVerdict,
)

pytestmark = pytest.mark.unit

_OBSERVED_AT = datetime(2026, 8, 26, 1, 2, 3, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _FakePersistence:
    def __init__(
        self,
        *,
        accessible: WorkspaceContextAccess | None = None,
        current: WorkspaceContextSnapshot | None = None,
        candidates: tuple[WorkspaceContextCandidate, ...] = (),
    ) -> None:
        self.accessible = accessible
        self.current = current
        self.candidates = candidates
        self.initialize_calls: list[WorkspaceContextCandidate] = []
        self.switch_calls: list[WorkspaceContextSwitchRequest] = []

    async def get_accessible(self, user_id: str) -> WorkspaceContextAccess | None:
        assert user_id == "user-1"
        return self.accessible

    async def get_current(self, user_id: str) -> WorkspaceContextSnapshot | None:
        assert user_id == "user-1"
        return self.current

    async def list_candidates(self, user_id: str) -> tuple[WorkspaceContextCandidate, ...]:
        assert user_id == "user-1"
        return self.candidates

    async def initialize(
        self,
        user_id: str,
        *,
        candidate: WorkspaceContextCandidate,
        observed_at: datetime,
    ) -> WorkspaceContextAccess:
        assert user_id == "user-1"
        assert observed_at == _OBSERVED_AT
        self.initialize_calls.append(candidate)
        return _access(candidate, revision=0)

    async def switch(
        self,
        user_id: str,
        *,
        actor_api_key_id: str | None,
        request: WorkspaceContextSwitchRequest,
        observed_at: datetime,
    ) -> WorkspaceContextSwitchOutcome:
        assert user_id == "user-1"
        assert actor_api_key_id == "key-1"
        assert observed_at == _OBSERVED_AT
        self.switch_calls.append(request)
        return WorkspaceContextSwitchOutcome(
            context=WorkspaceContextSnapshot(
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                revision=request.expected_revision + 1,
                updated_at=observed_at,
            ),
            changed=True,
        )


class _FakeJudge:
    def __init__(
        self,
        *,
        selected: WorkspaceContextCandidate | None = None,
        unavailable: bool = False,
    ) -> None:
        self.selected = selected
        self.unavailable = unavailable
        self.requests: list[WorkspaceContextJudgeRequest] = []

    async def select(
        self,
        request: WorkspaceContextJudgeRequest,
    ) -> WorkspaceContextJudgeVerdict:
        self.requests.append(request)
        if self.unavailable:
            raise WorkspaceContextJudgeUnavailable("judge unavailable")
        assert self.selected is not None
        selected = next(
            (
                candidate
                for candidate in request.candidates
                if (candidate.tenant_id, candidate.project_id, candidate.membership_role)
                == (
                    self.selected.tenant_id,
                    self.selected.project_id,
                    self.selected.membership_role,
                )
            ),
            None,
        )
        if selected is None:
            from src.infrastructure.workspace_core.context_judge import (
                WorkspaceContextCandidate as JudgeCandidate,
            )

            selected = JudgeCandidate(
                tenant_id=self.selected.tenant_id,
                project_id=self.selected.project_id,
                membership_role=self.selected.membership_role,
            )
        return WorkspaceContextJudgeVerdict(
            selected=selected,
            rationale="The structured evidence selects the supplied candidate.",
            evidence=["candidate is accessible"],
            agent_id="provider-judge:model-1",
            tool_name="select_workspace_context",
            input_json=request.model_dump(mode="json"),
            output_json={"candidate_index": 1, "rationale": "selected"},
            latency_ms=7,
        )


def _candidate(project_id: str) -> WorkspaceContextCandidate:
    return WorkspaceContextCandidate(
        tenant_id="tenant-1",
        project_id=project_id,
        membership_role="member",
    )


def _access(candidate: WorkspaceContextCandidate, *, revision: int) -> WorkspaceContextAccess:
    return WorkspaceContextAccess(
        context=WorkspaceContextSnapshot(
            tenant_id=candidate.tenant_id,
            project_id=candidate.project_id,
            revision=revision,
            updated_at=_OBSERVED_AT,
        ),
        membership_role=candidate.membership_role,
    )


async def test_accessible_current_context_requires_no_candidate_or_judgment() -> None:
    candidate = _candidate("project-current")
    persistence = _FakePersistence(accessible=_access(candidate, revision=4))
    judge = _FakeJudge(unavailable=True)
    service = WorkspaceContextApplicationServiceV2(persistence=persistence, judge=judge)

    result = await service.get_or_initialize(user_id="user-1", observed_at=_OBSERVED_AT)

    assert result.context.project_id == "project-current"
    assert judge.requests == []
    assert persistence.initialize_calls == []


async def test_single_candidate_is_a_structural_selection_without_judgment() -> None:
    candidate = _candidate("project-only")
    persistence = _FakePersistence(candidates=(candidate,))
    judge = _FakeJudge(unavailable=True)
    service = WorkspaceContextApplicationServiceV2(persistence=persistence, judge=judge)

    result = await service.get_or_initialize(user_id="user-1", observed_at=_OBSERVED_AT)

    assert result.context.project_id == "project-only"
    assert judge.requests == []
    assert persistence.initialize_calls == [candidate]


async def test_multiple_candidates_require_judgment_and_emit_complete_audit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = _candidate("project-a")
    second = _candidate("project-b")
    current = WorkspaceContextSnapshot(
        tenant_id="tenant-old",
        project_id="project-old",
        revision=3,
        updated_at=_OBSERVED_AT,
    )
    persistence = _FakePersistence(current=current, candidates=(first, second))
    judge = _FakeJudge(selected=second)
    service = WorkspaceContextApplicationServiceV2(persistence=persistence, judge=judge)

    with caplog.at_level(logging.INFO):
        result = await service.get_or_initialize(user_id="user-1", observed_at=_OBSERVED_AT)

    assert result.context.project_id == "project-b"
    assert persistence.initialize_calls == [second]
    assert len(judge.requests) == 1
    assert judge.requests[0].current is not None
    assert judge.requests[0].current.revision == 3
    record = next(record for record in caplog.records if record.msg == "Workspace Context judgment")
    assert record.agent_id == "provider-judge:model-1"
    assert record.tool_name == "select_workspace_context"
    assert record.input_json == judge.requests[0].model_dump(mode="json")
    assert record.output_json == {"candidate_index": 1, "rationale": "selected"}
    assert record.rationale == "The structured evidence selects the supplied candidate."
    assert record.latency_ms == 7


@pytest.mark.parametrize("invalid_verdict", [False, True])
async def test_judge_failure_or_out_of_roster_selection_has_zero_mutation(
    invalid_verdict: bool,
) -> None:
    first = _candidate("project-a")
    second = _candidate("project-b")
    persistence = _FakePersistence(candidates=(first, second))
    judge = (
        _FakeJudge(selected=_candidate("project-not-accessible"))
        if invalid_verdict
        else _FakeJudge(unavailable=True)
    )
    service = WorkspaceContextApplicationServiceV2(persistence=persistence, judge=judge)

    with pytest.raises(WorkspaceContextError) as error:
        await service.get_or_initialize(user_id="user-1", observed_at=_OBSERVED_AT)

    assert error.value.code is WorkspaceContextErrorCode.UNAVAILABLE
    assert persistence.initialize_calls == []


async def test_switch_is_delegated_without_hidden_policy() -> None:
    persistence = _FakePersistence()
    service = WorkspaceContextApplicationServiceV2(
        persistence=persistence,
        judge=_FakeJudge(unavailable=True),
    )
    request = WorkspaceContextSwitchRequest(
        tenant_id="tenant-2",
        project_id="project-2",
        expected_revision=5,
        idempotency_key="switch-1",
    )

    outcome = await service.switch(
        user_id="user-1",
        actor_api_key_id="key-1",
        request=request,
        observed_at=_OBSERVED_AT,
    )

    assert outcome.context.revision == 6
    assert persistence.switch_calls == [request]


def test_provider_judge_and_application_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}

    assert entries[WORKSPACE_CONTEXT_PROVIDER_MODULE_V2].enabled is True
    assert entries[WORKSPACE_CONTEXT_JUDGE_MODULE_V2].enabled is True
    assert entries[WORKSPACE_CONTEXT_APPLICATION_MODULE_V2].enabled is True
    assert entries[WORKSPACE_CONTEXT_APPLICATION_MODULE_V2].inject == {
        "provider": WORKSPACE_CONTEXT_PROVIDER_SERVICE_V2,
        "judge": WORKSPACE_CONTEXT_JUDGE_SERVICE_V2,
    }
    order = tuple(entry.module_ref for entry in document.entries)
    assert (
        order.index(WORKSPACE_CONTEXT_PROVIDER_MODULE_V2)
        < order.index(WORKSPACE_CONTEXT_JUDGE_MODULE_V2)
        < order.index(WORKSPACE_CONTEXT_APPLICATION_MODULE_V2)
    )


async def test_generation_resolver_binds_application_to_operation_db() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=111,
        version=111,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-workspace-context:test",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(WORKSPACE_CONTEXT_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, WorkspaceContextApplicationResolverV2)
            assert resolver.resolve(operation).context.persistence._session is db
    finally:
        await db.close()
        await host.close()


@pytest.mark.parametrize(
    "disabled_module",
    [WORKSPACE_CONTEXT_PROVIDER_MODULE_V2, WORKSPACE_CONTEXT_JUDGE_MODULE_V2],
)
async def test_missing_required_provider_or_judge_fails_without_fallback(
    disabled_module: str,
) -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == disabled_module else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=112,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-workspace-context-services" in str(error.value)
