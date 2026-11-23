"""Checkpoint an enrolled episode's graph effect before dispatching a portable projection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, bindparam, func, select

from src.configuration.config import get_settings
from src.domain.model.knowledge_sync.contracts import (
    GraphSyncContent,
    GraphSyncEntity,
    GraphSyncRelationship,
    KnowledgeSyncError,
)
from src.domain.model.memory.processing import MemoryProcessingSource
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.host.packages.project_plugin_installation import (
    AgentPackagePin,
    ProjectPluginInstallationService,
)
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    project_package_actor_can_execute,
)
from src.infrastructure.adapters.secondary.persistence.graph_projection_job_model import (
    GraphProjectionJob as Job,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel as Enrollment,
)
from src.infrastructure.adapters.secondary.persistence.memory_processing import (
    update_memory_processing_status,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, TaskLog, User
from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    ProjectPluginInstallation as Installation,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_graph_sync_repository import (
    SqlKnowledgeGraphSyncRepository,
)
from src.infrastructure.plugins.package_registry import load_plugin_trust_keys
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


type Sessions = Callable[[], AsyncSession]
RETRY_DELAY = timedelta(seconds=30)
GRANT = frozenset({"tools.execute", "graph.projection.compute"})
logger = logging.getLogger(__name__)


class ExtractionAlreadyAdmitted(RuntimeError):
    """The original extractor owns the effect or its unknown outcome awaits review."""


async def extraction_guard(db: AsyncSession, task_id: str) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return True
    digest = hashlib.sha256(("episode-extraction:" + task_id).encode()).digest()
    key = int.from_bytes(digest[:8], signed=True)
    return bool(
        await db.scalar(
            select(func.pg_try_advisory_xact_lock(bindparam("key", key, type_=BigInteger)))
        )
    )


async def _authority(
    db: AsyncSession, tenant: str, project: str, actor: str
) -> ProjectPluginInstallationService:
    user = await db.get(User, actor, populate_existing=True)
    target = ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id=tenant, project_id=project)
    if not user or not await project_package_actor_can_execute(
        db, current_user=user, requested_scope=target
    ):
        raise OptionalBusinessError("forbidden", "projection actor cannot execute in this project")
    keys = await asyncio.to_thread(
        load_plugin_trust_keys, get_settings().plugin_marketplace_trusted_key_files
    )
    return ProjectPluginInstallationService(
        db, ScopeBindingV2(tenant_id=tenant, project_id=project), tuple(keys)
    )


async def _check_tool(
    service: ProjectPluginInstallationService, pin: AgentPackagePin, tool: str
) -> None:
    release = await service.pinned_package(pin)
    if (
        release.services.requires
        or not GRANT.issubset(release.approved_permissions)
        or not any(t.name == tool and t.permissions == GRANT for t in release.contribution.tools)
    ):
        raise OptionalBusinessError(
            "forbidden", "package lacks the dedicated graph projection grant"
        )


@dataclass(frozen=True)
class ExtractionAdmission:
    task_id: str
    claimed: bool
    summary: dict[str, Any] | None


async def select_for_source(
    sessions: Sessions,
    admission: AsyncSession,
    *,
    tenant: str,
    source: MemoryProcessingSource,
    author: str,
) -> ExtractionAdmission | None:
    project = await admission.get(Project, source.project_id)
    selection = (project.graph_config or {}).get("sync_projection") if project else None
    if selection and source.task_id and not await extraction_guard(admission, source.task_id):
        raise ExtractionAlreadyAdmitted("graph extraction is already in progress")
    try:
        return await _claim(
            sessions, tenant=tenant, source=source, author=author, selection=selection
        )
    except (OptionalBusinessError, RuntimeV2Error):
        # No graph effect was admitted. A fresh authorized request may retry this revision.
        async with sessions() as db, db.begin():
            await update_memory_processing_status(db, source, "FAILED")
        raise


async def _claim(
    sessions: Sessions,
    *,
    tenant: str,
    source: MemoryProcessingSource,
    author: str,
    selection: dict[str, str] | None,
) -> ExtractionAdmission | None:
    if not source.task_id:
        if selection:
            raise KnowledgeSyncError("knowledge_sync_write_context_required")
        return None
    async with sessions() as db, db.begin():
        task = await db.get(TaskLog, source.task_id, with_for_update=True, populate_existing=True)
        prior = (task.result or {}).get("projection_state") if task else None
        if not selection and not prior:
            return None
        if (
            not task
            or task.group_id != source.project_id
            or task.task_type != "add_episode"
            or MemoryProcessingSource.from_payload(task.payload) != source
        ):
            raise KnowledgeSyncError("knowledge_sync_write_conflict")
        job = await db.get(Job, source.task_id)
        if job:
            if (job.tenant_id, job.project_id, job.memory_id, job.source_revision) != (
                tenant,
                source.project_id,
                source.memory_id,
                source.revision,
            ):
                raise KnowledgeSyncError("knowledge_sync_write_conflict")
            if job.phase in {"extracting", "review"}:
                raise ExtractionAlreadyAdmitted(
                    "graph extraction already admitted; inspect its status before retry"
                )
            return ExtractionAdmission(job.task_id, False, job.summary)
        if not selection:
            raise KnowledgeSyncError("knowledge_sync_write_conflict")
        actor = task.payload.get("user_id")
        if not isinstance(actor, str):
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        service = await _authority(db, tenant, source.project_id, actor)
        plugin, tool = selection["plugin_id"], selection["tool"]
        state = await db.get(Installation, (source.project_id, plugin))
        if not state or not state.enabled or not state.active:
            raise OptionalBusinessError("not_enabled", "selected projection package is unavailable")
        release = await service.active_release(plugin)
        pin = AgentPackagePin(
            tenant_id=tenant,
            project_id=source.project_id,
            plugin_id=plugin,
            version=release.version,
            digest=release.digest,
            authorization_epoch=state.authorization_epoch,
        )
        await _check_tool(service, pin, tool)
        db.add(
            Job(
                task_id=source.task_id,
                tenant_id=tenant,
                project_id=source.project_id,
                memory_id=source.memory_id,
                source_revision=source.revision,
                actor_id=actor,
                author_id=author,
                pin=asdict(pin),
                tool=tool,
                phase="extracting",
            )
        )
        task.result = {"projection_state": "extracting"}
        task.status = "PROCESSING"
        task.started_at = datetime.now(UTC)
        if not await update_memory_processing_status(db, source, "PROCESSING"):
            raise KnowledgeSyncError("knowledge_sync_write_conflict")
        return ExtractionAdmission(source.task_id, True, None)


def extraction_input(result: object) -> dict[str, Any]:
    nodes = getattr(result, "nodes", ()) or ()
    edges = getattr(result, "edges", ()) or ()
    if len(nodes) > 200 or len(edges) > 500:
        raise ValueError("extracted graph exceeds the projection contract")
    snapshot = {
        "nodes": [
            {"uuid": node.uuid, "name": node.name, "kind": node.entity_type} for node in nodes
        ],
        "edges": [
            {
                "source": edge.source_uuid,
                "target": edge.target_uuid,
                "kind": edge.relationship_type,
                "fact": edge.fact,
                "score": edge.weight,
            }
            for edge in edges
        ],
    }
    if len(json.dumps(snapshot, allow_nan=False).encode()) > 120_000:
        raise ValueError("extracted graph exceeds the worker protocol envelope")
    return snapshot


async def captured(
    sessions: Sessions,
    source: MemoryProcessingSource,
    snapshot: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    async with sessions() as db, db.begin():
        job = await db.get(Job, source.task_id, with_for_update=True)
        task = await db.get(TaskLog, source.task_id)
        if (
            not job
            or not task
            or job.phase != "extracting"
            or not await update_memory_processing_status(db, source, "COMPLETED")
        ):
            raise KnowledgeSyncError("knowledge_sync_write_conflict")
        job.snapshot, job.summary, job.phase = snapshot, summary, "pending"
        task.result = {**summary, "projection_state": "pending"}
        task.status, task.progress, task.completed_at = "COMPLETED", 100, datetime.now(UTC)
        task.message = "Graph extraction complete; projection queued"


async def uncertain(sessions: Sessions, task_id: str) -> None:
    async with sessions() as db, db.begin():
        job = await db.get(Job, task_id, with_for_update=True)
        task = await db.get(TaskLog, task_id)
        if job and task and job.phase == "extracting":
            job.phase = "review"
            task.result = {"projection_state": "review"}
            task.status = "FAILED"
            task.error_message = "Graph extraction outcome requires reconciliation before retry"


async def deliver(sessions: Sessions, task_id: str) -> dict[str, Any]:
    async with sessions() as db, db.begin():
        job = await db.get(Job, task_id, with_for_update=True, populate_existing=True)
        if not job or job.phase not in {"pending", "complete", "withdrawn"} or job.summary is None:
            raise KnowledgeSyncError("knowledge_sync_write_conflict")
        if job.phase != "pending":
            return {**job.summary, "projection_state": job.phase}
        task = await db.get(TaskLog, task_id)
        if not task:
            raise KnowledgeSyncError("knowledge_sync_write_conflict")
        try:
            async with db.begin_nested():
                await _apply(db, job)
        except (OptionalBusinessError, KnowledgeSyncError, RuntimeV2Error) as exc:
            if isinstance(exc, OptionalBusinessError) and exc.code == "busy":
                job.retry_at = datetime.now(UTC) + timedelta(seconds=15)
            else:
                job.phase = "withdrawn"
                job.snapshot = None
            task.message = "Graph projection unavailable under its admitted scope and release"
        except Exception as exc:
            logger.warning("Graph projection %s deferred (%s)", task_id, type(exc).__name__)
            job.retry_at = datetime.now(UTC) + RETRY_DELAY
            task.message = "Graph projection pending retry"
        else:
            job.phase = "complete"
            job.snapshot = None
            task.message = "Graph processing complete"
        response = {**job.summary, "projection_state": job.phase}
        task.result = response
        return response


async def _apply(db: AsyncSession, job: Job) -> None:
    pin = AgentPackagePin(**job.pin)
    project = await db.get(Project, job.project_id, populate_existing=True)
    enrollment = await db.get(Enrollment, job.project_id, populate_existing=True)
    memory = await db.get(Memory, job.memory_id, populate_existing=True)
    expected = {"plugin_id": pin.plugin_id, "tool": job.tool}
    if (
        not project
        or project.tenant_id != job.tenant_id
        or (project.graph_config or {}).get("sync_projection") != expected
        or not enrollment
        or not enrollment.enabled
        or not memory
        or (memory.version, memory.task_id, memory.project_id)
        != (job.source_revision, job.task_id, job.project_id)
    ):
        raise KnowledgeSyncError("knowledge_sync_write_conflict")
    service = await _authority(db, job.tenant_id, job.project_id, job.actor_id)
    await _check_tool(service, pin, job.tool)
    if job.snapshot is None:
        raise KnowledgeSyncError("knowledge_sync_write_conflict")
    value = await service.invoke_pinned_tool(pin, job.tool, job.snapshot)
    # Take the same enrollment/memory fences used by the sync write authority before journal commit.
    await db.refresh(project, with_for_update={"read": True})
    await db.refresh(enrollment, with_for_update={"read": True})
    await db.refresh(memory, with_for_update=True)
    if (
        (project.graph_config or {}).get("sync_projection") != expected
        or not enrollment.enabled
        or (memory.project_id, memory.task_id, memory.version)
        != (job.project_id, job.task_id, job.source_revision)
    ):
        raise KnowledgeSyncError("knowledge_sync_write_conflict")
    current = await _authority(db, job.tenant_id, job.project_id, job.actor_id)
    await _check_tool(current, pin, job.tool)
    checked = GraphSyncContent(
        source_revision=job.source_revision,
        change_sequence=1,
        audit_attempt=1,
        entities=tuple(GraphSyncEntity.from_dict(v) for v in value["entities"]),
        relationships=tuple(GraphSyncRelationship.from_dict(v) for v in value["relationships"]),
    )
    if len(checked.entities) > len(job.snapshot["nodes"]) or len(checked.relationships) > len(
        job.snapshot["edges"]
    ):
        raise KnowledgeSyncError("knowledge_sync_input_invalid")
    written = await SqlKnowledgeGraphSyncRepository(db).enqueue_derived(
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        memory_id=job.memory_id,
        author_id=job.author_id,
        source_revision=job.source_revision,
        entities=checked.entities,
        relationships=checked.relationships,
    )
    if written is None:
        raise KnowledgeSyncError("knowledge_sync_write_conflict")


async def recover(sessions: Sessions) -> None:
    async with sessions() as db:
        if db.get_bind().dialect.name == "postgresql":
            # A transaction-scoped guard survives long extractions and is released
            # by PostgreSQL when their owning process dies. Never repeat an unknown write.
            after = ""
            while True:
                unknown = (
                    await db.scalars(
                        select(Job.task_id)
                        .where(Job.phase == "extracting", Job.task_id > after)
                        .order_by(Job.task_id)
                        .limit(64)
                    )
                ).all()
                if not unknown:
                    break
                for identity in unknown:
                    if await extraction_guard(db, identity):
                        await uncertain(sessions, identity)
                after = unknown[-1]
        pending = (
            await db.scalars(
                select(Job.task_id)
                .where(Job.phase == "pending", Job.retry_at <= datetime.now(UTC))
                .order_by(Job.retry_at, Job.task_id)
                .limit(16)
            )
        ).all()

    for task in pending:
        await deliver(sessions, task)


@asynccontextmanager
async def recovery_loop(sessions: Sessions) -> AsyncIterator[None]:
    async def poll() -> None:
        while True:
            try:
                await recover(sessions)
            except Exception as exc:
                logger.warning("Projection recovery pending (%s)", type(exc).__name__)
            await asyncio.sleep(15)

    task = asyncio.create_task(poll(), name="graph-projection-recovery")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
