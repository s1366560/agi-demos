"""Integration tests for the Cloud run-change revert authority endpoint."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, status
from sqlalchemy import select

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    Conversation,
    ProjectSandbox,
    User,
)
from src.infrastructure.plugins.v2.workspace_core_runtime import WorkspaceCoreRuntimeServiceV2

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _run_change_revert_v2_runtime(test_app: FastAPI) -> AsyncIterator[None]:
    """Exercise the revert route through the production V2 runtime host."""

    class ProviderAdapter:
        async def wait_until_idle(self) -> None:
            return None

    async def workspace_core_runtime_factory() -> WorkspaceCoreRuntimeServiceV2:
        marker = cast(Any, object())
        return WorkspaceCoreRuntimeServiceV2(
            settings=marker,
            client=marker,
            authority=test_app.state.workspace_authority,
            context_judge=marker,
            plan_judge=marker,
            autonomy_judge=marker,
            access_verifier=marker,
            event_sink=marker,
            agent_runtime_provider=marker,
            provider_adapter=cast(Any, ProviderAdapter()),
        )

    async def empty_cache_keys(*_args: object, **_kwargs: object) -> AsyncIterator[str]:
        for key in ():
            yield key

    redis_client = AsyncMock()
    redis_client.scan_iter = empty_cache_keys
    redis_client.delete = AsyncMock(return_value=0)
    redis_client.xadd = AsyncMock(return_value="1-1")
    test_app.state.container._redis_client = redis_client
    await initialize_plugin_runtime_v2(
        test_app,
        sandbox_redis_client=redis_client,
        workspace_core_runtime_factory=workspace_core_runtime_factory,
    )
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


class FakeSandboxAdapter:
    """Records bash invocations and answers with a scripted marker."""

    def __init__(self, output: str = "REVERT_OK abc123\n") -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    async def call_tool(
        self,
        sandbox_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "sandbox_id": sandbox_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "timeout": timeout,
            }
        )
        return {"content": [{"text": self.output}], "is_error": False}


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> FakeSandboxAdapter:
    adapter = FakeSandboxAdapter()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.routers.agent.run_change_revert_authority"
        ".get_sandbox_adapter",
        lambda: adapter,
    )
    return adapter


def _change_payload(
    path: str,
    *,
    patch_digest: str = "digest-1",
    hunks: list[dict[str, Any]] | None = None,
    status: str = "modified",
) -> dict[str, Any]:
    hunks = (
        hunks
        if hunks is not None
        else [
            {
                "header": "@@ -1,3 +1,3 @@",
                "old_start": 1,
                "new_start": 1,
                "lines": [
                    {"kind": "context", "old_line": 1, "new_line": 1, "text": "alpha"},
                    {"kind": "deletion", "old_line": 2, "new_line": None, "text": "beta"},
                    {"kind": "addition", "old_line": None, "new_line": 2, "text": "BETA"},
                    {"kind": "context", "old_line": 3, "new_line": 3, "text": "gamma"},
                ],
            }
        ]
    )
    additions = sum(1 for h in hunks for line in h["lines"] if line["kind"] == "addition")
    deletions = sum(1 for h in hunks for line in h["lines"] if line["kind"] == "deletion")
    return {
        "path": path,
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "binary": False,
        "untracked": False,
        "patch_digest": patch_digest,
        "hunks": hunks,
    }


async def _add_reviewed_run(
    test_db,
    test_project_db,
    test_user,
    *,
    run_id: str = "revert-run",
    run_status: str = "ready_review",
    owner_id: str | None = None,
    environment: dict[str, Any] | None = None,
) -> AgentRunAuthorityModel:
    now = datetime.now(UTC)
    conversation = Conversation(
        id=f"{run_id}-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=owner_id or test_user.id,
        title="Revert authority",
        status="active",
        agent_config={},
        message_count=0,
    )
    run = AgentRunAuthorityModel(
        id=run_id,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=conversation.id,
        run_kind="chat",
        plan_run_id=None,
        plan_version_id=None,
        idempotency_key=f"{run_id}-start",
        message_id=f"{run_id}-message",
        request_message="Change files",
        status=run_status,
        revision=3,
        permission_profile="workspace_write",
        authorization_snapshot={
            "environment": environment
            or {
                "id": "revert-environment",
                "kind": "sandbox",
                "workspace_path": "/workspace",
                "repository_root": "/repo",
                "branch": "main",
                "base_commit": "base-1",
            }
        },
        created_at=now - timedelta(minutes=1),
        updated_at=now,
    )
    test_db.add_all([conversation, run])
    await test_db.commit()
    return run


async def _add_change_event(
    test_db,
    run: AgentRunAuthorityModel,
    payloads: list[dict[str, Any]],
    *,
    event_id: str = "revert-change-event",
) -> None:
    test_db.add(
        AgentExecutionEvent(
            id=event_id,
            conversation_id=run.conversation_id,
            message_id=run.message_id,
            event_type="tool_result",
            event_data={"changes": payloads},
            event_time_us=10,
            event_counter=0,
        )
    )
    await test_db.commit()


async def _add_sandbox(
    test_db,
    test_project_db,
    *,
    sandbox_type: str = "cloud",
    sandbox_status: str = "running",
) -> ProjectSandbox:
    sandbox = ProjectSandbox(
        id="revert-project-sandbox",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        sandbox_id="revert-sandbox",
        sandbox_type=sandbox_type,
        status=sandbox_status,
        metadata_json={},
        local_config={},
    )
    test_db.add(sandbox)
    await test_db.commit()
    return sandbox


def _revert_body(
    run: AgentRunAuthorityModel,
    digest: str,
    selectors: list[dict[str, Any]],
    *,
    key: str = "revert-key-1",
) -> dict[str, Any]:
    return {
        "expected_run_revision": run.revision,
        "scope": "run",
        "snapshot_digest": digest,
        "idempotency_key": key,
        "selectors": selectors,
    }


async def _current_digest(authenticated_async_client, run: AgentRunAuthorityModel) -> str:
    response = await authenticated_async_client.get(
        f"/api/v1/agent/runs/{run.id}/changes",
        params={"scope": "run", "expected_revision": run.revision},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ready"
    return response.json()["snapshot_revision"]


async def test_revert_reverse_applies_recorded_file_and_replays_honestly(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    fake_adapter: FakeSandboxAdapter,
) -> None:
    run = await _add_reviewed_run(test_db, test_project_db, test_user)
    await _add_change_event(test_db, run, [_change_payload("src/a.py")])
    await _add_sandbox(test_db, test_project_db)
    digest = await _current_digest(authenticated_async_client, run)

    response = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, digest, [{"path": "src/a.py"}]),
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["accepted"] is True
    assert body["created"] is True
    assert body["head_commit"] == "abc123"
    assert body["snapshot_digest"] != digest
    assert body["reverted"] == [
        {
            "path": "src/a.py",
            "patch_digest": "digest-1",
            "hunk_indices": None,
            "deleted_file": False,
        }
    ]
    assert len(fake_adapter.calls) == 1
    command = fake_adapter.calls[0]["arguments"]["command"]
    assert "git apply --check --reverse" in command
    assert "cd '/repo'" in command

    refreshed = await authenticated_async_client.get(
        f"/api/v1/agent/runs/{run.id}/changes",
        params={"scope": "run", "expected_revision": run.revision},
    )
    assert refreshed.json()["snapshot_revision"] == body["snapshot_digest"]
    assert refreshed.json()["files"] == []
    assert refreshed.json()["status"] == "unattributed"

    events = (
        (
            await test_db.execute(
                select(AgentExecutionEvent).where(
                    AgentExecutionEvent.event_type == "change_reverted"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].event_data["reverted"] == [
        {"path": "src/a.py", "patch_digest": "digest-1", "hunk_indices": None}
    ]


async def test_revert_selected_hunk_keeps_remaining_hunks(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    fake_adapter: FakeSandboxAdapter,
) -> None:
    run = await _add_reviewed_run(test_db, test_project_db, test_user)
    second_hunk = {
        "header": "@@ -10,1 +10,2 @@",
        "old_start": 10,
        "new_start": 10,
        "lines": [
            {"kind": "context", "old_line": 10, "new_line": 10, "text": "ten"},
            {"kind": "addition", "old_line": None, "new_line": 11, "text": "eleven"},
        ],
    }
    await _add_change_event(
        test_db,
        run,
        [_change_payload("src/a.py", hunks=[_change_payload("x")["hunks"][0], second_hunk])],
    )
    await _add_sandbox(test_db, test_project_db)
    digest = await _current_digest(authenticated_async_client, run)

    response = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, digest, [{"path": "src/a.py", "hunk_indices": [1]}]),
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["reverted"][0]["hunk_indices"] == [1]
    command = fake_adapter.calls[0]["arguments"]["command"]
    assert "eleven" not in command  # content rides base64, never plaintext shell
    refreshed = await authenticated_async_client.get(
        f"/api/v1/agent/runs/{run.id}/changes",
        params={"scope": "run", "expected_revision": run.revision},
    )
    files = refreshed.json()["files"]
    assert len(files) == 1
    assert [hunk["old_start"] for hunk in files[0]["hunks"]] == [1]
    assert refreshed.json()["snapshot_revision"] == body["snapshot_digest"]


async def test_revert_rejects_stale_snapshot_digest(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    fake_adapter: FakeSandboxAdapter,
) -> None:
    run = await _add_reviewed_run(test_db, test_project_db, test_user)
    await _add_change_event(test_db, run, [_change_payload("src/a.py")])
    await _add_sandbox(test_db, test_project_db)

    response = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, "stale-digest", [{"path": "src/a.py"}]),
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["reason_code"] == "snapshot_digest_mismatch"
    assert response.json()["accepted"] is False
    assert fake_adapter.calls == []


async def test_revert_rejects_unknown_selector(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    fake_adapter: FakeSandboxAdapter,
) -> None:
    run = await _add_reviewed_run(test_db, test_project_db, test_user)
    await _add_change_event(test_db, run, [_change_payload("src/a.py")])
    await _add_sandbox(test_db, test_project_db)
    digest = await _current_digest(authenticated_async_client, run)

    unknown_file = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, digest, [{"path": "src/missing.py"}]),
    )
    unknown_hunk = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, digest, [{"path": "src/a.py", "hunk_indices": [7]}]),
    )

    assert unknown_file.status_code == status.HTTP_409_CONFLICT
    assert unknown_file.json()["reason_code"] == "unknown_change_selector"
    assert unknown_hunk.status_code == status.HTTP_409_CONFLICT
    assert unknown_hunk.json()["reason_code"] == "unknown_change_selector"
    assert fake_adapter.calls == []


async def test_revert_idempotent_replay_and_conflict(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    fake_adapter: FakeSandboxAdapter,
) -> None:
    run = await _add_reviewed_run(test_db, test_project_db, test_user)
    await _add_change_event(
        test_db, run, [_change_payload("src/a.py"), _change_payload("src/b.py", patch_digest="d2")]
    )
    await _add_sandbox(test_db, test_project_db)
    digest = await _current_digest(authenticated_async_client, run)
    body = _revert_body(run, digest, [{"path": "src/a.py"}])

    first = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert", json=body
    )
    replay = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert", json=body
    )
    conflict = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, digest, [{"path": "src/b.py"}], key="revert-key-1"),
    )

    assert first.status_code == status.HTTP_200_OK
    assert first.json()["created"] is True
    assert replay.status_code == status.HTTP_200_OK
    assert replay.json()["created"] is False
    assert replay.json()["snapshot_digest"] == first.json()["snapshot_digest"]
    assert conflict.status_code == status.HTTP_409_CONFLICT
    assert len(fake_adapter.calls) == 1


async def test_revert_denies_foreign_run(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    fake_adapter: FakeSandboxAdapter,
) -> None:
    test_db.add(User(id="revert-other-user", email="other@example.test", hashed_password="x"))
    await test_db.commit()
    run = await _add_reviewed_run(
        test_db,
        test_project_db,
        test_user,
        run_id="revert-foreign-run",
        owner_id="revert-other-user",
    )

    response = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, "any", [{"path": "src/a.py"}]),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert fake_adapter.calls == []


async def test_revert_fails_closed_without_running_cloud_sandbox(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    fake_adapter: FakeSandboxAdapter,
) -> None:
    run = await _add_reviewed_run(test_db, test_project_db, test_user)
    await _add_change_event(test_db, run, [_change_payload("src/a.py")])
    digest = await _current_digest(authenticated_async_client, run)

    missing = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, digest, [{"path": "src/a.py"}]),
    )
    assert missing.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert missing.json()["reason_code"] == "sandbox_write_unavailable"
    assert missing.json()["retryable"] is True

    await _add_sandbox(test_db, test_project_db, sandbox_type="local")
    local = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, digest, [{"path": "src/a.py"}]),
    )
    assert local.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert local.json()["reason_code"] == "sandbox_write_unavailable"

    assert fake_adapter.calls == []


async def test_revert_patch_conflict_writes_nothing(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FakeSandboxAdapter(output="git apply error\nREVERT_CHECK_FAILED\n")
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.routers.agent.run_change_revert_authority"
        ".get_sandbox_adapter",
        lambda: adapter,
    )
    run = await _add_reviewed_run(test_db, test_project_db, test_user)
    await _add_change_event(test_db, run, [_change_payload("src/a.py")])
    await _add_sandbox(test_db, test_project_db)
    digest = await _current_digest(authenticated_async_client, run)

    response = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/changes/revert",
        json=_revert_body(run, digest, [{"path": "src/a.py"}]),
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["reason_code"] == "revert_patch_conflict"
    assert len(adapter.calls) == 1
    remaining = (
        (
            await test_db.execute(
                select(AgentExecutionEvent).where(
                    AgentExecutionEvent.event_type == "change_reverted"
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []
    refreshed = await authenticated_async_client.get(
        f"/api/v1/agent/runs/{run.id}/changes",
        params={"scope": "run", "expected_revision": run.revision},
    )
    assert refreshed.json()["snapshot_revision"] == digest
    assert len(refreshed.json()["files"]) == 1


async def test_revert_rejects_active_run_and_revision_drift(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    fake_adapter: FakeSandboxAdapter,
) -> None:
    active = await _add_reviewed_run(
        test_db, test_project_db, test_user, run_id="revert-active-run", run_status="running"
    )
    await _add_change_event(test_db, active, [_change_payload("src/a.py")], event_id="e-active")
    await _add_sandbox(test_db, test_project_db)
    digest = await _current_digest(authenticated_async_client, active)

    active_response = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{active.id}/changes/revert",
        json=_revert_body(active, digest, [{"path": "src/a.py"}]),
    )
    assert active_response.status_code == status.HTTP_409_CONFLICT
    assert active_response.json()["reason_code"] == "run_active"

    drift = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{active.id}/changes/revert",
        json={
            **_revert_body(active, digest, [{"path": "src/a.py"}], key="revert-key-2"),
            "expected_run_revision": active.revision + 1,
        },
    )
    assert drift.status_code == status.HTTP_409_CONFLICT
    assert drift.json()["reason_code"] == "run_revision_conflict"
    assert fake_adapter.calls == []
