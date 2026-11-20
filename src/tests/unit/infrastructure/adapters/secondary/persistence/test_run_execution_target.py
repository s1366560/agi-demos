"""Run execution target persistence, projection, and conversation filtering."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.execution.run_execution_placement import (
    ExecutionTarget,
    InvalidExecutionTarget,
    RunExecutionPlacement,
    parse_execution_target,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation as ConversationModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ConversationExecutionIndex,
    ensure_chat_run_authority,
    latest_execution_placements,
    stamp_event_envelope,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_session_projection_reader import (
    SqlConversationSessionProjectionReader,
)
from src.infrastructure.plugins.v2.conversation_collection_repository import (
    SqlConversationCollectionRepositoryV2,
)

pytestmark = pytest.mark.unit


def test_parse_execution_target_defaults_to_cloud_and_rejects_other_tokens() -> None:
    assert parse_execution_target(None) is ExecutionTarget.CLOUD
    assert parse_execution_target("local") is ExecutionTarget.LOCAL
    with pytest.raises(InvalidExecutionTarget):
        parse_execution_target("worktree")


def test_projection_reads_columns_without_replacing_worktree_environment() -> None:
    row = SimpleNamespace(
        id="run-1",
        conversation_id="conversation-1",
        project_id="project-1",
        plan_version_id="plan-version-1",
        idempotency_key="approve-1",
        message_id="message-1",
        request_message="Implement the approved plan",
        status="running",
        revision=3,
        permission_profile="full_access",
        authorization_snapshot={
            "environment": {
                "id": "sandbox-1",
                "kind": "worktree",
                "label": "sandbox-1",
                "workspace_path": "/workspace",
                "repository_root": None,
                "branch": None,
                "base_commit": None,
                "source_run_id": None,
                "created_at": "2026-11-20T00:00:00+00:00",
            }
        },
        execution_target="local",
        execution_machine_id="machine-1",
        execution_environment_id=None,
        local_root_label="agi-demos",
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
        started_at=None,
        updated_at=datetime(2026, 11, 20, tzinfo=UTC),
        completed_at=None,
        error=None,
    )

    environment = SqlConversationSessionProjectionReader._run_environment(
        row.authorization_snapshot
    )
    assert environment is not None
    assert environment["kind"] == "worktree"
    assert environment["workspace_path"] == "/workspace"
    assert environment["label"] == "sandbox-1"
    assert "agi-demos" not in environment.values()
    assert SqlConversationSessionProjectionReader._execution_target(row.execution_target) == "local"
    assert (
        SqlConversationSessionProjectionReader._optional_execution_text(
            row.local_root_label,
            limit=255,
        )
        == "agi-demos"
    )
    assert (
        SqlConversationSessionProjectionReader._run_environment(
            {
                "environment": {
                    "id": "desktop",
                    "kind": "local",
                    "label": "agi-demos",
                    "workspace_path": "/Users/me/agi-demos",
                    "created_at": "2026-11-20T00:00:00+00:00",
                }
            }
        )
        is None
    )


def test_database_default_backfills_cloud_and_check_rejects_other_values() -> None:
    engine = create_engine("sqlite://")
    AgentRunAuthorityModel.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(AgentRunAuthorityModel).values(
                id="run-cloud",
                tenant_id="tenant-1",
                project_id="project-1",
                conversation_id="conversation-1",
                run_kind="chat",
                idempotency_key="cloud-1",
                message_id="run-cloud",
                request_message="hello",
                status="queued",
                revision=1,
                permission_profile="read_only",
                authorization_snapshot={"source": "test"},
            )
        )
        stored = connection.execute(
            select(AgentRunAuthorityModel.execution_target).where(
                AgentRunAuthorityModel.id == "run-cloud"
            )
        ).scalar_one()
        assert stored == "cloud"
        with pytest.raises(IntegrityError):
            connection.execute(
                insert(AgentRunAuthorityModel).values(
                    id="run-invalid",
                    tenant_id="tenant-1",
                    project_id="project-1",
                    conversation_id="conversation-1",
                    run_kind="chat",
                    idempotency_key="invalid-1",
                    message_id="run-invalid",
                    request_message="hello",
                    status="queued",
                    revision=1,
                    permission_profile="read_only",
                    authorization_snapshot={"source": "test"},
                    execution_target="desktop",
                )
            )


def test_event_envelope_stamps_the_four_fields() -> None:
    index = ConversationExecutionIndex(
        {
            "run-local": RunExecutionPlacement(
                execution_target=ExecutionTarget.LOCAL,
                execution_machine_id="machine-1",
                local_root_label="agi-demos",
            )
        }
    )
    stamped = stamp_event_envelope(
        {"type": "tool_end", "data": {"execution_message_id": "run-local"}},
        index,
    )
    assert stamped["execution_target"] == "local"
    assert stamped["execution_machine_id"] == "machine-1"
    assert stamped["execution_environment_id"] is None
    assert stamped["local_root_label"] == "agi-demos"
    unknown = stamp_event_envelope({"type": "complete", "data": {}}, index, "missing")
    assert unknown["execution_target"] == "cloud"
    assert unknown["local_root_label"] is None


async def test_new_cloud_run_persists_cloud_explicitly() -> None:
    class _Db:
        def __init__(self) -> None:
            self.added: list[AgentRunAuthorityModel] = []

        async def get(self, _model: object, _key: str) -> None:
            return None

        def add(self, row: AgentRunAuthorityModel) -> None:
            self.added.append(row)

        async def commit(self) -> None:
            return None

    db = _Db()
    conversation = SimpleNamespace(
        id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        workspace_id=None,
    )
    row = await ensure_chat_run_authority(
        db,  # type: ignore[arg-type]
        conversation=conversation,  # type: ignore[arg-type]
        run_id="run-1",
        request_message="hello",
        client_message_id=None,
        app_model_context=None,
        permission_snapshot={
            "permission_profile": "read_only",
            "requested_permission_mode": None,
            "effective_permission_mode": "ask",
            "policy": {"permission_mode": "ask"},
        },
    )
    assert row.execution_target == "cloud"
    assert row.execution_machine_id is None
    assert row.local_root_label is None
    assert "execution_target" not in row.authorization_snapshot


async def test_conversation_list_filter_matches_any_run_of_the_requested_target(
    db_session: AsyncSession,
    test_project_db,
    test_user,
) -> None:
    project = test_project_db
    now = datetime.now(UTC)
    cloud_only = ConversationModel(
        id="conversation-cloud",
        project_id=project.id,
        tenant_id=project.tenant_id,
        user_id=test_user.id,
        title="Cloud",
        status="active",
        message_count=0,
        created_at=now,
        current_mode="build",
        participant_agents=[],
    )
    mixed = ConversationModel(
        id="conversation-mixed",
        project_id=project.id,
        tenant_id=project.tenant_id,
        user_id=test_user.id,
        title="Mixed",
        status="active",
        message_count=0,
        created_at=now,
        current_mode="build",
        participant_agents=[],
    )
    db_session.add_all([cloud_only, mixed])
    await db_session.flush()
    db_session.add_all(
        [
            _run(project, cloud_only.id, "run-cloud", "cloud", now),
            _run(project, mixed.id, "run-old-local", "local", now.replace(year=2020)),
            _run(project, mixed.id, "run-new-cloud", "cloud", now),
        ]
    )
    await db_session.flush()
    repository = SqlConversationCollectionRepositoryV2(db_session)

    local_matches = await repository.list_default(
        project_id=project.id,
        tenant_id=project.tenant_id,
        status=None,
        limit=10,
        offset=0,
        execution_target="local",
    )
    cloud_matches = await repository.list_default(
        project_id=project.id,
        tenant_id=project.tenant_id,
        status=None,
        limit=10,
        offset=0,
        execution_target="cloud",
    )
    placements = await latest_execution_placements(
        db_session,
        tenant_id=project.tenant_id,
        project_id=project.id,
        conversation_ids=[cloud_only.id, mixed.id],
    )

    assert [item.id for item in local_matches] == [mixed.id]
    assert {item.id for item in cloud_matches} == {cloud_only.id, mixed.id}
    assert placements[mixed.id].execution_target is ExecutionTarget.CLOUD
    assert placements[cloud_only.id].execution_target is ExecutionTarget.CLOUD


def _run(project, conversation_id: str, run_id: str, target: str, created_at: datetime):
    return AgentRunAuthorityModel(
        id=run_id,
        tenant_id=project.tenant_id,
        project_id=project.id,
        conversation_id=conversation_id,
        run_kind="chat",
        idempotency_key=run_id,
        message_id=run_id,
        request_message=run_id,
        status="completed",
        revision=1,
        permission_profile="read_only",
        authorization_snapshot={
            "environment": {"kind": "worktree", "workspace_path": "/workspace"}
        },
        execution_target=target,
        local_root_label="agi-demos" if target == "local" else None,
        created_at=created_at,
        updated_at=created_at,
    )
