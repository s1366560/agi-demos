"""Verified worker captures persist without starting a second ROOT scheduler."""

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.plugins.skill_evolution.models import SkillEvolutionSession
from src.infrastructure.plugins.v2 import artifact_content_gc_runtime
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import (
    DataPlaneGenerationAdmissionV2,
    PlatformPluginRuntimeHostV2,
)
from src.infrastructure.plugins.v2.skill_evolution_runtime import SKILL_EVOLUTION_RUNTIME_SERVICE_V2

ROOT = Path(__file__).resolve().parents[6]
SCOPE = ScopeV2(
    kind=ScopeKindV2.SESSION,
    tenant_id="tenant-capture",
    project_id="project-capture",
    session_id="conversation-capture",
)


@pytest.mark.parametrize("scoped", [False, True])
async def test_admitted_worker_capture_is_durable_but_cannot_start_scheduler(
    test_engine, monkeypatch, scoped
):
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(artifact_content_gc_runtime, "async_session_factory", sessions)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=704,
        version=704,
        profile_projector=(
            (
                lambda document: replace(
                    document,
                    entries=tuple(replace(entry, scope=SCOPE) for entry in document.entries),
                )
            )
            if scoped
            else None
        ),
    )
    assert publication.accepted
    candidate = host.manager.current.resolve(SKILL_EVOLUTION_RUNTIME_SERVICE_V2, SCOPE)
    with pytest.raises(RuntimeV2Error, match="not admitted"):
        await candidate.capture_turn({})
    distribution = host.current_distribution.to_payload()
    if scoped:
        from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
            PlatformPluginRepositoryV2,
        )

        async with sessions() as db:
            await PlatformPluginRepositoryV2(db, scope=SCOPE).record_requested_distribution(
                publication.snapshot, publication.envelope
            )
            await db.commit()
            distribution = await PlatformPluginRepositoryV2(
                db, scope=SCOPE
            ).latest_requested_distribution()

    await host.close()
    worker = DataPlaneGenerationAdmissionV2(builtin_runtime_definitions_v2())
    payload = {
        "tenant_id": SCOPE.tenant_id,
        "project_id": SCOPE.project_id,
        "conversation_id": SCOPE.session_id,
        "user_message": "durable capture",
        "final_content": "completed",
        "success": True,
    }
    try:
        async with worker.admit(
            descriptor_payload=distribution["descriptor"],
            distribution_payload=distribution,
            operation_id="worker-capture",
            scope=SCOPE,
        ) as operation:
            service = operation.require(SKILL_EVOLUTION_RUNTIME_SERVICE_V2)
            assert not service.runtime.plugin.scheduler.running
            await service.record_tool_event(payload | {"tool_name": "read", "result": "captured"})
            await service.capture_turn(payload)
            assert not service.runtime.plugin.scheduler.running
            assert not service.runtime.plugin.scheduler._pending_tasks
            with pytest.raises(RuntimeV2Error, match="not admitted"):
                service.schedule_evolution(tenant_id=SCOPE.tenant_id)
            with pytest.raises(RuntimeV2Error):
                await service.capture_turn(payload | {"tenant_id": "other"})
        with pytest.raises(RuntimeV2Error):
            await service.capture_turn(payload)
        async with sessions() as db:
            rows = list((await db.scalars(select(SkillEvolutionSession))).all())
            assert len(rows) == 1
            assert rows[0].tenant_id == SCOPE.tenant_id
            assert rows[0].conversation_id == SCOPE.session_id
            assert rows[0].tool_call_count == 1
            assert not rows[0].processed
    finally:
        await worker.close()
