"""SQL helpers for harness-native workspace CI/CD state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspaceDeploymentModel,
    WorkspacePipelineContractModel,
    WorkspacePipelineRunModel,
    WorkspacePipelineStageRunModel,
)


class SqlWorkspacePipelineRepository:
    """Persistence boundary for workspace-native CI/CD contracts and runs."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_contract(
        self,
        *,
        workspace_id: str,
        plan_id: str | None,
    ) -> WorkspacePipelineContractModel | None:
        stmt = (
            select(WorkspacePipelineContractModel)
            .where(WorkspacePipelineContractModel.workspace_id == workspace_id)
            .where(WorkspacePipelineContractModel.plan_id == plan_id)
            .order_by(
                WorkspacePipelineContractModel.updated_at.desc().nullslast(),
                WorkspacePipelineContractModel.created_at.desc(),
            )
            .limit(1)
        )
        result = await self._db.execute(refresh_select_statement(stmt))
        return result.scalar_one_or_none()

    async def ensure_contract(
        self,
        *,
        workspace_id: str,
        plan_id: str | None,
        provider: str,
        code_root: str | None,
        commands: list[dict[str, Any]],
        env: dict[str, Any] | None = None,
        trigger_policy: dict[str, Any] | None = None,
        timeout_seconds: int = 600,
        auto_deploy: bool = True,
        preview_port: int | None = None,
        health_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkspacePipelineContractModel:
        existing = await self.get_contract(workspace_id=workspace_id, plan_id=plan_id)
        if existing is not None:
            existing.provider = provider
            existing.code_root = code_root
            existing.commands_json = list(commands)
            existing.env_json = dict(env or {})
            existing.trigger_policy_json = dict(trigger_policy or {})
            existing.timeout_seconds = max(1, int(timeout_seconds or 600))
            existing.auto_deploy = bool(auto_deploy)
            existing.preview_port = preview_port
            existing.health_url = health_url
            existing.metadata_json = dict(metadata or {})
            existing.status = "active"
            existing.updated_at = datetime.now(UTC)
            await self._db.flush()
            return existing

        model = WorkspacePipelineContractModel(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            plan_id=plan_id,
            provider=provider,
            code_root=code_root,
            commands_json=list(commands),
            env_json=dict(env or {}),
            trigger_policy_json=dict(trigger_policy or {}),
            timeout_seconds=max(1, int(timeout_seconds or 600)),
            auto_deploy=bool(auto_deploy),
            preview_port=preview_port,
            health_url=health_url,
            status="active",
            metadata_json=dict(metadata or {}),
        )
        self._db.add(model)
        await self._db.flush()
        return model

    async def create_run(
        self,
        *,
        contract_id: str,
        workspace_id: str,
        plan_id: str | None,
        node_id: str | None,
        attempt_id: str | None,
        commit_ref: str | None,
        provider: str,
        metadata: dict[str, Any] | None = None,
    ) -> WorkspacePipelineRunModel:
        model = WorkspacePipelineRunModel(
            id=str(uuid.uuid4()),
            contract_id=contract_id,
            workspace_id=workspace_id,
            plan_id=plan_id,
            node_id=node_id,
            attempt_id=attempt_id,
            commit_ref=commit_ref,
            provider=provider,
            status="running",
            started_at=datetime.now(UTC),
            metadata_json=dict(metadata or {}),
        )
        self._db.add(model)
        await self._db.flush()
        return model

    async def finish_run(
        self,
        run: WorkspacePipelineRunModel,
        *,
        status: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkspacePipelineRunModel:
        run.status = status
        run.reason = reason
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
        workspace_id: str,
        stage: str,
        command: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkspacePipelineStageRunModel:
        model = WorkspacePipelineStageRunModel(
            id=str(uuid.uuid4()),
            run_id=run_id,
            workspace_id=workspace_id,
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
        stage_run: WorkspacePipelineStageRunModel,
        *,
        status: str,
        exit_code: int | None,
        stdout_preview: str | None,
        stderr_preview: str | None,
        log_ref: str | None = None,
        artifact_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkspacePipelineStageRunModel:
        completed_at = datetime.now(UTC)
        started_at = stage_run.started_at or completed_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        stage_run.status = status
        stage_run.exit_code = exit_code
        stage_run.stdout_preview = stdout_preview
        stage_run.stderr_preview = stderr_preview
        stage_run.log_ref = log_ref
        stage_run.artifact_refs_json = list(artifact_refs or [])
        stage_run.completed_at = completed_at
        stage_run.duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
        stage_run.updated_at = completed_at
        if metadata:
            stage_run.metadata_json = {**dict(stage_run.metadata_json or {}), **metadata}
        await self._db.flush()
        return stage_run

    async def latest_runs(
        self,
        *,
        plan_id: str,
        limit: int = 5,
    ) -> list[WorkspacePipelineRunModel]:
        result = await self._db.execute(
            refresh_select_statement(
                select(WorkspacePipelineRunModel)
                .where(WorkspacePipelineRunModel.plan_id == plan_id)
                .order_by(
                    WorkspacePipelineRunModel.created_at.desc(),
                    WorkspacePipelineRunModel.id.desc(),
                )
                .limit(max(0, limit))
            )
        )
        return list(result.scalars().all())

    async def latest_run_for_node(
        self,
        *,
        plan_id: str,
        node_id: str,
        attempt_id: str | None = None,
    ) -> WorkspacePipelineRunModel | None:
        stmt = (
            select(WorkspacePipelineRunModel)
            .where(WorkspacePipelineRunModel.plan_id == plan_id)
            .where(WorkspacePipelineRunModel.node_id == node_id)
        )
        if attempt_id:
            stmt = stmt.where(WorkspacePipelineRunModel.attempt_id == attempt_id)
        result = await self._db.execute(
            refresh_select_statement(
                stmt.order_by(
                    WorkspacePipelineRunModel.created_at.desc(),
                    WorkspacePipelineRunModel.id.desc(),
                ).limit(1)
            )
        )
        return result.scalar_one_or_none()

    async def stages_for_runs(
        self,
        run_ids: list[str],
    ) -> list[WorkspacePipelineStageRunModel]:
        if not run_ids:
            return []
        result = await self._db.execute(
            refresh_select_statement(
                select(WorkspacePipelineStageRunModel)
                .where(WorkspacePipelineStageRunModel.run_id.in_(run_ids))
                .order_by(
                    WorkspacePipelineStageRunModel.created_at.asc(),
                    WorkspacePipelineStageRunModel.id.asc(),
                )
            )
        )
        return list(result.scalars().all())

    async def upsert_deployment(  # noqa: PLR0913
        self,
        *,
        workspace_id: str,
        plan_id: str | None,
        node_id: str | None,
        pipeline_run_id: str | None,
        provider: str,
        status: str,
        command: str | None,
        pid: int | None = None,
        process_group_id: int | None = None,
        port: int | None = None,
        preview_url: str | None = None,
        health_url: str | None = None,
        service_id: str | None = None,
        service_name: str | None = None,
        service_url: str | None = None,
        ws_preview_url: str | None = None,
        required: bool = True,
        rollback_ref: str | None = None,
        log_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkspaceDeploymentModel:
        model = await self._deployment_for_service(
            plan_id=plan_id,
            node_id=node_id,
            service_id=service_id,
        )
        if model is None:
            model = WorkspaceDeploymentModel(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                plan_id=plan_id,
                node_id=node_id,
            )
            self._db.add(model)
        model.pipeline_run_id = pipeline_run_id
        model.provider = provider
        model.status = status
        model.command = command
        model.pid = pid
        model.process_group_id = process_group_id
        model.port = port
        model.preview_url = preview_url
        model.health_url = health_url
        model.service_id = service_id
        model.service_name = service_name
        model.service_url = service_url
        model.ws_preview_url = ws_preview_url
        model.required = bool(required)
        model.rollback_ref = rollback_ref
        model.log_ref = log_ref
        if status == "healthy":
            model.last_healthy_at = datetime.now(UTC)
        model.updated_at = datetime.now(UTC)
        model.metadata_json = {**dict(model.metadata_json or {}), **dict(metadata or {})}
        await self._db.flush()
        return model

    async def _deployment_for_service(
        self,
        *,
        plan_id: str | None,
        node_id: str | None,
        service_id: str | None,
    ) -> WorkspaceDeploymentModel | None:
        if plan_id is None or node_id is None:
            return None
        stmt = (
            select(WorkspaceDeploymentModel)
            .where(WorkspaceDeploymentModel.plan_id == plan_id)
            .where(WorkspaceDeploymentModel.node_id == node_id)
        )
        if service_id is None:
            stmt = stmt.where(WorkspaceDeploymentModel.service_id.is_(None))
        else:
            stmt = stmt.where(WorkspaceDeploymentModel.service_id == service_id)
        result = await self._db.execute(
            refresh_select_statement(
                stmt.order_by(
                    WorkspaceDeploymentModel.created_at.desc(),
                    WorkspaceDeploymentModel.id.desc(),
                ).limit(1)
            )
        )
        return result.scalar_one_or_none()

    async def latest_deployments(
        self,
        *,
        plan_id: str,
        limit: int = 10,
    ) -> list[WorkspaceDeploymentModel]:
        result = await self._db.execute(
            refresh_select_statement(
                select(WorkspaceDeploymentModel)
                .where(WorkspaceDeploymentModel.plan_id == plan_id)
                .order_by(
                    WorkspaceDeploymentModel.updated_at.desc().nullslast(),
                    WorkspaceDeploymentModel.created_at.desc(),
                    WorkspaceDeploymentModel.id.desc(),
                )
                .limit(max(0, limit))
            )
        )
        return list(result.scalars().all())


__all__ = ["SqlWorkspacePipelineRepository"]
