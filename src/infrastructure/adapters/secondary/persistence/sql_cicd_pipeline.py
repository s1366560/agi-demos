"""SQL helpers for ordinary-chat CI/CD state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    CicdPipelineRunModel,
    CicdPipelineStageRunModel,
)


class SqlCicdPipelineRepository:
    """Persistence boundary for tenant/project-scoped CI/CD runs."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_run(
        self,
        *,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        provider: str,
        repository: str,
        branch: str | None,
        commit_ref: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> CicdPipelineRunModel:
        model = CicdPipelineRunModel(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            provider=provider,
            repository=repository,
            branch=branch,
            commit_ref=commit_ref,
            status="running",
            started_at=datetime.now(UTC),
            metadata_json=dict(metadata or {}),
        )
        self._db.add(model)
        await self._db.flush()
        return model

    async def finish_run(
        self,
        run: CicdPipelineRunModel,
        *,
        status: str,
        reason: str | None = None,
        external_id: str | None = None,
        external_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CicdPipelineRunModel:
        run.status = status
        run.reason = reason
        run.external_id = external_id
        run.external_url = external_url
        run.completed_at = datetime.now(UTC)
        run.updated_at = run.completed_at
        if metadata:
            run.metadata_json = {**dict(run.metadata_json or {}), **metadata}
        await self._db.flush()
        return run

    async def create_stage_run(
        self,
        *,
        run_id: str,
        stage: str,
        command: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> CicdPipelineStageRunModel:
        model = CicdPipelineStageRunModel(
            id=str(uuid.uuid4()),
            run_id=run_id,
            stage=stage,
            status="running",
            command=command,
            started_at=datetime.now(UTC),
            metadata_json=dict(metadata or {}),
        )
        self._db.add(model)
        await self._db.flush()
        return model

    async def finish_stage_run(
        self,
        stage_run: CicdPipelineStageRunModel,
        *,
        status: str,
        exit_code: int | None,
        stdout_preview: str | None,
        stderr_preview: str | None,
        log_ref: str | None = None,
        artifact_refs: list[str] | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CicdPipelineStageRunModel:
        completed_at = datetime.now(UTC)
        stage_run.status = status
        stage_run.exit_code = exit_code
        stage_run.stdout_preview = stdout_preview
        stage_run.stderr_preview = stderr_preview
        stage_run.log_ref = log_ref
        stage_run.artifact_refs_json = list(artifact_refs or [])
        stage_run.duration_ms = duration_ms
        stage_run.completed_at = completed_at
        stage_run.updated_at = completed_at
        if metadata:
            stage_run.metadata_json = {**dict(stage_run.metadata_json or {}), **metadata}
        await self._db.flush()
        return stage_run


__all__ = ["SqlCicdPipelineRepository"]
