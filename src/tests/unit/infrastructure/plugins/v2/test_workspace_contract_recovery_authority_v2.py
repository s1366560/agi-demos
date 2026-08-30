"""Generation-owned persistence coverage for workspace contract recovery."""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import src.infrastructure.plugins.v2.agent_event_query_services as event_query_services
import src.infrastructure.plugins.v2.artifact_content_gc_runtime as persistence_runtime
from src.infrastructure.agent.workspace.contract_agent_runtime import (
    recover_workspace_contract_payload,
)
from src.infrastructure.agent.workspace.planner_agent_decomposer import (
    RuntimeWorkspacePlannerAgentTurnRunner,
)
from src.infrastructure.agent.workspace_plan.iteration_review import (
    RuntimeWorkspaceIterationReviewAgentTurnRunner,
)
from src.infrastructure.agent.workspace_plan.supervisor_decision import (
    RuntimeWorkspaceSupervisorAgentTurnRunner,
)
from src.infrastructure.agent.workspace_plan.verification_judge import (
    RuntimeWorkspaceVerifierAgentTurnRunner,
)
from src.infrastructure.agent.workspace_plan.worktree_agent import (
    RuntimeWorkspaceWorktreeAgentTurnRunner,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _SessionContext:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def __aenter__(self) -> AsyncSession:
        return self._db

    async def __aexit__(self, *_args: object) -> None:
        await self._db.close()


class _EventQueryService:
    def __init__(self, events: list[object]) -> None:
        self._events = events
        self.calls: list[dict[str, object]] = []

    async def get_events(self, **kwargs: object) -> list[object]:
        self.calls.append(dict(kwargs))
        return list(self._events)


async def test_contract_recovery_resolves_session_and_event_query_from_one_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncSession()
    session_calls = 0

    def session_factory() -> _SessionContext:
        nonlocal session_calls
        session_calls += 1
        return _SessionContext(db)

    monkeypatch.setattr(persistence_runtime, "async_session_factory", session_factory)
    service = _EventQueryService(
        [
            SimpleNamespace(event_type="observe", event_data={"payload": {"value": "old"}}),
            SimpleNamespace(event_type="observe", event_data={"payload": {"value": "new"}}),
        ]
    )
    observed: dict[str, object] = {}

    def resolve_event_query(_self: object, operation: Any) -> _EventQueryService:
        observed["generation"] = operation.descriptor.generation
        observed["db"] = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
        observed["identity"] = operation.require(OPERATION_IDENTITY_SERVICE_V2)
        observed["metadata"] = operation.require(OPERATION_METADATA_SERVICE_V2)
        return service

    monkeypatch.setattr(
        event_query_services.AgentEventQueryResolverV2,
        "resolve",
        resolve_event_query,
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=731,
        version=731,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)

    try:
        payload = await recover_workspace_contract_payload(
            conversation_id="conversation-1",
            tenant_id="tenant-1",
            project_id="project-1",
            extract_payload=lambda event: event["data"].get("payload"),
            limit=17,
        )
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    assert payload == {"value": "new"}
    assert session_calls == 1
    assert service.calls == [
        {
            "conversation_id": "conversation-1",
            "from_time_us": 0,
            "from_counter": 0,
            "limit": 17,
        }
    ]
    assert observed == {
        "generation": 731,
        "db": db,
        "identity": {"tenant_id": "tenant-1", "project_id": "project-1"},
        "metadata": {
            "kind": "workspace-contract-event-recovery",
            "conversation_id": "conversation-1",
        },
    }


def test_contract_recovery_has_no_static_persistence_composition() -> None:
    source = inspect.getsource(recover_workspace_contract_payload)

    assert "ASYNC_SESSION_FACTORY_SERVICE_V2" in source
    assert "AGENT_EVENT_QUERY_SERVICE_V2" in source
    assert "force_process_host_lease=True" in source
    assert "async_session_factory" not in source
    assert "SqlAgentExecutionEventRepository" not in source


def test_workspace_contract_runners_scope_every_recovery_query() -> None:
    methods = (
        RuntimeWorkspacePlannerAgentTurnRunner.run_planning_turn,
        RuntimeWorkspaceSupervisorAgentTurnRunner.run_decision_turn,
        RuntimeWorkspaceVerifierAgentTurnRunner.run_verification_turn,
        RuntimeWorkspaceWorktreeAgentTurnRunner.run_preparation_turn,
        RuntimeWorkspaceIterationReviewAgentTurnRunner.run_review_turn,
    )

    for method in methods:
        tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
        recovery_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "recover_workspace_contract_payload"
        ]
        assert len(recovery_calls) == 2
        for call in recovery_calls:
            keyword_names = {keyword.arg for keyword in call.keywords}
            assert {"tenant_id", "project_id"} <= keyword_names
