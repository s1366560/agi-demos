"""Closed-loop acceptance for SubAgent run logs (trace) with populated runs."""

from __future__ import annotations

import pytest
import pytest_asyncio

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.plugins.v2.subagent_run_registry_service import (
    SUBAGENT_RUN_REGISTRY_SERVICE_V2,
)

pytestmark = pytest.mark.integration

QA_TRACE_ID = "qa-governance-trace-0001"


@pytest_asyncio.fixture(loop_scope="function")
async def qa_conversations(test_db, qa_scope, test_user):
    """Two QA conversations plus a completed and a failed run in the registry."""
    conversations = []
    for index in (1, 2):
        conversation = Conversation(
            id=f"qa-governance-conversation-{index}",
            project_id=qa_scope.project_id,
            tenant_id=qa_scope.tenant_id,
            user_id=test_user.id,
            title=f"QA Governance Conversation {index}",
        )
        test_db.add(conversation)
        conversations.append(conversation)
    await test_db.commit()
    return conversations


@pytest_asyncio.fixture(loop_scope="function")
async def qa_runs(governance_runtime, qa_conversations):
    """Register a completed and a failed run through the production registry."""
    conversation_id = qa_conversations[0].id
    async with await governance_runtime.acquire() as generation:
        registry = generation.resolve(
            SUBAGENT_RUN_REGISTRY_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        completed = registry.create_run(
            conversation_id,
            "qa-governance-researcher",
            "Summarize the QA governance samples",
            run_id="qa-governance-run-completed",
        )
        registry.set_trace_context(conversation_id, completed.run_id, QA_TRACE_ID)
        registry.mark_running(conversation_id, completed.run_id)
        registry.mark_completed(
            conversation_id,
            completed.run_id,
            summary="QA governance run finished with 2 findings",
            tokens_used=1234,
            execution_time_ms=4200,
        )

        failed = registry.create_run(
            conversation_id,
            "qa-governance-executor",
            "Apply the QA governance migration",
            run_id="qa-governance-run-failed",
        )
        registry.set_trace_context(conversation_id, failed.run_id, QA_TRACE_ID)
        registry.mark_running(conversation_id, failed.run_id)
        registry.mark_failed(
            conversation_id,
            failed.run_id,
            error="QA governance sample failure: simulated tool timeout",
            execution_time_ms=1800,
        )
    return {"conversation_id": conversation_id, "completed": completed, "failed": failed}


async def test_project_run_list_returns_populated_runs(
    authenticated_async_client, governance_runtime, qa_scope, qa_runs
) -> None:
    response = await authenticated_async_client.get(
        f"/api/v1/agent/trace/runs/project/{qa_scope.project_id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == qa_scope.project_id
    runs = {run["run_id"]: run for run in payload["runs"]}
    assert {qa_runs["completed"].run_id, qa_runs["failed"].run_id} <= set(runs)
    assert runs[qa_runs["completed"].run_id]["status"] == "completed"
    assert runs[qa_runs["failed"].run_id]["status"] == "failed"


async def test_project_run_list_status_filter(
    authenticated_async_client, governance_runtime, qa_scope, qa_runs
) -> None:
    response = await authenticated_async_client.get(
        f"/api/v1/agent/trace/runs/project/{qa_scope.project_id}",
        params={"status": "failed"},
    )

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert [run["run_id"] for run in runs] == [qa_runs["failed"].run_id]


async def test_conversation_run_list_and_detail_return_populated_fields(
    authenticated_async_client, governance_runtime, qa_runs
) -> None:
    conversation_id = qa_runs["conversation_id"]
    listing = await authenticated_async_client.get(f"/api/v1/agent/trace/runs/{conversation_id}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2

    completed = await authenticated_async_client.get(
        f"/api/v1/agent/trace/runs/{conversation_id}/{qa_runs['completed'].run_id}"
    )
    assert completed.status_code == 200
    completed_run = completed.json()
    assert completed_run["status"] == "completed"
    assert completed_run["summary"] == "QA governance run finished with 2 findings"
    assert completed_run["tokens_used"] == 1234
    assert completed_run["execution_time_ms"] == 4200
    assert completed_run["trace_id"] == QA_TRACE_ID

    failed = await authenticated_async_client.get(
        f"/api/v1/agent/trace/runs/{conversation_id}/{qa_runs['failed'].run_id}"
    )
    assert failed.status_code == 200
    failed_run = failed.json()
    assert failed_run["status"] == "failed"
    assert failed_run["error"] == "QA governance sample failure: simulated tool timeout"


async def test_trace_chain_groups_seeded_runs(
    authenticated_async_client, governance_runtime, qa_runs
) -> None:
    response = await authenticated_async_client.get(
        f"/api/v1/agent/trace/runs/{qa_runs['conversation_id']}/trace/{QA_TRACE_ID}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_id"] == QA_TRACE_ID
    assert payload["total"] == 2
    assert {run["run_id"] for run in payload["runs"]} == {
        qa_runs["completed"].run_id,
        qa_runs["failed"].run_id,
    }


async def test_member_without_own_conversations_sees_no_project_runs(
    viewer_client, governance_runtime, viewer_user, qa_scope, qa_runs
) -> None:
    response = await viewer_client.get(f"/api/v1/agent/trace/runs/project/{qa_scope.project_id}")

    assert response.status_code == 200
    assert response.json()["runs"] == []


async def test_member_cannot_read_other_users_conversation_runs(
    viewer_client, governance_runtime, viewer_user, qa_runs
) -> None:
    response = await viewer_client.get(f"/api/v1/agent/trace/runs/{qa_runs['conversation_id']}")

    assert response.status_code == 404


async def test_outsider_is_rejected_on_project_runs(
    outsider_client, governance_runtime, outsider_user, qa_scope, qa_runs
) -> None:
    response = await outsider_client.get(f"/api/v1/agent/trace/runs/project/{qa_scope.project_id}")

    assert response.status_code == 403
