from datetime import UTC, datetime

from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskStatus,
)
from src.infrastructure.adapters.primary.web.routers.workspace_tasks import _to_response


def test_to_response_projects_current_attempt_fields() -> None:
    task = WorkspaceTask(
        id="task-1",
        workspace_id="ws-1",
        title="Run attempt",
        created_by="user-1",
        status=WorkspaceTaskStatus.IN_PROGRESS,
        metadata={
            "current_attempt_id": "attempt-1",
            "current_attempt_number": 2,
            "current_attempt_conversation_id": "conv-1",
            "current_attempt_worker_binding_id": "binding-1",
            "current_attempt_worker_agent_id": "agent-1",
            "last_attempt_status": "rejected",
            "pending_leader_adjudication": True,
        },
        created_at=datetime.now(UTC),
    )

    response = _to_response(task)

    assert response.current_attempt_id == "attempt-1"
    assert response.current_attempt_number == 2
    assert response.current_attempt_conversation_id == "conv-1"
    assert response.current_attempt_worker_binding_id == "binding-1"
    assert response.current_attempt_worker_agent_id == "agent-1"
    assert response.last_attempt_status == "rejected"
    assert response.pending_leader_adjudication is True
