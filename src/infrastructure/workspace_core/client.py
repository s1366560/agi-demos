"""Private HTTP client and access adapter for Avernet Workspace Core."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable, AsyncIterator, Mapping, Sequence
from typing import Any, Literal, cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, StrictBool, ValidationError

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.domain.ports.services.workspace_access_verifier_port import WorkspaceAccessRequest

logger = logging.getLogger(__name__)


class WorkspaceCoreClientError(RuntimeError):
    """Workspace Core was unavailable or violated its private contract."""


class WorkspaceCoreNotFoundError(WorkspaceCoreClientError):
    """Workspace Core could not find the requested private resource."""


class WorkspaceCoreForbiddenError(WorkspaceCoreClientError):
    """Workspace Core rejected the caller's canonical scope."""


class WorkspaceCoreConflictError(WorkspaceCoreClientError):
    """Workspace Core rejected an idempotency or revision precondition."""


class WorkspaceCoreCompatibilityError(WorkspaceCoreClientError):
    """Workspace Core cannot serve the gateway's frozen public API contract."""


class WorkspaceCoreProxyResponse:
    """Open upstream response whose bytes and connection are closed after streaming."""

    def __init__(self, client: httpx.AsyncClient, response: httpx.Response) -> None:
        super().__init__()
        self._client = client
        self._response = response
        self._closed = False

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self._response.headers

    async def aiter_raw(self) -> AsyncIterator[bytes]:
        """Yield wire bytes with backpressure and always release upstream resources."""
        try:
            if self._response.is_stream_consumed:
                if self._response.content:
                    yield self._response.content
            else:
                async for chunk in self._response.aiter_raw():
                    yield chunk
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """Idempotently close both the response stream and its private client."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._response.aclose()
        finally:
            await self._client.aclose()


class WorkspaceCoreHealth(BaseModel):
    """Health response returned by the Workspace Core helper/service."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    version: str


class WorkspaceCorePublicRoute(BaseModel):
    """One public method/path pair implemented by Workspace Core."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["DELETE", "GET", "PATCH", "POST", "PUT"]
    path: str = Field(pattern=r"^/api/v1/")


class WorkspaceCorePublicApiCapabilities(BaseModel):
    """Authenticated declaration used to fail closed before gateway startup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal[1]
    manifest_version: NonNegativeInt
    required_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_route_count: NonNegativeInt
    required_route_keys_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    implemented_contract_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    implemented_route_count: NonNegativeInt
    implemented_route_keys_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    implemented_routes: list[WorkspaceCorePublicRoute]
    complete: StrictBool


class WorkspaceCoreSnapshot(BaseModel):
    """Canonical read-only snapshot used during migration comparison."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str
    workspace_id: str
    revision: NonNegativeInt
    counts: dict[str, NonNegativeInt]
    canonical_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkspaceCoreProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    tenant_id: str
    project_id: str
    name: str
    created_by: str
    is_archived: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceCoreMember(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    user_id: str
    role: str


class WorkspaceCoreAgent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    workspace_id: str
    agent_id: str
    display_name: str | None = None
    label: str | None = None
    status: str = "idle"
    is_active: bool = True


class WorkspaceCoreTask(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    workspace_id: str
    title: str


class WorkspaceAuthorityActor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    is_superuser: StrictBool = False


class WorkspaceAuthorityTaskRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str
    task_id: str


class WorkspaceAuthorityQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: WorkspaceAuthorityActor
    workspace_ids: list[str]
    task_refs: list[WorkspaceAuthorityTaskRef] = Field(default_factory=list)


class WorkspaceAuthorityQueryProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str
    tenant_id: str
    project_id: str
    name: str
    created_by: str
    is_archived: StrictBool
    metadata: dict[str, Any]
    member_role: str | None


class WorkspaceAuthorityTaskLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str
    task_id: str
    linked: StrictBool


class WorkspaceAuthorityQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profiles: list[WorkspaceAuthorityQueryProfile]
    task_links: list[WorkspaceAuthorityTaskLink]


class WorkspaceCoreTaskSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: dict[str, Any]
    conversation_id: str
    initial_message: dict[str, Any]
    workspace_policy: dict[str, Any] | None = None
    capability_mode: Literal["work", "code"]


class WorkspaceCoreTaskSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: str
    replayed: StrictBool
    workspace: dict[str, Any]
    initial_message: dict[str, Any]
    policy: dict[str, Any] | None
    capability_version: str


class _WorkspaceAccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: StrictBool


class WorkspaceRuntimeCorrelationRequest(BaseModel):
    """Immutable Agent Runtime delivery identity recorded by Workspace Core."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    tenant_id: str
    project_id: str
    workspace_id: str
    user_id: str
    task_id: str | None = None
    attempt_id: str | None = None
    plan_id: str | None = None
    plan_node_id: str | None = None
    conversation_id: str
    bcs_session_id: str
    bcs_group_id: str
    bcs_message_id: str | None = None
    state_machine_run_id: str | None = None
    delivery_request_id: str
    provider_run_id: str
    provider_id: str
    provider_bot_ref: str = ""


class WorkspaceRuntimeCorrelationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    status: Literal["pending", "running", "completed", "failed", "aborted"]
    created: StrictBool


class WorkspaceRuntimeTerminalRequest(BaseModel):
    """Persisted terminal proof to commit with the Workspace outbox event."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str
    workspace_id: str
    execution_status: Literal["complete", "error", "aborted"]
    terminal_message_id: str
    terminal_event_id: str
    report: dict[str, Any]


class WorkspaceRuntimeTerminalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    status: Literal["completed", "failed", "aborted"]
    outbox_id: str
    terminal_id: str | None = None
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created: StrictBool


class WorkspaceRuntimeTerminalReport(BaseModel):
    """Replay-safe Provider terminal report stored by Workspace Core."""

    model_config = ConfigDict(extra="forbid")

    content: str
    provider_state: Literal["final", "error", "aborted"]
    sequence: NonNegativeInt
    usage: dict[str, Any] | None = None
    stop_reason: str | None = None
    error_message: str | None = None
    legacy_event: dict[str, Any]


class WorkspaceRuntimeTerminalReadResponse(BaseModel):
    """Persisted terminal authority used to replay a lost Provider callback."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    status: Literal["completed", "failed", "aborted"]
    outbox_id: str
    terminal_id: str | None = None
    terminal_message_id: str
    terminal_event_id: str
    report: WorkspaceRuntimeTerminalReport
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    persisted: Literal[True]


class WorkspaceRuntimeRecoveryClaimRequest(BaseModel):
    """Deterministic lease controls for one bounded recovery sweep."""

    model_config = ConfigDict(extra="forbid")

    lease_owner: str
    stale_after_seconds: int = Field(gt=0, le=86_400)
    lease_seconds: int = Field(gt=0, le=3_600)
    limit: int = Field(gt=0, le=100)


class WorkspaceRuntimeRecoveryItem(BaseModel):
    """One scoped correlation leased to the Python recovery worker."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    tenant_id: str
    project_id: str
    workspace_id: str
    user_id: str
    task_id: str | None = None
    plan_id: str | None = None
    plan_node_id: str | None = None
    conversation_id: str
    bcs_session_id: str
    bcs_group_id: str
    delivery_request_id: str
    provider_run_id: str
    provider_id: str
    provider_bot_ref: str = ""
    status: Literal["running", "completed", "failed", "aborted"]
    recovery_attempt_count: NonNegativeInt


class WorkspaceRuntimeRecoveryClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recoveries: list[WorkspaceRuntimeRecoveryItem]


class WorkspaceRuntimeCallbackAckRequest(BaseModel):
    """Scope required to acknowledge a terminal `/bot/events` callback."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str
    workspace_id: str


class WorkspaceRuntimeCallbackAckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    status: Literal["completed", "failed", "aborted"]
    acknowledged: Literal[True]


class WorkspaceRuntimeRecoveryJudgmentRequest(BaseModel):
    """Auditable structured Agent verdict for one leased recovery."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str
    tenant_id: str
    project_id: str
    workspace_id: str
    lease_owner: str
    action: Literal["continue", "fail", "escalate"]
    agent_id: str
    tool_name: Literal["decide_runtime_recovery"]
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    rationale: str
    latency_ms: NonNegativeInt


class WorkspaceRuntimeRecoveryJudgmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    correlation_id: str
    action: Literal["continue", "fail", "escalate"]
    recorded: Literal[True]


class WorkspaceCoreClient:
    """Stateless authenticated client for the private Workspace Core API."""

    def __init__(
        self,
        settings: WorkspaceCoreSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__()
        if settings.base_url is None or settings.service_token is None:
            raise ValueError("Workspace Core client requires connection credentials")
        self._base_url = str(settings.base_url)
        self._service_token = settings.service_token
        self._timeout = settings.request_timeout_seconds
        self._transport = transport

    async def health(self) -> WorkspaceCoreHealth:
        """Read the core health contract without changing authority state."""
        payload = await self._get("/health")
        return self._validate(WorkspaceCoreHealth, payload, path="/health")

    async def read_public_api_capabilities(self) -> WorkspaceCorePublicApiCapabilities:
        """Read the authenticated public API implementation declaration."""
        path = "/internal/v1/capabilities/workspace-public-api"
        payload = await self._get(path)
        return self._validate(WorkspaceCorePublicApiCapabilities, payload, path=path)

    async def read_snapshot(
        self,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
    ) -> WorkspaceCoreSnapshot:
        """Read a canonical migration snapshot for parity comparison."""
        path = f"/internal/v1/workspaces/{_path_segment(workspace_id)}/snapshot"
        payload = await self._get(
            path,
            headers={"X-MemStack-Tenant-ID": tenant_id},
            params={"project_id": project_id},
        )
        return self._validate(WorkspaceCoreSnapshot, payload, path=path)

    async def has_workspace_access(self, request: WorkspaceAccessRequest) -> bool:
        """Check current membership against the Avernet authority."""
        path = (
            f"/internal/v1/workspaces/{_path_segment(request.workspace_id)}"
            f"/members/{_path_segment(request.user_id)}"
        )
        payload = await self._get(
            path,
            headers={"X-MemStack-Tenant-ID": request.tenant_id},
        )
        response = self._validate(_WorkspaceAccessResponse, payload, path=path)
        return response.allowed

    async def read_workspace_profile(
        self,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        user_id: str,
        is_superuser: bool = False,
    ) -> WorkspaceCoreProfile:
        path = (
            f"/api/v1/tenants/{_path_segment(tenant_id)}/projects/{_path_segment(project_id)}"
            f"/workspaces/{_path_segment(workspace_id)}"
        )
        payload = await self._get(
            path,
            headers=_caller_headers(user_id=user_id, is_superuser=is_superuser),
        )
        return self._validate(WorkspaceCoreProfile, payload, path=path)

    async def list_workspace_members(
        self,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        user_id: str,
        is_superuser: bool = False,
    ) -> list[WorkspaceCoreMember]:
        path = (
            f"/api/v1/tenants/{_path_segment(tenant_id)}/projects/{_path_segment(project_id)}"
            f"/workspaces/{_path_segment(workspace_id)}/members"
        )
        payload = await self._get_json(
            path,
            headers=_caller_headers(user_id=user_id, is_superuser=is_superuser),
        )
        try:
            return [WorkspaceCoreMember.model_validate(item) for item in payload]
        except ValidationError as exc:
            raise WorkspaceCoreClientError(
                f"Workspace Core returned invalid members for GET {path}"
            ) from exc

    async def list_workspace_agents(
        self,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        user_id: str,
        is_superuser: bool = False,
        active_only: bool = True,
    ) -> list[WorkspaceCoreAgent]:
        path = (
            f"/api/v1/tenants/{_path_segment(tenant_id)}/projects/{_path_segment(project_id)}"
            f"/workspaces/{_path_segment(workspace_id)}/agents"
        )
        payload = await self._get_json(
            path,
            headers=_caller_headers(user_id=user_id, is_superuser=is_superuser),
            params={"active_only": str(active_only).lower(), "limit": "1000", "offset": "0"},
        )
        try:
            return [WorkspaceCoreAgent.model_validate(item) for item in payload]
        except ValidationError as exc:
            raise WorkspaceCoreClientError(
                f"Workspace Core returned invalid agents for GET {path}"
            ) from exc

    async def read_workspace_task(
        self,
        *,
        workspace_id: str,
        task_id: str,
        user_id: str,
        is_superuser: bool = False,
    ) -> WorkspaceCoreTask:
        path = (
            f"/api/v1/workspaces/{_path_segment(workspace_id)}/tasks/{_path_segment(task_id)}"
        )
        payload = await self._get(
            path,
            headers=_caller_headers(user_id=user_id, is_superuser=is_superuser),
        )
        return self._validate(WorkspaceCoreTask, payload, path=path)

    async def query_workspace_authority(
        self,
        request: WorkspaceAuthorityQueryRequest,
    ) -> WorkspaceAuthorityQueryResponse:
        """Batch canonical Workspace profiles, member roles, and task linkage."""
        path = "/internal/v1/workspace-authority/query"
        payload = await self._post(
            path,
            headers={},
            json_body=request.model_dump(mode="json"),
        )
        return self._validate(
            WorkspaceAuthorityQueryResponse,
            payload,
            path=path,
            method="POST",
        )

    async def create_task_session(
        self,
        *,
        tenant_id: str,
        project_id: str,
        user_id: str,
        user_email: str,
        idempotency_key: str,
        request: WorkspaceCoreTaskSessionRequest,
    ) -> WorkspaceCoreTaskSessionResponse:
        path = (
            f"/internal/v1/tenants/{_path_segment(tenant_id)}/projects/"
            f"{_path_segment(project_id)}/task-sessions"
        )
        payload = await self._post(
            path,
            headers={
                "X-MemStack-User-ID": user_id,
                "X-MemStack-User-Email": user_email,
                "X-Idempotency-Key": idempotency_key,
            },
            json_body=request.model_dump(exclude_none=True),
        )
        return self._validate(
            WorkspaceCoreTaskSessionResponse,
            payload,
            path=path,
            method="POST",
        )

    async def record_runtime_correlation(
        self,
        request: WorkspaceRuntimeCorrelationRequest,
    ) -> WorkspaceRuntimeCorrelationResponse:
        """Idempotently bind one BCS delivery to the MemStack execution scope."""
        path = "/internal/v1/runtime-correlations"
        payload = await self._post(
            path,
            headers={"X-MemStack-Tenant-ID": request.tenant_id},
            json_body=request.model_dump(exclude={"tenant_id"}),
        )
        return self._validate(WorkspaceRuntimeCorrelationResponse, payload, path=path)

    async def record_runtime_terminal(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeTerminalRequest,
    ) -> WorkspaceRuntimeTerminalResponse:
        """Atomically commit the terminal proof and Workspace outbox event."""
        path = f"/internal/v1/runtime-correlations/{_path_segment(correlation_id)}/terminal"
        payload = await self._post(
            path,
            headers={"X-MemStack-Tenant-ID": request.tenant_id},
            json_body=request.model_dump(exclude={"tenant_id"}),
        )
        return self._validate(WorkspaceRuntimeTerminalResponse, payload, path=path)

    async def read_runtime_terminal(
        self,
        correlation_id: str,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
    ) -> WorkspaceRuntimeTerminalReadResponse:
        """Read a committed terminal without invoking Agent Runtime again."""
        path = f"/internal/v1/runtime-correlations/{_path_segment(correlation_id)}/terminal"
        payload = await self._get(
            path,
            headers={"X-MemStack-Tenant-ID": tenant_id},
            params={"project_id": project_id, "workspace_id": workspace_id},
        )
        return self._validate(WorkspaceRuntimeTerminalReadResponse, payload, path=path)

    async def claim_runtime_recoveries(
        self,
        request: WorkspaceRuntimeRecoveryClaimRequest,
    ) -> WorkspaceRuntimeRecoveryClaimResponse:
        """Lease a bounded batch of stale or callback-incomplete correlations."""
        path = "/internal/v1/runtime-recoveries/claim"
        payload = await self._post(path, headers={}, json_body=request.model_dump())
        return self._validate(WorkspaceRuntimeRecoveryClaimResponse, payload, path=path)

    async def acknowledge_runtime_terminal_callback(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeCallbackAckRequest,
    ) -> WorkspaceRuntimeCallbackAckResponse:
        """Acknowledge that Avernet accepted the persisted terminal callback."""
        path = f"/internal/v1/runtime-correlations/{_path_segment(correlation_id)}/callback-ack"
        payload = await self._post(
            path,
            headers={"X-MemStack-Tenant-ID": request.tenant_id},
            json_body=request.model_dump(exclude={"tenant_id"}),
        )
        return self._validate(WorkspaceRuntimeCallbackAckResponse, payload, path=path)

    async def record_runtime_recovery_judgment(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeRecoveryJudgmentRequest,
    ) -> WorkspaceRuntimeRecoveryJudgmentResponse:
        """Persist one structured Agent recovery verdict and release its lease."""
        path = (
            f"/internal/v1/runtime-correlations/{_path_segment(correlation_id)}/recovery-judgments"
        )
        payload = await self._post(
            path,
            headers={"X-MemStack-Tenant-ID": request.tenant_id},
            json_body=request.model_dump(exclude={"tenant_id"}),
        )
        return self._validate(WorkspaceRuntimeRecoveryJudgmentResponse, payload, path=path)

    async def proxy_request(
        self,
        *,
        method: str,
        path: str,
        query: bytes,
        body: AsyncIterable[bytes] | bytes,
        headers: Sequence[tuple[str, str]],
    ) -> WorkspaceCoreProxyResponse:
        """Open one legacy-compatible streaming request and response."""
        request_headers = httpx.Headers(headers)
        request_headers["Authorization"] = f"Bearer {self._service_token.get_secret_value()}"
        request_headers["Accept-Encoding"] = "identity"
        url = path if not query else f"{path}?{query.decode('latin-1')}"
        client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        )
        try:
            upstream_request = client.build_request(
                method,
                url,
                headers=request_headers,
                content=body,
            )
            response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            raise WorkspaceCoreClientError(
                f"Workspace Core request failed for {method} {path}"
            ) from exc
        return WorkspaceCoreProxyResponse(client, response)

    async def _get(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        payload = await self._request_json("GET", path, headers=headers, params=params)
        if not isinstance(payload, dict):
            raise WorkspaceCoreClientError(
                f"Workspace Core returned a non-object response for GET {path}"
            )
        return cast("dict[str, Any]", payload)

    async def _get_json(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        payload = await self._request_json("GET", path, headers=headers, params=params)
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise WorkspaceCoreClientError(
                f"Workspace Core returned a non-list response for GET {path}"
            )
        return cast("list[dict[str, Any]]", payload)

    async def _post(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = await self._request_json("POST", path, headers=headers, json_body=json_body)
        if not isinstance(payload, dict):
            raise WorkspaceCoreClientError(
                f"Workspace Core returned a non-object response for POST {path}"
            )
        return cast("dict[str, Any]", payload)

    async def _request_json(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> object:
        request_headers = {
            "Authorization": f"Bearer {self._service_token.get_secret_value()}",
            "Accept": "application/json",
            **dict(headers or {}),
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=request_headers,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, params=params, json=json_body)
                _ = response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            error_message = f"Workspace Core request failed for {method} {path}"
            if exc.response.status_code == 403:
                raise WorkspaceCoreForbiddenError(error_message) from exc
            if exc.response.status_code == 404:
                raise WorkspaceCoreNotFoundError(
                    f"Workspace Core resource was not found for {method} {path}"
                ) from exc
            if exc.response.status_code == 409:
                raise WorkspaceCoreConflictError(error_message) from exc
            raise WorkspaceCoreClientError(error_message) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise WorkspaceCoreClientError(
                f"Workspace Core request failed for {method} {path}"
            ) from exc
        return payload

    @staticmethod
    def _validate[ResponseT: BaseModel](
        response_type: type[ResponseT],
        payload: dict[str, Any],
        *,
        path: str,
        method: str = "GET",
    ) -> ResponseT:
        try:
            return response_type.model_validate(payload)
        except ValidationError as exc:
            raise WorkspaceCoreClientError(
                f"Workspace Core returned an invalid response for {method} {path}"
            ) from exc


class AvernetWorkspaceAccessVerifier:
    """Fail-closed membership verifier backed by Workspace Core."""

    def __init__(self, client: WorkspaceCoreClient) -> None:
        super().__init__()
        self._client = client

    async def has_access(self, request: WorkspaceAccessRequest) -> bool:
        try:
            return await self._client.has_workspace_access(request)
        except WorkspaceCoreClientError:
            logger.warning(
                "Workspace Core access verification failed closed",
                extra={"workspace_id": request.workspace_id},
            )
            return False


def _path_segment(value: str) -> str:
    return quote(value, safe="")


def _caller_headers(*, user_id: str, is_superuser: bool) -> dict[str, str]:
    return {
        "X-MemStack-User-ID": user_id,
        "X-MemStack-User-Is-Superuser": "true" if is_superuser else "false",
    }


__all__ = [
    "AvernetWorkspaceAccessVerifier",
    "WorkspaceAuthorityActor",
    "WorkspaceAuthorityQueryRequest",
    "WorkspaceAuthorityQueryResponse",
    "WorkspaceAuthorityTaskRef",
    "WorkspaceCoreClient",
    "WorkspaceCoreClientError",
    "WorkspaceCoreCompatibilityError",
    "WorkspaceCoreConflictError",
    "WorkspaceCoreForbiddenError",
    "WorkspaceCoreHealth",
    "WorkspaceCoreNotFoundError",
    "WorkspaceCoreProxyResponse",
    "WorkspaceCorePublicApiCapabilities",
    "WorkspaceCorePublicRoute",
    "WorkspaceCoreSnapshot",
    "WorkspaceCoreTaskSessionRequest",
    "WorkspaceCoreTaskSessionResponse",
    "WorkspaceRuntimeCorrelationRequest",
    "WorkspaceRuntimeCorrelationResponse",
    "WorkspaceRuntimeTerminalReadResponse",
    "WorkspaceRuntimeTerminalReport",
    "WorkspaceRuntimeTerminalRequest",
    "WorkspaceRuntimeTerminalResponse",
]
