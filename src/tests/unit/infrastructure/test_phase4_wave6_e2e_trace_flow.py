"""Phase 4 Wave 6: End-to-end trace flow tests.

Validates cross-component integration across all Phase 4 infrastructure layers:
- Redis namespace adapter isolation (Wave 2)
- Redis credential scope adapter with encryption (Wave 2)
- SubAgentSpanService OTel integration (Wave 3)
- API endpoint helpers round-trip through Pydantic schemas (Wave 4)
- Cross-component: SubAgentRun -> namespace -> credential -> span -> API query
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    SubAgentRunListResponse,
    TraceChainResponse,
)
from src.infrastructure.adapters.primary.web.routers.agent.trace_router import (
    parse_statuses,
    router,
    run_to_response,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_redis_mock() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.mget = AsyncMock(return_value=[])
    redis.exists = AsyncMock(return_value=0)

    pipe = AsyncMock()
    pipe.set = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline = MagicMock(return_value=pipe)

    async def _empty_scan_iter(*, match: str = "*", count: int = 100):
        return
        yield

    redis.scan_iter = _empty_scan_iter
    return redis


def _make_encryption_mock() -> MagicMock:
    enc = MagicMock()
    enc.encrypt = MagicMock(side_effect=lambda v: f"ENC({v})")  # type: ignore[misc]
    enc.decrypt = MagicMock(side_effect=lambda v: str(v).replace("ENC(", "").rstrip(")"))  # type: ignore[misc]
    return enc


def _make_mock_tracer() -> MagicMock:
    tracer = MagicMock()
    mock_span = MagicMock()
    mock_span.get_span_context.return_value = MagicMock(
        trace_id=0x1234567890ABCDEF1234567890ABCDEF,
        span_id=0xABCDEF1234567890,
        is_remote=False,
    )

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_span)
    cm.__exit__ = MagicMock(return_value=False)
    tracer.start_as_current_span = MagicMock(return_value=cm)
    tracer.start_span = MagicMock(return_value=mock_span)

    return tracer


def _make_run(
    *,
    run_id: str = "run-e2e-1",
    conversation_id: str = "conv-e2e",
    subagent_name: str = "researcher",
    task: str = "research topic",
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    status: SubAgentRunStatus = SubAgentRunStatus.PENDING,
    created_at: datetime | None = None,
) -> SubAgentRun:
    run = SubAgentRun(
        run_id=run_id,
        conversation_id=conversation_id,
        subagent_name=subagent_name,
        task=task,
        created_at=created_at or datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
    )
    if trace_id is not None:
        run = run.with_trace_context(trace_id, parent_span_id)
    if status == SubAgentRunStatus.RUNNING:
        run = run.start()
    elif status == SubAgentRunStatus.COMPLETED:
        run = run.start()
        run = run.complete(summary="done", tokens_used=100, execution_time_ms=500)
    elif status == SubAgentRunStatus.FAILED:
        run = run.start()
        run = run.fail(error="boom")
    return run


# ---------------------------------------------------------------------------
# E2E: Redis namespace adapter — isolation between agents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNamespaceIsolationE2E:
    def _make_adapter(self, redis: AsyncMock):
        from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
            RedisAgentNamespaceAdapter,
        )

        return RedisAgentNamespaceAdapter(redis=redis, default_ttl_seconds=3600)

    async def test_set_and_get_for_same_agent(self) -> None:
        redis = _make_redis_mock()
        redis.get = AsyncMock(return_value=b"cached-value")
        adapter = self._make_adapter(redis)

        await adapter.set_key("proj-1", "agent-a", "state", "cached-value")
        result = await adapter.get_key("proj-1", "agent-a", "state")

        redis.set.assert_awaited_once_with("agent:ns:proj-1:agent-a:state", "cached-value", ex=3600)
        redis.get.assert_awaited_once_with("agent:ns:proj-1:agent-a:state")
        assert result is not None

    async def test_different_agents_use_different_keys(self) -> None:
        redis = _make_redis_mock()
        adapter = self._make_adapter(redis)

        await adapter.set_key("proj-1", "agent-a", "key1", "val-a")
        await adapter.set_key("proj-1", "agent-b", "key1", "val-b")

        calls = redis.set.await_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == "agent:ns:proj-1:agent-a:key1"
        assert calls[1].args[0] == "agent:ns:proj-1:agent-b:key1"

    async def test_delete_key_only_affects_target_agent(self) -> None:
        redis = _make_redis_mock()
        adapter = self._make_adapter(redis)

        await adapter.delete_key("proj-1", "agent-a", "key1")

        redis.delete.assert_awaited_once_with("agent:ns:proj-1:agent-a:key1")

    async def test_get_many_builds_correct_keys(self) -> None:
        redis = _make_redis_mock()
        redis.mget = AsyncMock(return_value=[b"v1", None, b"v3"])
        adapter = self._make_adapter(redis)

        result = await adapter.get_many("proj-1", "agent-x", ["k1", "k2", "k3"])

        redis.mget.assert_awaited_once_with(
            [
                "agent:ns:proj-1:agent-x:k1",
                "agent:ns:proj-1:agent-x:k2",
                "agent:ns:proj-1:agent-x:k3",
            ]
        )
        assert result["k1"] is not None
        assert result["k2"] is None
        assert result["k3"] is not None

    async def test_set_many_uses_pipeline(self) -> None:
        redis = _make_redis_mock()
        adapter = self._make_adapter(redis)

        await adapter.set_many("proj-1", "agent-y", {"a": "1", "b": "2"})

        pipe = redis.pipeline.return_value
        assert pipe.set.call_count == 2
        pipe.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# E2E: Redis credential scope adapter — encryption integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCredentialScopeE2E:
    def _make_adapter(self, redis: AsyncMock, enc: MagicMock | None = None):
        from src.infrastructure.adapters.secondary.cache.redis_agent_credential_scope import (
            RedisAgentCredentialScopeAdapter,
        )

        return RedisAgentCredentialScopeAdapter(
            redis=redis,
            encryption_service=enc or _make_encryption_mock(),
            default_ttl_seconds=3600,
        )

    async def test_set_credential_encrypts_value(self) -> None:
        redis = _make_redis_mock()
        enc = _make_encryption_mock()
        adapter = self._make_adapter(redis, enc)

        await adapter.set_credential("proj-1", "agent-a", "api_key", "secret-123")

        enc.encrypt.assert_called_once_with("secret-123")
        redis.set.assert_awaited_once_with(
            "agent:cred:proj-1:agent-a:api_key",
            "ENC(secret-123)",
            ex=3600,
        )

    async def test_get_credential_decrypts_value(self) -> None:
        redis = _make_redis_mock()
        enc = _make_encryption_mock()
        redis.get = AsyncMock(return_value=b"ENC(my-secret)")
        adapter = self._make_adapter(redis, enc)

        result = await adapter.get_credential("proj-1", "agent-a", "api_key")

        enc.decrypt.assert_called_once()
        assert result is not None

    async def test_get_credential_returns_none_when_missing(self) -> None:
        redis = _make_redis_mock()
        adapter = self._make_adapter(redis)

        result = await adapter.get_credential("proj-1", "agent-a", "missing")
        assert result is None

    async def test_has_credential_checks_existence(self) -> None:
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=1)
        adapter = self._make_adapter(redis)

        assert await adapter.has_credential("proj-1", "agent-a", "key") is True
        redis.exists.assert_awaited_once_with("agent:cred:proj-1:agent-a:key")

    async def test_delete_credential_removes_key(self) -> None:
        redis = _make_redis_mock()
        adapter = self._make_adapter(redis)

        result = await adapter.delete_credential("proj-1", "agent-a", "old-key")
        assert result is True
        redis.delete.assert_awaited_once_with("agent:cred:proj-1:agent-a:old-key")

    async def test_different_agents_credentials_isolated(self) -> None:
        redis = _make_redis_mock()
        enc = _make_encryption_mock()
        adapter = self._make_adapter(redis, enc)

        await adapter.set_credential("proj-1", "agent-a", "token", "tok-a")
        await adapter.set_credential("proj-1", "agent-b", "token", "tok-b")

        calls = redis.set.await_args_list
        assert calls[0].args[0] == "agent:cred:proj-1:agent-a:token"
        assert calls[1].args[0] == "agent:cred:proj-1:agent-b:token"


# ---------------------------------------------------------------------------
# E2E: SubAgentSpanService — OTel tracing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSpanServiceE2E:
    def _get_service(self):
        from src.infrastructure.agent.subagent.span_service import SubAgentSpanService

        return SubAgentSpanService

    async def test_trace_run_sets_span_attributes(self) -> None:
        cls = self._get_service()
        svc = cls()
        run = _make_run(trace_id="t-e2e", parent_span_id="s-e2e")

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=_make_mock_tracer(),
        ):
            async with svc.trace_run(run) as span:
                assert span is not None
                span.set_attribute.assert_any_call("subagent.name", "researcher")
                span.set_attribute.assert_any_call("subagent.run_id", "run-e2e-1")
                span.set_attribute.assert_any_call("subagent.trace_id", "t-e2e")
                span.set_attribute.assert_any_call("subagent.parent_span_id", "s-e2e")

    async def test_mark_span_completed_sets_attributes(self) -> None:
        cls = self._get_service()
        svc = cls()
        mock_span = MagicMock()

        svc.mark_span_completed(
            mock_span, summary="all done", tokens_used=42, execution_time_ms=1000
        )

        mock_span.set_attribute.assert_any_call("subagent.summary", "all done")
        mock_span.set_attribute.assert_any_call("subagent.tokens_used", 42)
        mock_span.set_attribute.assert_any_call("subagent.execution_time_ms", 1000)

    async def test_mark_span_failed_records_error(self) -> None:
        cls = self._get_service()
        svc = cls()
        mock_span = MagicMock()
        exc = RuntimeError("test failure")

        svc.mark_span_failed(mock_span, error="test failure", exception=exc)

        mock_span.record_exception.assert_called_once_with(exc)
        mock_span.set_status.assert_called_once()

    async def test_mark_span_completed_on_none_is_noop(self) -> None:
        cls = self._get_service()
        svc = cls()
        svc.mark_span_completed(None, summary="ignored")

    async def test_add_run_event_to_span(self) -> None:
        cls = self._get_service()
        svc = cls()
        mock_span = MagicMock()

        svc.add_run_event(mock_span, "task.started", {"key": "value"})

        mock_span.add_event.assert_called_once_with("task.started", attributes={"key": "value"})

    async def test_extract_trace_context_with_active_span(self) -> None:
        cls = self._get_service()
        svc = cls()

        mock_span = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.trace_id = 0xDEADBEEF12345678DEADBEEF12345678
        mock_ctx.span_id = 0x1234567890ABCDEF
        mock_span.get_span_context.return_value = mock_ctx

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_current_span",
            return_value=mock_span,
        ):
            result = svc.extract_trace_context()

        assert result is not None
        trace_id, span_id = result
        assert len(trace_id) == 32
        assert len(span_id) == 16


# ---------------------------------------------------------------------------
# E2E: API round-trip — SubAgentRun -> response -> filter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApiRoundTripE2E:
    def test_run_to_response_full_lifecycle(self) -> None:
        run = SubAgentRun(
            run_id="run-rt-1",
            conversation_id="conv-rt",
            subagent_name="coder",
            task="write code",
        )
        run = run.with_trace_context("trace-rt", "span-rt")
        run = run.start()
        run = run.complete(summary="code written", tokens_used=200, execution_time_ms=1500)

        resp = run_to_response(run)

        assert resp.run_id == "run-rt-1"
        assert resp.trace_id == "trace-rt"
        assert resp.parent_span_id == "span-rt"
        assert resp.status == "completed"
        assert resp.summary == "code written"
        assert resp.tokens_used == 200
        assert resp.execution_time_ms == 1500

    def test_multiple_runs_same_trace_in_list_response(self) -> None:
        runs = [
            _make_run(run_id=f"run-{i}", trace_id="shared-trace", parent_span_id=f"span-{i}")
            for i in range(3)
        ]
        responses = [run_to_response(r) for r in runs]
        list_resp = SubAgentRunListResponse(
            conversation_id="conv-e2e",
            runs=responses,
            total=len(responses),
        )

        assert list_resp.total == 3
        trace_ids = {r.trace_id for r in list_resp.runs}
        assert trace_ids == {"shared-trace"}
        run_ids = {r.run_id for r in list_resp.runs}
        assert len(run_ids) == 3

    def test_trace_chain_response_construction(self) -> None:
        runs = [
            _make_run(
                run_id=f"chain-{i}",
                trace_id="chain-trace",
                parent_span_id=f"span-{i}",
                status=SubAgentRunStatus.COMPLETED,
            )
            for i in range(2)
        ]
        responses = [run_to_response(r) for r in runs]
        chain = TraceChainResponse(
            trace_id="chain-trace",
            conversation_id="conv-e2e",
            runs=responses,
            total=2,
        )

        assert chain.trace_id == "chain-trace"
        assert chain.total == 2
        assert all(r.status == "completed" for r in chain.runs)

    def test_parse_statuses_round_trip(self) -> None:
        statuses = parse_statuses("running,completed,failed")
        assert statuses is not None
        assert len(statuses) == 3
        assert SubAgentRunStatus.RUNNING in statuses
        assert SubAgentRunStatus.COMPLETED in statuses
        assert SubAgentRunStatus.FAILED in statuses

    def test_failed_run_response_includes_error(self) -> None:
        run = _make_run(
            trace_id="t-fail",
            parent_span_id="s-fail",
            status=SubAgentRunStatus.FAILED,
        )
        resp = run_to_response(run)
        assert resp.status == "failed"
        assert resp.error == "boom"
        assert resp.trace_id == "t-fail"


# ---------------------------------------------------------------------------
# E2E: Full API endpoint with TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_registry():
    registry = MagicMock()
    registry.list_runs.return_value = []
    registry.list_trace_runs.return_value = []
    registry.get_run.return_value = None
    registry.list_descendant_runs.return_value = []
    registry.count_active_runs.return_value = 0
    registry.count_all_active_runs.return_value = 0
    return registry


@pytest.fixture
def mock_container(mock_registry: MagicMock):
    container = MagicMock()
    container.subagent_run_registry.return_value = mock_registry
    return container


@pytest.fixture
def app(mock_container: MagicMock):
    test_app = FastAPI()
    test_app.state.container = mock_container

    mock_user = SimpleNamespace(id="user-1", email="test@test.com", tenant_id="t-1")
    mock_db = AsyncMock()

    test_app.dependency_overrides[get_current_user] = lambda: mock_user
    test_app.dependency_overrides[get_db] = lambda: mock_db

    test_app.include_router(router, prefix="/api/v1/agent/trace")
    return test_app


@pytest.fixture
def client(app: FastAPI):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _patch_container_helper(mock_container: MagicMock):
    with (
        patch(
            "src.infrastructure.adapters.primary.web.routers.agent.trace_router.get_container_with_db",
            return_value=mock_container,
        ),
        patch(
            "src.infrastructure.adapters.primary.web.routers.agent.trace_router._get_accessible_conversation",
            AsyncMock(return_value=SimpleNamespace(id="conv-e2e", tenant_id="t-1", user_id="user-1")),
        ),
    ):
        yield


@pytest.mark.unit
class TestApiEndpointE2E:
    def test_list_runs_filtered_by_trace_id(
        self,
        client: TestClient,
        mock_registry: MagicMock,
    ) -> None:
        run1 = _make_run(run_id="r1", trace_id="t-target", status=SubAgentRunStatus.COMPLETED)
        run3 = _make_run(run_id="r3", trace_id="t-target", status=SubAgentRunStatus.FAILED)
        mock_registry.list_trace_runs.return_value = [run1, run3]

        resp = client.get("/api/v1/agent/trace/runs/conv-e2e?trace_id=t-target")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] == 2
        assert {r["run_id"] for r in data["runs"]} == {"r1", "r3"}

    def test_get_trace_chain_ordered_by_created_at(
        self,
        client: TestClient,
        mock_registry: MagicMock,
    ) -> None:
        run_early = _make_run(
            run_id="r-early",
            trace_id="chain-t",
            status=SubAgentRunStatus.COMPLETED,
            created_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        )
        run_late = _make_run(
            run_id="r-late",
            trace_id="chain-t",
            status=SubAgentRunStatus.COMPLETED,
            created_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC),
        )
        mock_registry.list_trace_runs.return_value = [run_early, run_late]

        resp = client.get("/api/v1/agent/trace/runs/conv-e2e/trace/chain-t")
        assert resp.status_code == 200

        data = resp.json()
        assert data["trace_id"] == "chain-t"
        assert data["total"] == 2
        assert data["runs"][0]["run_id"] == "r-early"
        assert data["runs"][1]["run_id"] == "r-late"

    def test_get_single_run_with_trace(
        self,
        client: TestClient,
        mock_registry: MagicMock,
    ) -> None:
        run = _make_run(
            run_id="r-single",
            trace_id="t-single",
            parent_span_id="s-single",
            status=SubAgentRunStatus.COMPLETED,
        )
        mock_registry.get_run.return_value = run

        resp = client.get("/api/v1/agent/trace/runs/conv-e2e/r-single")
        assert resp.status_code == 200

        data = resp.json()
        assert data["run_id"] == "r-single"
        assert data["trace_id"] == "t-single"
        assert data["parent_span_id"] == "s-single"

    def test_get_nonexistent_run_returns_404(
        self,
        client: TestClient,
        mock_registry: MagicMock,
    ) -> None:
        mock_registry.get_run.return_value = None

        resp = client.get("/api/v1/agent/trace/runs/conv-e2e/no-such-run")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# E2E: Cross-component — SubAgentRun + namespace + credential + span + API
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCrossComponentE2E:
    async def test_run_with_trace_through_namespace_and_credential(self) -> None:
        from src.infrastructure.adapters.secondary.cache.redis_agent_credential_scope import (
            RedisAgentCredentialScopeAdapter,
        )
        from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
            RedisAgentNamespaceAdapter,
        )

        run = _make_run(trace_id="t-cross", parent_span_id="s-cross")
        assert run.trace_id == "t-cross"

        redis = _make_redis_mock()
        ns_adapter = RedisAgentNamespaceAdapter(redis=redis, default_ttl_seconds=3600)
        await ns_adapter.set_key("proj-1", run.subagent_name, "run_id", run.run_id)
        redis.set.assert_awaited_once_with(
            f"agent:ns:proj-1:{run.subagent_name}:run_id",
            run.run_id,
            ex=3600,
        )

        cred_redis = _make_redis_mock()
        enc = _make_encryption_mock()
        cred_adapter = RedisAgentCredentialScopeAdapter(
            redis=cred_redis, encryption_service=enc, default_ttl_seconds=3600
        )
        await cred_adapter.set_credential("proj-1", run.subagent_name, "api_key", "secret")
        enc.encrypt.assert_called_once_with("secret")

        resp = run_to_response(run)
        assert resp.trace_id == "t-cross"
        assert resp.run_id == run.run_id

    async def test_span_service_with_traced_run_and_api_response(self) -> None:
        from src.infrastructure.agent.subagent.span_service import SubAgentSpanService

        run = _make_run(trace_id="t-span-api", parent_span_id="s-span-api")
        svc = SubAgentSpanService()

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=_make_mock_tracer(),
        ):
            async with svc.trace_run(run) as span:
                assert span is not None
                span.set_attribute.assert_any_call("subagent.trace_id", "t-span-api")

                svc.mark_span_completed(span, summary="done", tokens_used=50)
                span.set_attribute.assert_any_call("subagent.summary", "done")
                span.set_attribute.assert_any_call("subagent.tokens_used", 50)

        resp = run_to_response(run)
        assert resp.trace_id == "t-span-api"
        assert resp.parent_span_id == "s-span-api"
        assert resp.status == "pending"

    async def test_full_lifecycle_run_through_all_layers(self) -> None:
        from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
            RedisAgentNamespaceAdapter,
        )
        from src.infrastructure.agent.subagent.span_service import SubAgentSpanService

        run = SubAgentRun(
            run_id="run-full",
            conversation_id="conv-full",
            subagent_name="planner",
            task="plan project",
        )
        run = run.with_trace_context("t-full-lifecycle", "s-parent")

        redis = _make_redis_mock()
        ns = RedisAgentNamespaceAdapter(redis=redis, default_ttl_seconds=3600)
        await ns.set_key("proj-1", "planner", "current_run", run.run_id)

        svc = SubAgentSpanService()
        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=_make_mock_tracer(),
        ):
            async with svc.trace_run(run) as span:
                run = run.start()
                assert run.status == SubAgentRunStatus.RUNNING
                assert run.trace_id == "t-full-lifecycle"

                run = run.complete(summary="plan created", tokens_used=300, execution_time_ms=2000)
                assert run.status == SubAgentRunStatus.COMPLETED

                if span is not None:
                    svc.mark_span_completed(
                        span,
                        summary="plan created",
                        tokens_used=300,
                        execution_time_ms=2000,
                    )

        resp = run_to_response(run)
        assert resp.trace_id == "t-full-lifecycle"
        assert resp.parent_span_id == "s-parent"
        assert resp.status == "completed"
        assert resp.summary == "plan created"
        assert resp.tokens_used == 300
        assert resp.execution_time_ms == 2000

        list_resp = SubAgentRunListResponse(
            conversation_id="conv-full",
            runs=[resp],
            total=1,
        )
        assert list_resp.total == 1
        assert list_resp.runs[0].trace_id == "t-full-lifecycle"
