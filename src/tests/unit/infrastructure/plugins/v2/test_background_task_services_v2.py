"""V2 Provider/Consumer and lifecycle coverage for background task services."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.background_tasks import TaskManager
from src.infrastructure.adapters.secondary.workflow import AsyncioWorkflowEngine
from src.infrastructure.plugins.v2.background_task_services import (
    BACKGROUND_TASK_ACCESS_PROVIDER_MODULE_V2,
    BACKGROUND_TASK_APPLICATION_MODULE_V2,
    BACKGROUND_TASK_APPLICATION_SERVICE_V2,
    BACKGROUND_TASK_MANAGER_MODULE_V2,
    BACKGROUND_TASK_MANAGER_SERVICE_V2,
    BackgroundTaskApplicationResolverV2,
    BackgroundTaskApplicationServicesV2,
    BackgroundTaskManagerRuntimeV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workflow_runtime import (
    WORKFLOW_RUNTIME_MODULE_V2,
    WORKFLOW_RUNTIME_SERVICE_V2,
    WorkflowRuntimeServiceV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def _noop() -> None:
    return None


class _AccessibleProjects:
    def __init__(self, project_ids: set[str] | None) -> None:
        self.project_ids = project_ids
        self.calls: list[tuple[str, bool]] = []

    async def accessible_project_ids(
        self,
        *,
        user_id: str,
        is_superuser: bool,
    ) -> set[str] | None:
        self.calls.append((user_id, is_superuser))
        return self.project_ids


async def test_application_resolver_uses_operation_session_and_shared_manager() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=61,
        version=61,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="background-tasks:user-a",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            runtime = operation.require(BACKGROUND_TASK_MANAGER_SERVICE_V2)
            resolver = operation.require(BACKGROUND_TASK_APPLICATION_SERVICE_V2)

            assert isinstance(runtime, BackgroundTaskManagerRuntimeV2)
            assert isinstance(resolver, BackgroundTaskApplicationResolverV2)
            services = resolver.resolve(operation)
            assert services.manager is runtime.manager
            assert getattr(services.access, "_session", None) is db
    finally:
        await db.close()
        await host.close()


async def test_task_manager_identity_and_cleanup_survive_generation_replacement() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=62,
        version=62,
    )
    assert first.accepted is True
    lease = await host.acquire()
    generation = await lease.__aenter__()
    runtime = generation.resolve(
        BACKGROUND_TASK_MANAGER_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(runtime, BackgroundTaskManagerRuntimeV2)
    manager = runtime.manager
    tracked = manager.create_task("survives-hmr", _noop)
    first_workflow_runtime = generation.resolve(
        WORKFLOW_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(first_workflow_runtime, WorkflowRuntimeServiceV2)
    first_workflows = await first_workflow_runtime.engine.list_workflows()
    assert [workflow.workflow_id for workflow in first_workflows] == [tracked.task_id]
    cleanup_task = manager._cleanup_task
    assert cleanup_task is not None
    try:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=63,
            version=63,
        )
        assert second.accepted is True
        replacement = host.manager.current
        assert replacement is not None
        replacement_runtime = replacement.resolve(
            BACKGROUND_TASK_MANAGER_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        assert isinstance(replacement_runtime, BackgroundTaskManagerRuntimeV2)
        assert replacement_runtime.manager is manager
        assert replacement_runtime.manager.get_task(tracked.task_id) is tracked
        replacement_workflow_runtime = replacement.resolve(
            WORKFLOW_RUNTIME_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        assert isinstance(replacement_workflow_runtime, WorkflowRuntimeServiceV2)
        replacement_workflows = await replacement_workflow_runtime.engine.list_workflows()
        assert [workflow.workflow_id for workflow in replacement_workflows] == [tracked.task_id]
        assert manager._cleanup_task is cleanup_task
        assert not cleanup_task.done()
    finally:
        await lease.__aexit__(None, None, None)

    assert manager._cleanup_task is cleanup_task
    assert not cleanup_task.done()
    await host.close()
    assert manager._cleanup_task is None


async def test_later_candidate_failure_keeps_active_manager_and_tasks() -> None:
    workflow_factory_calls = 0

    def workflow_factory() -> AsyncioWorkflowEngine:
        nonlocal workflow_factory_calls
        workflow_factory_calls += 1
        if workflow_factory_calls > 1:
            raise RuntimeError("candidate workflow unavailable")
        return AsyncioWorkflowEngine(manager=TaskManager())

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workflow_runtime_factory=workflow_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=64,
        version=64,
    )
    assert first.accepted is True
    active = host.manager.current
    assert active is not None
    runtime = active.resolve(
        BACKGROUND_TASK_MANAGER_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(runtime, BackgroundTaskManagerRuntimeV2)
    manager = runtime.manager
    tracked = manager.create_task("retained-after-candidate-failure", _noop)
    cleanup_task = manager._cleanup_task
    assert cleanup_task is not None

    failed = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=65,
        version=65,
    )

    assert failed.accepted is False
    assert host.manager.current is active
    assert manager.get_task(tracked.task_id) is tracked
    assert manager._cleanup_task is cleanup_task
    assert not cleanup_task.done()

    await host.close()
    assert manager._cleanup_task is None


async def test_application_filters_owner_and_project_before_limit() -> None:
    manager = TaskManager()
    now = datetime.now(UTC)
    owned = manager.create_task("owned", _noop)
    owned.owner_user_id = "user-a"
    owned.created_at = now
    project = manager.create_task("project", _noop)
    project.project_id = "project-a"
    project.created_at = now - timedelta(minutes=1)
    foreign = manager.create_task("foreign", _noop)
    foreign.owner_user_id = "user-b"
    foreign.project_id = "project-b"
    foreign.created_at = now - timedelta(minutes=2)
    unscoped = manager.create_task("unscoped", _noop)
    unscoped.created_at = now - timedelta(minutes=3)
    access = _AccessibleProjects({"project-a"})
    services = BackgroundTaskApplicationServicesV2(manager=manager, access=access)

    page = await services.list_tasks(
        user_id="user-a",
        is_superuser=False,
        status=None,
        limit=1,
    )

    assert page.total == 2
    assert [task["task_id"] for task in page.tasks] == [owned.task_id]
    assert project.task_id in manager.tasks
    assert foreign.task_id in manager.tasks
    assert unscoped.task_id in manager.tasks
    assert access.calls == [("user-a", False)]


def test_background_task_modules_are_explicit_and_workflow_injects_manager() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert BACKGROUND_TASK_MANAGER_MODULE_V2 in enabled_modules
    assert BACKGROUND_TASK_ACCESS_PROVIDER_MODULE_V2 in enabled_modules
    assert BACKGROUND_TASK_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(BACKGROUND_TASK_MANAGER_MODULE_V2) < enabled_modules.index(
        WORKFLOW_RUNTIME_MODULE_V2
    )
    assert enabled_modules.index(BACKGROUND_TASK_ACCESS_PROVIDER_MODULE_V2) < (
        enabled_modules.index(BACKGROUND_TASK_APPLICATION_MODULE_V2)
    )
    workflow_entry = next(
        entry for entry in document.entries if entry.module_ref == WORKFLOW_RUNTIME_MODULE_V2
    )
    assert workflow_entry.inject == {"task_manager": "service:runtime.background-task-manager"}
    application_entry = next(
        entry
        for entry in document.entries
        if entry.module_ref == BACKGROUND_TASK_APPLICATION_MODULE_V2
    )
    assert application_entry.inject == {
        "manager": "service:runtime.background-task-manager",
        "provider": "service:persistence.background-task-access-provider",
    }


async def test_background_task_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == BACKGROUND_TASK_ACCESS_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=64)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-background-task-services" in str(error.value)
