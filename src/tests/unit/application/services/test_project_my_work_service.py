from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.services.project_my_work_service import (
    HITLRequestAuthority,
    ProjectMyWorkAccessDeniedError,
    ProjectMyWorkService,
    WorkspaceAttemptAuthority,
)

NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)


class FakeProjectMyWorkReader:
    def __init__(
        self,
        *,
        has_access: bool = True,
        attempts: list[WorkspaceAttemptAuthority] | None = None,
        hitl_requests: list[HITLRequestAuthority] | None = None,
    ) -> None:
        self.has_access = has_access
        self.attempts = attempts or []
        self.hitl_requests = hitl_requests or []

    async def has_project_access(self, *, project_id: str, user_id: str) -> bool:
        return self.has_access

    async def list_latest_workspace_attempts(
        self,
        *,
        project_id: str,
        user_id: str,
    ) -> list[WorkspaceAttemptAuthority]:
        return self.attempts

    async def list_pending_hitl_requests(
        self,
        *,
        project_id: str,
        user_id: str,
        now: datetime,
    ) -> list[HITLRequestAuthority]:
        return self.hitl_requests


def attempt(
    authority_id: str,
    conversation_id: str,
    status: str,
    *,
    agent_config: dict[str, object] | None = None,
    workspace_metadata: dict[str, object] | None = None,
    updated_at: datetime | None = None,
) -> WorkspaceAttemptAuthority:
    return WorkspaceAttemptAuthority(
        id=authority_id,
        conversation_id=conversation_id,
        workspace_id="workspace-1",
        project_id="project-1",
        title=f"Task {authority_id}",
        status=status,
        attempt_number=2,
        conversation_agent_config=agent_config,
        workspace_metadata=workspace_metadata,
        created_at=NOW - timedelta(minutes=2),
        updated_at=updated_at,
    )


def hitl(
    authority_id: str,
    conversation_id: str,
    request_type: str,
    *,
    expires_at: datetime,
) -> HITLRequestAuthority:
    return HITLRequestAuthority(
        id=authority_id,
        request_type=request_type,
        conversation_id=conversation_id,
        workspace_id="workspace-1",
        project_id="project-1",
        title=f"Session {conversation_id}",
        conversation_agent_config={"capability_mode": "work"},
        request_metadata=None,
        workspace_metadata=None,
        created_at=NOW - timedelta(minutes=1),
        expires_at=expires_at,
    )


async def test_maps_only_supported_latest_attempt_authorities() -> None:
    reader = FakeProjectMyWorkReader(
        attempts=[
            attempt(
                "running-attempt",
                "conversation-running",
                "running",
                agent_config={"capability_mode": "unknown"},
                workspace_metadata={"capability_mode": "code"},
            ),
            attempt(
                "adjudication-attempt", "conversation-adjudication", "awaiting_leader_adjudication"
            ),
            attempt("blocked-attempt", "conversation-blocked", "blocked"),
            attempt("accepted-attempt", "conversation-accepted", "accepted"),
            attempt("unknown-attempt", "conversation-unknown", "custom"),
        ]
    )

    response = await ProjectMyWorkService(reader).list_for_project(
        project_id="project-1",
        user_id="user-1",
        now=NOW,
    )

    assert [item.authority_id for item in response.items] == [
        "running-attempt",
        "blocked-attempt",
        "adjudication-attempt",
    ]
    running, blocked, adjudication = response.items
    assert (running.group, running.status, running.required_action) == (
        "running",
        "running",
        "observe",
    )
    assert running.capability_mode == "code"
    assert running.id == "workspace_attempt:running-attempt"
    assert running.attempt_number == 2
    assert (
        running.run_id,
        running.revision,
        running.permission_profile,
        running.environment,
        running.last_heartbeat_at,
    ) == (None, None, None, None, None)
    assert (blocked.group, blocked.status, blocked.required_action) == (
        "needs_input",
        "failed",
        "inspect_failure",
    )
    assert (adjudication.group, adjudication.status, adjudication.required_action) == (
        "running",
        "running",
        "observe",
    )


async def test_pending_hitl_precedes_attempt_and_expired_request_does_not() -> None:
    reader = FakeProjectMyWorkReader(
        attempts=[
            attempt("attempt-overridden", "conversation-1", "running"),
            attempt("attempt-visible", "conversation-2", "pending"),
            attempt("attempt-unsupported-hitl", "conversation-4", "running"),
        ],
        hitl_requests=[
            hitl(
                "permission-active",
                "conversation-1",
                "permission",
                expires_at=NOW + timedelta(minutes=1),
            ),
            hitl(
                "permission-expired",
                "conversation-2",
                "permission",
                expires_at=NOW,
            ),
            hitl(
                "decision-active",
                "conversation-3",
                "decision",
                expires_at=NOW + timedelta(minutes=2),
            ),
            hitl(
                "unsupported-active",
                "conversation-4",
                "custom_request",
                expires_at=NOW + timedelta(minutes=2),
            ),
        ],
    )

    response = await ProjectMyWorkService(reader).list_for_project(
        project_id="project-1",
        user_id="user-1",
        now=NOW,
    )

    items = {item.authority_id: item for item in response.items}
    assert set(items) == {
        "permission-active",
        "attempt-visible",
        "attempt-unsupported-hitl",
        "decision-active",
    }
    permission = items["permission-active"]
    assert permission.id == "hitl_request:permission-active"
    assert (permission.group, permission.status, permission.required_action) == (
        "needs_approval",
        "needs_approval",
        "review_approval",
    )
    decision = items["decision-active"]
    assert (decision.group, decision.status, decision.required_action) == (
        "needs_input",
        "needs_input",
        "provide_input",
    )
    assert permission.attempt_number is None


async def test_denies_incomplete_project_scope() -> None:
    service = ProjectMyWorkService(FakeProjectMyWorkReader(has_access=False))

    with pytest.raises(ProjectMyWorkAccessDeniedError):
        await service.list_for_project(project_id="project-1", user_id="user-1", now=NOW)


async def test_capability_mode_does_not_infer_from_workspace_use_case() -> None:
    reader = FakeProjectMyWorkReader(
        attempts=[
            attempt(
                "unclassified-attempt",
                "conversation-unclassified",
                "running",
                workspace_metadata={
                    "workspace_use_case": "programming",
                    "workspace_type": "software_development",
                },
            )
        ]
    )

    response = await ProjectMyWorkService(reader).list_for_project(
        project_id="project-1",
        user_id="user-1",
        now=NOW,
    )

    assert response.items[0].capability_mode is None
