"""Contract tests for the read-only Workspace Core client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import pytest

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.domain.ports.services.workspace_access_verifier_port import WorkspaceAccessRequest
from src.infrastructure.workspace_core.client import (
    AvernetWorkspaceAccessVerifier,
    WorkspaceCoreClient,
    WorkspaceCoreClientError,
    WorkspaceCorePublicApiCapabilities,
    WorkspaceRuntimeCallbackAckRequest,
    WorkspaceRuntimeCorrelationRequest,
    WorkspaceRuntimeRecoveryClaimRequest,
    WorkspaceRuntimeRecoveryJudgmentRequest,
    WorkspaceRuntimeTerminalRequest,
)


def _settings() -> WorkspaceCoreSettings:
    return WorkspaceCoreSettings.model_validate(
        {
            "WORKSPACE_CORE_SHADOW_READ_ENABLED": True,
            "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
            "WORKSPACE_CORE_SERVICE_TOKEN": "internal-test-token",
        }
    )


@pytest.mark.unit
async def test_health_uses_private_service_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer internal-test-token"
        return httpx.Response(200, json={"status": "ok", "version": "0.1.0"})

    client = WorkspaceCoreClient(_settings(), transport=httpx.MockTransport(handler))

    health = await client.health()

    assert health.status == "ok"
    assert health.version == "0.1.0"


@pytest.mark.unit
async def test_public_api_capabilities_use_private_service_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/v1/capabilities/workspace-public-api"
        assert request.headers["authorization"] == "Bearer internal-test-token"
        return httpx.Response(
            200,
            json={
                "protocol_version": 1,
                "manifest_version": 1,
                "required_contract_sha256": "a" * 64,
                "required_route_count": 92,
                "required_route_keys_sha256": "b" * 64,
                "implemented_contract_sha256": None,
                "implemented_route_count": 0,
                "implemented_route_keys_sha256": "c" * 64,
                "implemented_routes": [],
                "complete": False,
            },
        )

    client = WorkspaceCoreClient(_settings(), transport=httpx.MockTransport(handler))

    capabilities = await client.read_public_api_capabilities()

    assert isinstance(capabilities, WorkspaceCorePublicApiCapabilities)
    assert capabilities.required_route_count == 92
    assert capabilities.complete is False


@pytest.mark.unit
async def test_access_check_sends_tenant_correlation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/v1/workspaces/ws-1/members/user-1"
        assert request.headers["x-memstack-tenant-id"] == "tenant-1"
        return httpx.Response(200, json={"allowed": True})

    client = WorkspaceCoreClient(_settings(), transport=httpx.MockTransport(handler))
    verifier = AvernetWorkspaceAccessVerifier(client)

    allowed = await verifier.has_access(
        WorkspaceAccessRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            workspace_id="ws-1",
        )
    )

    assert allowed is True


@pytest.mark.unit
async def test_read_snapshot_validates_canonical_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["project_id"] == "project-1"
        return httpx.Response(
            200,
            json={
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "workspace_id": "ws-1",
                "revision": 7,
                "counts": {"tasks": 3, "messages": 8},
                "canonical_hash": "a" * 64,
            },
        )

    client = WorkspaceCoreClient(_settings(), transport=httpx.MockTransport(handler))

    snapshot = await client.read_snapshot(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="ws-1",
    )

    assert snapshot.revision == 7
    assert snapshot.counts == {"tasks": 3, "messages": 8}


@pytest.mark.unit
async def test_access_verifier_fails_closed_when_core_is_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = WorkspaceCoreClient(_settings(), transport=httpx.MockTransport(handler))
    verifier = AvernetWorkspaceAccessVerifier(client)

    allowed = await verifier.has_access(
        WorkspaceAccessRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            workspace_id="ws-1",
        )
    )

    assert allowed is False


@pytest.mark.unit
async def test_proxy_request_preserves_method_query_body_and_context_headers() -> None:
    raw_body = b'{"name":"workspace","revision":7}'
    request_chunks: list[bytes] = []
    response_stream = _TrackingResponseStream([b'{"accepted":', b"true}"])

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/v1/workspaces/ws-1"
        assert request.url.query == b"tag=first&tag=second"
        async for chunk in request.stream:
            request_chunks.append(chunk)
        assert request.headers["authorization"] == "Bearer internal-test-token"
        assert request.headers["accept-encoding"] == "identity"
        assert request.headers["x-memstack-user-authorization"] == "Bearer user-token"
        assert request.headers["x-memstack-tenant-id"] == "tenant-1"
        return httpx.Response(
            202,
            headers={"Content-Length": "17"},
            stream=response_stream,
        )

    async def body_chunks() -> AsyncIterator[bytes]:
        yield raw_body[:12]
        yield raw_body[12:]

    client = WorkspaceCoreClient(_settings(), transport=_StreamingHandlerTransport(handler))

    response = await client.proxy_request(
        method="PATCH",
        path="/api/v1/workspaces/ws-1",
        query=b"tag=first&tag=second",
        body=body_chunks(),
        headers=[
            ("Content-Type", "application/json"),
            ("X-MemStack-User-Authorization", "Bearer user-token"),
            ("X-MemStack-Tenant-ID", "tenant-1"),
        ],
    )

    assert response.status_code == 202
    response_chunks = [chunk async for chunk in response.aiter_raw()]
    assert request_chunks == [raw_body[:12], raw_body[12:]]
    assert response_chunks == [b'{"accepted":', b"true}"]
    assert response.headers["content-length"] == "17"
    assert response_stream.closed is True


@pytest.mark.unit
async def test_proxy_request_maps_network_failure_without_fallback() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = WorkspaceCoreClient(_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(WorkspaceCoreClientError, match="PATCH /api/v1/workspaces/ws-1"):
        await client.proxy_request(
            method="PATCH",
            path="/api/v1/workspaces/ws-1",
            query=b"",
            body=b"{}",
            headers=[],
        )


class _TrackingResponseStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        super().__init__()
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _StreamingHandlerTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    ) -> None:
        super().__init__()
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._handler(request)


@pytest.mark.unit
async def test_runtime_correlation_and_terminal_use_atomic_core_contracts() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer internal-test-token"
        assert request.headers["x-memstack-tenant-id"] == "tenant-1"
        if request.url.path == "/internal/v1/runtime-correlations":
            return httpx.Response(
                200,
                json={
                    "correlation_id": "correlation-1",
                    "status": "running",
                    "created": True,
                },
            )
        assert request.url.path == ("/internal/v1/runtime-correlations/correlation-1/terminal")
        if request.method == "GET":
            assert dict(request.url.params) == {
                "project_id": "project-1",
                "workspace_id": "workspace-1",
            }
            return httpx.Response(
                200,
                json={
                    "correlation_id": "correlation-1",
                    "status": "completed",
                    "outbox_id": "outbox-1",
                    "terminal_id": "terminal-1",
                    "terminal_message_id": "message-1",
                    "terminal_event_id": "event-1",
                    "report": {
                        "content": "done",
                        "provider_state": "final",
                        "sequence": 2,
                        "usage": {"total_tokens": 12},
                        "stop_reason": "end_turn",
                        "error_message": None,
                        "legacy_event": {"event_id": "event-1"},
                    },
                    "report_hash": "a" * 64,
                    "persisted": True,
                },
            )
        return httpx.Response(
            200,
            json={
                "correlation_id": "correlation-1",
                "status": "completed",
                "outbox_id": "outbox-1",
                "terminal_id": "terminal-1",
                "report_hash": "a" * 64,
                "created": True,
            },
        )

    client = WorkspaceCoreClient(_settings(), transport=httpx.MockTransport(handler))
    correlation = await client.record_runtime_correlation(
        WorkspaceRuntimeCorrelationRequest(
            correlation_id="correlation-1",
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            user_id="user-1",
            task_id="task-1",
            plan_id="plan-1",
            plan_node_id="node-1",
            conversation_id="conversation-1",
            bcs_session_id="session-1",
            bcs_group_id="group-1",
            delivery_request_id="delivery-1",
            provider_run_id="provider-run-1",
            provider_id="provider-1",
            provider_bot_ref="agent-1",
        )
    )
    terminal = await client.record_runtime_terminal(
        correlation.correlation_id,
        WorkspaceRuntimeTerminalRequest(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            execution_status="complete",
            terminal_message_id="message-1",
            terminal_event_id="event-1",
            report={"content": "done"},
        ),
    )
    replay = await client.read_runtime_terminal(
        correlation.correlation_id,
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
    )

    assert correlation.status == "running"
    assert terminal.status == "completed"
    assert replay.report.provider_state == "final"
    assert replay.report.sequence == 2
    assert replay.persisted is True
    assert len(requests) == 3


@pytest.mark.unit
async def test_runtime_recovery_claim_ack_and_judgment_use_private_contracts() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer internal-test-token"
        if request.url.path == "/internal/v1/runtime-recoveries/claim":
            return httpx.Response(
                200,
                json={
                    "recoveries": [
                        {
                            "correlation_id": "correlation-1",
                            "tenant_id": "tenant-1",
                            "project_id": "project-1",
                            "workspace_id": "workspace-1",
                            "user_id": "user-1",
                            "task_id": "task-1",
                            "plan_id": "plan-1",
                            "plan_node_id": "node-1",
                            "conversation_id": "conversation-1",
                            "bcs_session_id": "session-1",
                            "bcs_group_id": "group-1",
                            "delivery_request_id": "delivery-1",
                            "provider_run_id": "provider-run-1",
                            "provider_id": "provider-1",
                            "provider_bot_ref": "agent-1",
                            "status": "running",
                            "recovery_attempt_count": 1,
                        }
                    ]
                },
            )
        assert request.headers["x-memstack-tenant-id"] == "tenant-1"
        if request.url.path.endswith("/callback-ack"):
            return httpx.Response(
                200,
                json={
                    "correlation_id": "correlation-1",
                    "status": "completed",
                    "acknowledged": True,
                },
            )
        return httpx.Response(
            200,
            json={
                "audit_id": "audit-1",
                "correlation_id": "correlation-1",
                "action": "continue",
                "recorded": True,
            },
        )

    client = WorkspaceCoreClient(_settings(), transport=httpx.MockTransport(handler))
    claim = await client.claim_runtime_recoveries(
        WorkspaceRuntimeRecoveryClaimRequest(
            lease_owner="worker-1",
            stale_after_seconds=60,
            lease_seconds=30,
            limit=20,
        )
    )
    ack = await client.acknowledge_runtime_terminal_callback(
        "correlation-1",
        WorkspaceRuntimeCallbackAckRequest(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
        ),
    )
    judgment = await client.record_runtime_recovery_judgment(
        "correlation-1",
        WorkspaceRuntimeRecoveryJudgmentRequest(
            audit_id="audit-1",
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            lease_owner="worker-1",
            action="continue",
            agent_id="judge-agent",
            tool_name="decide_runtime_recovery",
            input_json={"has_terminal": False},
            output_json={"action": "continue"},
            rationale="execution may still be active",
            latency_ms=12,
        ),
    )

    assert claim.recoveries[0].provider_id == "provider-1"
    assert ack.acknowledged is True
    assert judgment.recorded is True
    assert len(requests) == 3
