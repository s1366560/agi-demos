"""Fail-closed contracts for the live Workspace Agent E2E gate."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import httpx
import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
GATE_PATH = REPO_ROOT / "scripts/workspace-core/verify-live-agent-e2e.py"


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("workspace_live_agent_e2e", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _environment() -> dict[str, str]:
    return {
        "WORKSPACE_E2E_CORE_BASE_URL": "http://core.test",
        "WORKSPACE_E2E_PROVIDER_WEBHOOK_TOKEN": "provider-secret",
        "WORKSPACE_E2E_CORE_SERVICE_TOKEN": "core-secret",
        "WORKSPACE_E2E_TENANT_ID": "tenant-1",
        "WORKSPACE_E2E_PROJECT_ID": "project-1",
        "WORKSPACE_E2E_WORKSPACE_ID": "workspace-1",
        "WORKSPACE_E2E_USER_ID": "user-1",
        "WORKSPACE_E2E_AGENT_ID": "agent-1",
        "WORKSPACE_E2E_TASK_ID": "task-1",
        "WORKSPACE_E2E_GROUP_ID": "workspace-1",
        "WORKSPACE_E2E_SESSION_ID": "workspace-1",
        "WORKSPACE_E2E_PROVIDER_ID": "memstack-workspace-agent-runtime",
        "WORKSPACE_E2E_ABORT_MESSAGE": "Run a safe long task until cancelled.",
        "WORKSPACE_E2E_API_BASE_URL": "http://api.test",
        "WORKSPACE_E2E_RAY_DASHBOARD_URL": "http://ray.test",
        "WORKSPACE_E2E_RUN_ID": "live-contract",
    }


def _terminal(correlation_id: str, *, aborted: bool = False) -> dict[str, Any]:
    return {
        "correlation_id": correlation_id,
        "status": "aborted" if aborted else "completed",
        "outbox_id": f"outbox-{correlation_id}",
        "terminal_id": f"terminal-{correlation_id}",
        "terminal_message_id": f"message-{correlation_id}",
        "terminal_event_id": f"event-{correlation_id}",
        "report": {
            "content": "complete",
            "provider_state": "aborted" if aborted else "final",
            "sequence": 2,
            "usage": None,
            "stop_reason": "end_turn",
            "error_message": None,
            "legacy_event": {"event_type": "cancelled" if aborted else "complete"},
        },
        "report_hash": "a" * 64,
        "persisted": True,
    }


class _PassingLiveTransport:
    def __init__(self, gate: ModuleType) -> None:
        self._gate = gate
        self.provider_calls: list[dict[str, Any]] = []
        self._history = [
            {
                "id": "message-1",
                "role": "assistant",
                "content": [{"type": "text", "text": "complete"}],
                "timestamp": 1,
                "sequence": 1,
            }
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        if request.url.host == "api.test" and request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "version": "0.2.0"})
        if request.url.host == "core.test" and request.url.path == "/health":
            return httpx.Response(
                200,
                json={"status": "ok", "version": "memstack-workspace-core/0.1.0"},
            )
        if request.url.path == "/internal/v1/capabilities/workspace-public-api":
            assert request.headers["authorization"] == "Bearer core-secret"
            return httpx.Response(
                200,
                json={
                    "complete": True,
                    "implemented_route_count": 92,
                    "required_route_count": 92,
                },
            )
        if request.url.path == "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1":
            assert request.headers["authorization"] == "Bearer core-secret"
            assert request.headers["x-memstack-user-id"] == "user-1"
            return httpx.Response(
                200,
                json={
                    "id": "workspace-1",
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                },
            )
        if request.url.path.endswith("/workspaces/workspace-1/agents"):
            assert request.url.params["active_only"] == "true"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "binding-1",
                        "workspace_id": "workspace-1",
                        "agent_id": "agent-1",
                        "is_active": True,
                    }
                ],
            )
        if request.url.host == "ray.test" and request.url.path == "/api/jobs/":
            return httpx.Response(
                200,
                json=[
                    {
                        "status": "RUNNING",
                        "entrypoint": "python -m src.agent_actor_worker",
                    }
                ],
            )
        if request.url.path.startswith("/internal/v1/runtime-correlations/"):
            assert request.headers["authorization"] == "Bearer core-secret"
            correlation_id = request.url.path.split("/")[-2]
            abort_correlation = self._gate._provider_correlation_id("live-contract-abort")
            return httpx.Response(
                200,
                json=_terminal(correlation_id, aborted=correlation_id == abort_correlation),
            )
        if request.url.path == "/internal/v1/workspace-core/provider":
            assert request.headers["authorization"] == "Bearer provider-secret"
            payload = cast("dict[str, Any]", json.loads(request.content))
            self.provider_calls.append(payload)
            if payload["method"] == "chat.history":
                return httpx.Response(200, json={"ok": True, "messages": self._history})
            if payload["method"] == "chat.abort":
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "aborted": True,
                        "ray_cancelled": True,
                        "local_worker_cancelled": True,
                    },
                )
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)


async def test_mock_transport_contract_covers_every_live_gate_without_claiming_live_evidence(
    tmp_path: Path,
) -> None:
    gate = _load_gate()
    config = gate.LiveAgentE2EConfig.from_environment(
        evidence_output=tmp_path / "live-evidence.json",
        environ=_environment(),
    )
    passing_transport = _PassingLiveTransport(gate)

    async def no_sleep(_seconds: float) -> None:
        return None

    evidence = await gate.run_live_agent_e2e(
        config,
        transport=httpx.MockTransport(passing_transport),
        sleep=no_sleep,
    )

    assert evidence["evidenceClass"] == "transport-contract"
    assert evidence["liveEvidence"] is False
    assert len(evidence["terminalProofs"]) == 3
    assert evidence["history"]["duplicateDeliveryStable"] is True
    assert evidence["abort"] == {
        "activeCancellationObserved": True,
        "rayCancelled": True,
        "localWorkerCancelled": True,
    }
    followup_calls = [
        item for item in passing_transport.provider_calls if item["id"] == "live-contract-followup"
    ]
    assert len(followup_calls) == 2
    abort_calls = [
        item for item in passing_transport.provider_calls if item["method"] == "chat.abort"
    ]
    assert abort_calls[0]["run_id"] == "live-contract-abort"
    assert all(
        item["extensions"]["task_id"] == "task-1" for item in passing_transport.provider_calls
    )
    assert all(
        item["to_bot"]["provider_id"] == "memstack-workspace-agent-runtime"
        for item in passing_transport.provider_calls
    )
    assert all(item["session_id"] == "workspace-1" for item in passing_transport.provider_calls)
    serialized = (tmp_path / "live-evidence.json").read_text(encoding="utf-8")
    assert "provider-secret" not in serialized
    assert "core-secret" not in serialized


def test_environment_contract_fails_closed_without_credentials_or_live_scope(
    tmp_path: Path,
) -> None:
    gate = _load_gate()

    with pytest.raises(gate.LiveAgentE2EError) as captured:
        gate.LiveAgentE2EConfig.from_environment(
            evidence_output=tmp_path / "evidence.json",
            environ={},
        )

    details = {item["detail"] for item in captured.value.blockers}
    assert any("WORKSPACE_CORE_BASE_URL" in item for item in details)
    assert any("WORKSPACE_E2E_TENANT_ID" in item for item in details)
    assert any("WORKSPACE_E2E_ABORT_MESSAGE" in item for item in details)


def test_environment_contract_rejects_llm_provider_as_core_provider_identity(
    tmp_path: Path,
) -> None:
    gate = _load_gate()
    environ = _environment()
    environ["WORKSPACE_E2E_PROVIDER_ID"] = "llm-provider-uuid"

    with pytest.raises(gate.LiveAgentE2EError) as captured:
        gate.LiveAgentE2EConfig.from_environment(
            evidence_output=tmp_path / "evidence.json",
            environ=environ,
        )

    assert captured.value.blockers == [
        {
            "code": "invalid_provider_identity",
            "detail": ("WORKSPACE_E2E_PROVIDER_ID must be memstack-workspace-agent-runtime"),
        }
    ]


@pytest.mark.parametrize("field", ["WORKSPACE_E2E_GROUP_ID", "WORKSPACE_E2E_SESSION_ID"])
async def test_preflight_rejects_group_or_session_outside_workspace_projection(
    tmp_path: Path,
    field: str,
) -> None:
    gate = _load_gate()
    environ = _environment()
    environ[field] = "synthetic-scope"
    config = gate.LiveAgentE2EConfig.from_environment(
        evidence_output=tmp_path / "blocked.json",
        environ=environ,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            version = (
                "memstack-workspace-core/0.1.0" if request.url.host == "core.test" else "0.2.0"
            )
            return httpx.Response(200, json={"status": "ok", "version": version})
        if request.url.path == "/internal/v1/capabilities/workspace-public-api":
            return httpx.Response(
                200,
                json={
                    "complete": True,
                    "implemented_route_count": 92,
                    "required_route_count": 92,
                },
            )
        if request.url.host == "ray.test":
            return httpx.Response(
                200,
                json=[
                    {
                        "status": "RUNNING",
                        "entrypoint": "python -m src.agent_actor_worker",
                    }
                ],
            )
        if request.url.path.endswith("/workspaces/workspace-1"):
            return httpx.Response(
                200,
                json={
                    "id": "workspace-1",
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                },
            )
        if request.url.path.endswith("/workspaces/workspace-1/agents"):
            return httpx.Response(
                200,
                json=[
                    {
                        "workspace_id": "workspace-1",
                        "agent_id": "agent-1",
                        "is_active": True,
                    }
                ],
            )
        return httpx.Response(404)

    with pytest.raises(gate.LiveAgentE2EError) as captured:
        await gate.run_live_agent_e2e(config, transport=httpx.MockTransport(handler))

    assert {item["code"] for item in captured.value.blockers} == {"workspace_projection_scope"}
    assert not config.evidence_output.exists()


async def test_preflight_failure_never_writes_live_evidence(tmp_path: Path) -> None:
    gate = _load_gate()
    output = tmp_path / "blocked.json"
    config = gate.LiveAgentE2EConfig.from_environment(
        evidence_output=output,
        environ=_environment(),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.test":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.host == "ray.test":
            return httpx.Response(
                200,
                json=[
                    {
                        "status": "RUNNING",
                        "entrypoint": "python -m src.agent_actor_worker",
                    }
                ],
            )
        return httpx.Response(503, json={"detail": "unavailable"})

    with pytest.raises(gate.LiveAgentE2EError) as captured:
        await gate.run_live_agent_e2e(config, transport=httpx.MockTransport(handler))

    codes = {item["code"] for item in captured.value.blockers}
    assert {"core_health", "core_capabilities"}.issubset(codes)
    assert not output.exists()
