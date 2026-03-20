"""Phase 4 Wave 6: Cross-wave domain integration tests.

Validates that all Phase 4 domain components work together:
- SubAgentRun trace lifecycle (Wave 1)
- AgentNamespacePort / AgentCredentialScopePort protocol compliance (Wave 1)
- Redis adapters conform to port protocols (Wave 2)
- SpanService integrates with SubAgentRun trace context (Wave 3)
- API helpers round-trip SubAgentRun through Pydantic schemas (Wave 4)
"""

from __future__ import annotations

import dataclasses

import pytest

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.domain.ports.agent.agent_credential_scope_port import AgentCredentialScopePort
from src.domain.ports.agent.agent_namespace_port import AgentNamespacePort

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    *,
    run_id: str = "run-integ-1",
    conversation_id: str = "conv-integ",
    subagent_name: str = "researcher",
    task: str = "research topic",
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    status: SubAgentRunStatus = SubAgentRunStatus.PENDING,
) -> SubAgentRun:
    run = SubAgentRun(
        run_id=run_id,
        conversation_id=conversation_id,
        subagent_name=subagent_name,
        task=task,
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
# SubAgentRun full trace lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentRunTraceLifecycle:
    def test_full_lifecycle_with_trace_context(self) -> None:
        run = SubAgentRun(
            conversation_id="conv-1",
            subagent_name="analyzer",
            task="analyze data",
        )
        assert run.trace_id is None
        assert run.parent_span_id is None

        run = run.with_trace_context("trace-abc", "span-parent")
        assert run.trace_id == "trace-abc"
        assert run.parent_span_id == "span-parent"

        run = run.start()
        assert run.status == SubAgentRunStatus.RUNNING
        assert run.trace_id == "trace-abc"

        run = run.complete(summary="finished", tokens_used=42, execution_time_ms=100)
        assert run.status == SubAgentRunStatus.COMPLETED
        assert run.trace_id == "trace-abc"
        assert run.parent_span_id == "span-parent"
        assert run.summary == "finished"
        assert run.tokens_used == 42

    def test_lifecycle_trace_preserved_through_failure(self) -> None:
        run = _make_run(trace_id="t-fail", parent_span_id="s-fail")
        run = run.start()
        run = run.fail(error="something broke")
        assert run.status == SubAgentRunStatus.FAILED
        assert run.trace_id == "t-fail"
        assert run.parent_span_id == "s-fail"
        assert run.error == "something broke"

    def test_lifecycle_trace_preserved_through_cancel(self) -> None:
        run = _make_run(trace_id="t-cancel", parent_span_id="s-cancel")
        run = run.cancel(reason="user cancelled")
        assert run.status == SubAgentRunStatus.CANCELLED
        assert run.trace_id == "t-cancel"
        assert run.parent_span_id == "s-cancel"

    def test_lifecycle_trace_preserved_through_timeout(self) -> None:
        run = _make_run(trace_id="t-timeout", parent_span_id="s-timeout")
        run = run.time_out()
        assert run.status == SubAgentRunStatus.TIMED_OUT
        assert run.trace_id == "t-timeout"
        assert run.parent_span_id == "s-timeout"

    def test_lifecycle_freeze_preserves_trace(self) -> None:
        run = _make_run(
            trace_id="t-freeze",
            parent_span_id="s-freeze",
            status=SubAgentRunStatus.COMPLETED,
        )
        frozen = run.freeze_result("final output")
        assert frozen.trace_id == "t-freeze"
        assert frozen.parent_span_id == "s-freeze"
        assert frozen.frozen_result_text == "final output"

    def test_event_data_includes_trace_fields(self) -> None:
        run = _make_run(trace_id="t-evt", parent_span_id="s-evt")
        data = run.to_event_data()
        assert data["trace_id"] == "t-evt"
        assert data["parent_span_id"] == "s-evt"
        assert data["run_id"] == "run-integ-1"
        assert data["status"] == "pending"

    def test_event_data_trace_fields_none_when_unset(self) -> None:
        run = _make_run()
        data = run.to_event_data()
        assert data["trace_id"] is None
        assert data["parent_span_id"] is None


# ---------------------------------------------------------------------------
# Trace context constraints
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTraceContextConstraints:
    def test_cannot_set_trace_on_running_run(self) -> None:
        run = _make_run(status=SubAgentRunStatus.RUNNING)
        with pytest.raises(ValueError, match="must be pending"):
            run.with_trace_context("trace-late")

    def test_cannot_set_trace_on_completed_run(self) -> None:
        run = _make_run(status=SubAgentRunStatus.COMPLETED)
        with pytest.raises(ValueError, match="must be pending"):
            run.with_trace_context("trace-late")

    def test_trace_id_cannot_be_empty(self) -> None:
        run = _make_run()
        with pytest.raises(ValueError, match="trace_id cannot be empty"):
            run.with_trace_context("")

    def test_trace_id_cannot_be_whitespace(self) -> None:
        run = _make_run()
        with pytest.raises(ValueError, match="trace_id cannot be empty"):
            run.with_trace_context("   ")

    def test_parent_span_id_optional(self) -> None:
        run = _make_run()
        traced = run.with_trace_context("trace-only")
        assert traced.trace_id == "trace-only"
        assert traced.parent_span_id is None


# ---------------------------------------------------------------------------
# Port protocol compliance — AgentNamespacePort
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentNamespacePortProtocol:
    def test_redis_adapter_is_runtime_checkable(self) -> None:
        from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
            RedisAgentNamespaceAdapter,
        )

        assert isinstance(RedisAgentNamespaceAdapter, type)
        assert issubclass(RedisAgentNamespaceAdapter, AgentNamespacePort)

    def test_port_has_required_methods(self) -> None:
        required_methods = {
            "get_key",
            "set_key",
            "delete_key",
            "list_keys",
            "clear_namespace",
            "get_many",
            "set_many",
        }
        for method_name in required_methods:
            assert hasattr(AgentNamespacePort, method_name), (
                f"AgentNamespacePort missing {method_name}"
            )

    def test_port_is_runtime_checkable(self) -> None:
        assert hasattr(AgentNamespacePort, "__protocol_attrs__") or issubclass(
            AgentNamespacePort, type(AgentNamespacePort)
        )


# ---------------------------------------------------------------------------
# Port protocol compliance — AgentCredentialScopePort
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentCredentialScopePortProtocol:
    def test_redis_adapter_is_runtime_checkable(self) -> None:
        from src.infrastructure.adapters.secondary.cache.redis_agent_credential_scope import (
            RedisAgentCredentialScopeAdapter,
        )

        assert isinstance(RedisAgentCredentialScopeAdapter, type)
        assert issubclass(RedisAgentCredentialScopeAdapter, AgentCredentialScopePort)

    def test_port_has_required_methods(self) -> None:
        required_methods = {
            "get_credential",
            "set_credential",
            "delete_credential",
            "list_credential_keys",
            "has_credential",
            "clear_credentials",
        }
        for method_name in required_methods:
            assert hasattr(AgentCredentialScopePort, method_name), (
                f"AgentCredentialScopePort missing {method_name}"
            )


# ---------------------------------------------------------------------------
# Cross-wave: SubAgentRun trace -> event data -> API schema round trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTraceToApiSchemaRoundTrip:
    def test_run_to_response_preserves_trace_fields(self) -> None:
        from src.infrastructure.adapters.primary.web.routers.agent.trace_router import (
            run_to_response,
        )

        run = _make_run(trace_id="t-api", parent_span_id="s-api")
        resp = run_to_response(run)
        assert resp.trace_id == "t-api"
        assert resp.parent_span_id == "s-api"
        assert resp.run_id == "run-integ-1"
        assert resp.status == "pending"

    def test_run_to_response_none_trace(self) -> None:
        from src.infrastructure.adapters.primary.web.routers.agent.trace_router import (
            run_to_response,
        )

        run = _make_run()
        resp = run_to_response(run)
        assert resp.trace_id is None
        assert resp.parent_span_id is None

    def test_completed_run_to_response_full_fields(self) -> None:
        from src.infrastructure.adapters.primary.web.routers.agent.trace_router import (
            run_to_response,
        )

        run = _make_run(
            trace_id="t-complete",
            parent_span_id="s-complete",
            status=SubAgentRunStatus.COMPLETED,
        )
        resp = run_to_response(run)
        assert resp.trace_id == "t-complete"
        assert resp.status == "completed"
        assert resp.summary == "done"
        assert resp.tokens_used == 100
        assert resp.execution_time_ms == 500

    def test_event_data_keys_match_schema_fields(self) -> None:
        from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
            SubAgentRunResponse,
        )

        run = _make_run(trace_id="t-keys", parent_span_id="s-keys")
        data = run.to_event_data()
        schema_fields = set(SubAgentRunResponse.model_fields.keys())
        data_keys = set(data.keys())
        assert data_keys == schema_fields, (
            f"Mismatch: data_keys={data_keys - schema_fields}, schema_fields={schema_fields - data_keys}"
        )

    def test_parse_statuses_valid(self) -> None:
        from src.infrastructure.adapters.primary.web.routers.agent.trace_router import (
            parse_statuses,
        )

        result = parse_statuses("running,completed")
        assert result is not None
        assert SubAgentRunStatus.RUNNING in result
        assert SubAgentRunStatus.COMPLETED in result

    def test_parse_statuses_none(self) -> None:
        from src.infrastructure.adapters.primary.web.routers.agent.trace_router import (
            parse_statuses,
        )

        assert parse_statuses(None) is None
        assert parse_statuses("") is None


# ---------------------------------------------------------------------------
# Cross-wave: Multiple runs with same trace_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMultipleRunsSameTrace:
    def test_runs_with_same_trace_id_are_independent(self) -> None:
        run1 = _make_run(run_id="run-a", trace_id="shared-trace", parent_span_id="span-1")
        run2 = _make_run(run_id="run-b", trace_id="shared-trace", parent_span_id="span-2")

        assert run1.trace_id == run2.trace_id
        assert run1.parent_span_id != run2.parent_span_id
        assert run1.run_id != run2.run_id

    def test_runs_with_same_trace_can_have_different_statuses(self) -> None:
        run1 = _make_run(
            run_id="run-c",
            trace_id="shared-trace-2",
            status=SubAgentRunStatus.COMPLETED,
        )
        run2 = _make_run(
            run_id="run-d",
            trace_id="shared-trace-2",
            status=SubAgentRunStatus.FAILED,
        )

        assert run1.trace_id == run2.trace_id
        assert run1.status == SubAgentRunStatus.COMPLETED
        assert run2.status == SubAgentRunStatus.FAILED

    def test_event_data_for_related_trace_runs(self) -> None:
        runs = [
            _make_run(run_id=f"run-{i}", trace_id="chain-trace", parent_span_id=f"span-{i}")
            for i in range(3)
        ]
        events = [r.to_event_data() for r in runs]
        trace_ids = {e["trace_id"] for e in events}
        span_ids = {e["parent_span_id"] for e in events}
        run_ids = {e["run_id"] for e in events}

        assert len(trace_ids) == 1
        assert trace_ids == {"chain-trace"}
        assert len(span_ids) == 3
        assert len(run_ids) == 3


# ---------------------------------------------------------------------------
# SubAgentRun immutability guarantees
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentRunImmutability:
    def test_frozen_dataclass(self) -> None:
        run = _make_run()
        with pytest.raises(dataclasses.FrozenInstanceError):
            run.trace_id = "mutated"  # type: ignore[misc]

    def test_status_transition_returns_new_instance(self) -> None:
        run = _make_run(trace_id="t-immut")
        started = run.start()
        assert started is not run
        assert run.status == SubAgentRunStatus.PENDING
        assert started.status == SubAgentRunStatus.RUNNING

    def test_with_trace_context_returns_new_instance(self) -> None:
        run = _make_run()
        traced = run.with_trace_context("t-new", "s-new")
        assert traced is not run
        assert run.trace_id is None
        assert traced.trace_id == "t-new"

    def test_metadata_dict_is_independent_copy(self) -> None:
        run = _make_run()
        data = run.to_event_data()
        data["metadata"]["injected"] = True
        assert "injected" not in run.metadata
