"""Unit tests for ordinary-chat CI/CD pipeline execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.cicd_pipeline_service import (
    CicdPipelineError,
    CicdPipelineRunRequest,
    CicdPipelineService,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    CicdPipelineRunModel,
    CicdPipelineStageRunModel,
    Conversation as ConversationModel,
    PluginConfigModel,
    WorkspaceMemberModel,
    WorkspaceModel,
    WorkspacePipelineRunModel,
)
from src.infrastructure.agent.core.react_agent_tool_policy import (
    filter_non_workspace_conversation_tools,
)
from src.infrastructure.agent.workspace_plan.pipeline import (
    PipelineRunResult,
    PipelineStageResult,
)
from src.infrastructure.agent.workspace_plan.pipeline_provider_registry import (
    PipelineProviderUnavailableError,
)

pytestmark = pytest.mark.unit

TENANT_ID = "550e8400-e29b-41d4-a716-446655440001"
PROJECT_ID = "550e8400-e29b-41d4-a716-446655440002"
USER_ID = "550e8400-e29b-41d4-a716-446655440000"


class _FakeDroneProvider:
    def __init__(self, result: PipelineRunResult) -> None:
        self._result = result
        self.contracts: list[Any] = []

    async def run(self, contract: Any) -> PipelineRunResult:
        self.contracts.append(contract)
        return self._result


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


def _success_result() -> PipelineRunResult:
    return PipelineRunResult(
        status="success",
        reason="Drone build passed",
        stage_results=(
            PipelineStageResult(
                stage="drone",
                status="success",
                command="drone:api",
                exit_code=0,
                stdout_preview="ok",
            ),
        ),
        evidence_refs=("ci_pipeline:passed",),
        external_id="42",
        external_url="https://drone.example/ws/repo/42",
    )


def _delivery(
    *,
    repo: str = "owner/repo",
    token_env: str = "DRONE_TOKEN",
) -> dict[str, Any]:
    return {
        "provider": "drone",
        "drone": {
            "repo": repo,
            "server_url": "https://drone.example",
            "token_env": token_env,
            "poll_interval_seconds": 1,
        },
    }


async def _seed_workspace(
    db_session: AsyncSession,
    *,
    workspace_id: str,
    name: str,
    delivery: Mapping[str, Any] | None = None,
) -> None:
    db_session.add(
        WorkspaceModel(
            id=workspace_id,
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name=name,
            description="",
            created_by=USER_ID,
            is_archived=False,
            metadata_json={"delivery_cicd": dict(delivery or _delivery())},
        )
    )
    db_session.add(
        WorkspaceMemberModel(
            id=f"member-{workspace_id}",
            workspace_id=workspace_id,
            user_id=USER_ID,
            role="owner",
            invited_by=USER_ID,
        )
    )
    await db_session.flush()


async def _seed_conversation(
    db_session: AsyncSession,
    *,
    conversation_id: str = "conv-cicd-1",
    workspace_id: str | None = None,
) -> None:
    db_session.add(
        ConversationModel(
            id=conversation_id,
            project_id=PROJECT_ID,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            title="CI/CD chat",
            status="active",
            agent_config={},
            meta={},
            message_count=0,
            current_mode="build",
            merge_strategy="result_only",
            participant_agents=[],
            workspace_id=workspace_id,
        )
    )
    await db_session.flush()


def _request(
    *,
    conversation_id: str = "conv-cicd-1",
    repository: str | None = "owner/repo",
) -> CicdPipelineRunRequest:
    return CicdPipelineRunRequest(
        conversation_id=conversation_id,
        project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        repository=repository,
        reason="run ci",
    )


def test_cicd_tool_is_visible_in_non_workspace_conversations() -> None:
    tools = [_Tool("cicd_run_pipeline"), _Tool("workspace_report_complete")]

    filtered = filter_non_workspace_conversation_tools(
        tools,  # type: ignore[arg-type]
        is_workspace_conversation=False,
    )

    assert [tool.name for tool in filtered] == ["cicd_run_pipeline"]


async def test_run_pipeline_runs_repository_without_workspace(
    db_session: AsyncSession,
    test_project_db: Any,
) -> None:
    _ = test_project_db
    await _seed_conversation(db_session)
    service = CicdPipelineService(
        db_session,
        provider_factory=lambda: _FakeDroneProvider(_success_result()),
    )

    summary = await service.run_pipeline(_request())

    assert summary.repository == "owner/repo"
    assert summary.status == "success"
    assert "ci_pipeline:passed" in summary.evidence_refs
    runs = (
        (
            await db_session.execute(
                select(CicdPipelineRunModel).where(CicdPipelineRunModel.repository == "owner/repo")
            )
        )
        .scalars()
        .all()
    )
    stages = (
        (
            await db_session.execute(
                select(CicdPipelineStageRunModel).where(
                    CicdPipelineStageRunModel.run_id == summary.run_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(runs) == 1
    assert len(stages) == 1
    assert runs[0].conversation_id == "conv-cicd-1"


async def test_run_pipeline_ignores_multiple_visible_drone_workspaces_when_repo_is_provided(
    db_session: AsyncSession,
    test_project_db: Any,
) -> None:
    _ = test_project_db
    await _seed_workspace(db_session, workspace_id="ws-cicd-1", name="Drone One")
    await _seed_workspace(db_session, workspace_id="ws-cicd-2", name="Drone Two")
    await _seed_conversation(db_session)
    provider = _FakeDroneProvider(_success_result())
    service = CicdPipelineService(db_session, provider_factory=lambda: provider)

    summary = await service.run_pipeline(_request(repository="octo/service"))

    assert summary.status == "success"
    assert summary.repository == "octo/service"
    assert provider.contracts[0].provider_config["repo"] == "octo/service"
    workspace_runs = (await db_session.execute(select(WorkspacePipelineRunModel))).scalars().all()
    assert workspace_runs == []


async def test_run_pipeline_requires_repository_before_workspace_selection(
    db_session: AsyncSession,
    test_project_db: Any,
) -> None:
    _ = test_project_db
    await _seed_workspace(db_session, workspace_id="ws-cicd-1", name="Drone One")
    await _seed_workspace(db_session, workspace_id="ws-cicd-2", name="Drone Two")
    await _seed_conversation(db_session)
    service = CicdPipelineService(db_session)

    with pytest.raises(CicdPipelineError) as exc_info:
        await service.run_pipeline(_request(repository=None))

    assert exc_info.value.code == "repo_required"


async def test_run_pipeline_failed_provider_result_is_persisted_as_failed_run(
    db_session: AsyncSession,
    test_project_db: Any,
) -> None:
    _ = test_project_db
    await _seed_conversation(db_session)
    result = PipelineRunResult(
        status="failed",
        reason="Drone token is required",
        stage_results=(
            PipelineStageResult(
                stage="drone",
                status="failed",
                command="drone:api",
                exit_code=1,
                stderr_preview="Drone token is required",
            ),
        ),
        evidence_refs=("ci_pipeline:failed",),
    )
    service = CicdPipelineService(db_session, provider_factory=lambda: _FakeDroneProvider(result))

    summary = await service.run_pipeline(_request())

    assert summary.status == "failed"
    assert summary.reason == "Drone token is required"
    run = (
        await db_session.execute(
            select(CicdPipelineRunModel).where(CicdPipelineRunModel.id == summary.run_id)
        )
    ).scalar_one()
    assert run.status == "failed"


async def test_run_pipeline_merges_tenant_plugin_config_before_provider_run(
    db_session: AsyncSession,
    test_project_db: Any,
) -> None:
    _ = test_project_db
    await _seed_conversation(db_session)
    db_session.add(
        PluginConfigModel(
            id=PluginConfigModel.generate_id(),
            tenant_id=TENANT_ID,
            plugin_name="drone-pipeline-plugin",
            config={
                "drone_server_env": "TENANT_DRONE_SERVER",
                "drone_token_env": "TENANT_DRONE_TOKEN",
                "poll_interval_seconds": 3,
                "server_url": "https://tenant.example",
            },
        )
    )
    await db_session.flush()
    provider = _FakeDroneProvider(_success_result())
    service = CicdPipelineService(db_session, provider_factory=lambda: provider)

    summary = await service.run_pipeline(_request())

    assert summary.status == "success"
    assert len(provider.contracts) == 1
    provider_config = provider.contracts[0].provider_config
    assert provider_config["repo"] == "owner/repo"
    assert provider_config["drone_server_env"] == "TENANT_DRONE_SERVER"
    assert provider_config["drone_token_env"] == "TENANT_DRONE_TOKEN"
    assert provider_config["poll_interval_seconds"] == 3


async def test_run_pipeline_reports_disabled_provider_plugin(
    db_session: AsyncSession,
    test_project_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = test_project_db
    await _seed_conversation(db_session)

    async def _missing_provider(_provider: str) -> Any:
        raise PipelineProviderUnavailableError("drone")

    monkeypatch.setattr(
        "src.application.services.cicd_pipeline_service.require_pipeline_provider",
        _missing_provider,
    )
    service = CicdPipelineService(db_session)

    with pytest.raises(CicdPipelineError) as exc_info:
        await service.run_pipeline(_request())

    assert exc_info.value.code == "pipeline_provider_plugin_disabled"
    assert str(exc_info.value) == "pipeline provider plugin is not enabled: drone"
