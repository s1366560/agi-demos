from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    ActiveRunCountResponse,
    DescendantTreeResponse,
    SubAgentRunListResponse,
    SubAgentRunResponse,
    TraceChainResponse,
)
from src.infrastructure.adapters.primary.web.routers.agent.trace_router import (
    parse_statuses,
    router,
    run_to_response,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

# --- Fixtures ---


def _make_run(
    *,
    run_id: str = "run-1",
    conversation_id: str = "conv-1",
    subagent_name: str = "analyzer",
    task: str = "analyze data",
    status: SubAgentRunStatus = SubAgentRunStatus.COMPLETED,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    created_at: datetime | None = None,
) -> SubAgentRun:
    return SubAgentRun(
        run_id=run_id,
        conversation_id=conversation_id,
        subagent_name=subagent_name,
        task=task,
        status=status,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        created_at=created_at or datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def mock_registry():
    registry = MagicMock()
    registry.list_runs.return_value = []
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
    mock_db = MagicMock()

    test_app.dependency_overrides[get_current_user] = lambda: mock_user
    test_app.dependency_overrides[get_db] = lambda: mock_db

    test_app.include_router(router, prefix="/api/v1/agent/trace")
    return test_app


@pytest.fixture
def client(app: FastAPI):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _patch_container_helper(mock_container: MagicMock):
    with patch(
        "src.infrastructure.adapters.primary.web.routers.agent.trace_router.get_container_with_db",
        return_value=mock_container,
    ):
        yield


# --- Helper Tests ---


@pytest.mark.unit
class TestRunToResponse:
    def test_converts_completed_run(self) -> None:
        run = _make_run(trace_id="t-1", parent_span_id="span-1")
        resp = run_to_response(run)
        assert isinstance(resp, SubAgentRunResponse)
        assert resp.run_id == "run-1"
        assert resp.conversation_id == "conv-1"
        assert resp.subagent_name == "analyzer"
        assert resp.status == "completed"
        assert resp.trace_id == "t-1"
        assert resp.parent_span_id == "span-1"

    def test_converts_pending_run_with_nulls(self) -> None:
        run = _make_run(status=SubAgentRunStatus.PENDING)
        resp = run_to_response(run)
        assert resp.status == "pending"
        assert resp.started_at is None
        assert resp.ended_at is None
        assert resp.trace_id is None
        assert resp.parent_span_id is None

    def test_preserves_metadata(self) -> None:
        run = _make_run()
        resp = run_to_response(run)
        assert isinstance(resp.metadata, dict)


@pytest.mark.unit
class TestParseStatuses:
    def test_none_returns_none(self) -> None:
        assert parse_statuses(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_statuses("") is None

    def test_single_status(self) -> None:
        result = parse_statuses("running")
        assert result == [SubAgentRunStatus.RUNNING]

    def test_multiple_statuses(self) -> None:
        result = parse_statuses("running,completed,failed")
        assert result is not None
        assert len(result) == 3
        assert SubAgentRunStatus.RUNNING in result
        assert SubAgentRunStatus.COMPLETED in result
        assert SubAgentRunStatus.FAILED in result

    def test_whitespace_handling(self) -> None:
        result = parse_statuses(" running , completed ")
        assert result is not None
        assert len(result) == 2

    def test_invalid_status_raises_http_exception(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            parse_statuses("invalid_status")
        assert exc_info.value.status_code == 400
        assert "Invalid status filter value" in str(exc_info.value.detail)


# --- Schema Tests ---


@pytest.mark.unit
class TestSchemaModels:
    def test_subagent_run_response_defaults(self) -> None:
        resp = SubAgentRunResponse(
            run_id="r1",
            conversation_id="c1",
            subagent_name="a",
            task="t",
            status="pending",
            created_at="2026-01-01T00:00:00",
        )
        assert resp.started_at is None
        assert resp.trace_id is None
        assert resp.metadata == {}

    def test_subagent_run_list_response(self) -> None:
        resp = SubAgentRunListResponse(conversation_id="c1", runs=[], total=0)
        assert resp.total == 0
        assert resp.runs == []

    def test_trace_chain_response(self) -> None:
        resp = TraceChainResponse(trace_id="t-1", conversation_id="c1", runs=[], total=0)
        assert resp.trace_id == "t-1"

    def test_descendant_tree_response(self) -> None:
        resp = DescendantTreeResponse(
            parent_run_id="r1", conversation_id="c1", descendants=[], total=0
        )
        assert resp.parent_run_id == "r1"

    def test_active_run_count_response(self) -> None:
        resp = ActiveRunCountResponse(active_count=5)
        assert resp.active_count == 5
        assert resp.conversation_id is None

    def test_active_run_count_response_with_conversation(self) -> None:
        resp = ActiveRunCountResponse(active_count=3, conversation_id="c1")
        assert resp.conversation_id == "c1"


# --- list_runs endpoint ---


@pytest.mark.unit
class TestListRunsEndpoint:
    def test_empty_list(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_runs.return_value = []
        resp = client.get("/api/v1/agent/trace/runs/conv-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"] == "conv-1"
        assert data["runs"] == []
        assert data["total"] == 0

    def test_returns_runs(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_runs.return_value = [
            _make_run(run_id="r1"),
            _make_run(run_id="r2", subagent_name="planner"),
        ]
        resp = client.get("/api/v1/agent/trace/runs/conv-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["runs"][0]["run_id"] == "r1"
        assert data["runs"][1]["run_id"] == "r2"

    def test_status_filter_passed_to_registry(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        mock_registry.list_runs.return_value = []
        client.get("/api/v1/agent/trace/runs/conv-1?status=running,completed")
        args, kwargs = mock_registry.list_runs.call_args
        assert args[0] == "conv-1"
        statuses = kwargs.get("statuses") or args[1] if len(args) > 1 else kwargs.get("statuses")
        assert statuses is not None
        assert SubAgentRunStatus.RUNNING in statuses

    def test_trace_id_filter(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_runs.return_value = [
            _make_run(run_id="r1", trace_id="trace-abc"),
            _make_run(run_id="r2", trace_id="trace-xyz"),
            _make_run(run_id="r3", trace_id=None),
        ]
        resp = client.get("/api/v1/agent/trace/runs/conv-1?trace_id=trace-abc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["runs"][0]["run_id"] == "r1"
        assert data["runs"][0]["trace_id"] == "trace-abc"

    def test_invalid_status_returns_400(self, client: TestClient) -> None:
        resp = client.get("/api/v1/agent/trace/runs/conv-1?status=bogus")
        assert resp.status_code == 400

    def test_internal_error_returns_500(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_runs.side_effect = RuntimeError("boom")
        resp = client.get("/api/v1/agent/trace/runs/conv-1")
        assert resp.status_code == 500


# --- get_run endpoint ---


@pytest.mark.unit
class TestGetRunEndpoint:
    def test_run_found(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.get_run.return_value = _make_run(run_id="r1", trace_id="t-1")
        resp = client.get("/api/v1/agent/trace/runs/conv-1/r1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "r1"
        assert data["trace_id"] == "t-1"

    def test_run_not_found_returns_404(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.get_run.return_value = None
        resp = client.get("/api/v1/agent/trace/runs/conv-1/nonexistent")
        assert resp.status_code == 404

    def test_internal_error_returns_500(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.get_run.side_effect = RuntimeError("boom")
        resp = client.get("/api/v1/agent/trace/runs/conv-1/r1")
        assert resp.status_code == 500


# --- get_trace_chain endpoint ---


@pytest.mark.unit
class TestGetTraceChainEndpoint:
    def test_returns_matching_runs_sorted(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        run_late = _make_run(
            run_id="r2",
            trace_id="t-1",
            created_at=datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC),
        )
        run_early = _make_run(
            run_id="r1",
            trace_id="t-1",
            created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        run_other = _make_run(run_id="r3", trace_id="t-other")
        mock_registry.list_runs.return_value = [run_late, run_early, run_other]

        resp = client.get("/api/v1/agent/trace/runs/conv-1/trace/t-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "t-1"
        assert data["total"] == 2
        assert data["runs"][0]["run_id"] == "r1"
        assert data["runs"][1]["run_id"] == "r2"

    def test_empty_chain(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_runs.return_value = []
        resp = client.get("/api/v1/agent/trace/runs/conv-1/trace/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["runs"] == []

    def test_internal_error_returns_500(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_runs.side_effect = RuntimeError("boom")
        resp = client.get("/api/v1/agent/trace/runs/conv-1/trace/t-1")
        assert resp.status_code == 500


# --- get_descendants endpoint ---


@pytest.mark.unit
class TestGetDescendantsEndpoint:
    def test_returns_descendants(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_descendant_runs.return_value = [
            _make_run(run_id="child-1"),
            _make_run(run_id="child-2"),
        ]
        resp = client.get("/api/v1/agent/trace/runs/conv-1/parent-1/descendants")
        assert resp.status_code == 200
        data = resp.json()
        assert data["parent_run_id"] == "parent-1"
        assert data["total"] == 2

    def test_include_terminal_default_true(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        mock_registry.list_descendant_runs.return_value = []
        client.get("/api/v1/agent/trace/runs/conv-1/r1/descendants")
        _, kwargs = mock_registry.list_descendant_runs.call_args
        assert kwargs.get("include_terminal") is True

    def test_include_terminal_false(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_descendant_runs.return_value = []
        client.get("/api/v1/agent/trace/runs/conv-1/r1/descendants?include_terminal=false")
        _, kwargs = mock_registry.list_descendant_runs.call_args
        assert kwargs.get("include_terminal") is False

    def test_empty_descendants(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_descendant_runs.return_value = []
        resp = client.get("/api/v1/agent/trace/runs/conv-1/r1/descendants")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["descendants"] == []

    def test_internal_error_returns_500(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.list_descendant_runs.side_effect = RuntimeError("boom")
        resp = client.get("/api/v1/agent/trace/runs/conv-1/r1/descendants")
        assert resp.status_code == 500


# --- get_active_run_count endpoint ---


@pytest.mark.unit
class TestGetActiveRunCountEndpoint:
    def test_global_count(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.count_all_active_runs.return_value = 42
        resp = client.get("/api/v1/agent/trace/runs/active/count")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_count"] == 42
        assert data["conversation_id"] is None

    def test_per_conversation_count(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.count_active_runs.return_value = 3
        resp = client.get("/api/v1/agent/trace/runs/active/count?conversation_id=conv-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_count"] == 3
        assert data["conversation_id"] == "conv-1"

    def test_zero_count(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.count_all_active_runs.return_value = 0
        resp = client.get("/api/v1/agent/trace/runs/active/count")
        assert resp.status_code == 200
        assert resp.json()["active_count"] == 0

    def test_internal_error_returns_500(self, client: TestClient, mock_registry: MagicMock) -> None:
        mock_registry.count_all_active_runs.side_effect = RuntimeError("boom")
        resp = client.get("/api/v1/agent/trace/runs/active/count")
        assert resp.status_code == 500


# --- Route Conflict Tests ---


@pytest.mark.unit
class TestRouteOrdering:
    def test_active_count_not_confused_with_run_id(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        mock_registry.count_all_active_runs.return_value = 7
        resp = client.get("/api/v1/agent/trace/runs/active/count")
        assert resp.status_code == 200
        assert resp.json()["active_count"] == 7

    def test_trace_path_not_confused_with_run_id(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        mock_registry.list_runs.return_value = [_make_run(trace_id="t-1")]
        resp = client.get("/api/v1/agent/trace/runs/conv-1/trace/t-1")
        assert resp.status_code == 200
        assert resp.json()["trace_id"] == "t-1"
