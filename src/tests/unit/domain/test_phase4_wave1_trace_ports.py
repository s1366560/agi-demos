"""Tests for Phase 4 Wave 1: SubAgentRun trace context and isolation ports."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import runtime_checkable

import pytest

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.domain.ports.agent.agent_credential_scope_port import AgentCredentialScopePort
from src.domain.ports.agent.agent_namespace_port import AgentNamespacePort


# ---------------------------------------------------------------------------
# SubAgentRun trace fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentRunTraceFields:
    def _make_run(self, **overrides: object) -> SubAgentRun:
        defaults: dict[str, object] = {
            "conversation_id": "conv-1",
            "subagent_name": "researcher",
            "task": "find data",
        }
        defaults.update(overrides)
        return SubAgentRun(**defaults)  # type: ignore[arg-type]

    def test_trace_id_defaults_to_none(self) -> None:
        run = self._make_run()
        assert run.trace_id is None

    def test_parent_span_id_defaults_to_none(self) -> None:
        run = self._make_run()
        assert run.parent_span_id is None

    def test_trace_id_in_constructor(self) -> None:
        run = self._make_run(trace_id="abc123")
        assert run.trace_id == "abc123"

    def test_parent_span_id_in_constructor(self) -> None:
        run = self._make_run(parent_span_id="span-99")
        assert run.parent_span_id == "span-99"

    def test_trace_fields_preserved_through_start(self) -> None:
        run = self._make_run(trace_id="t1", parent_span_id="s1")
        started = run.start()
        assert started.trace_id == "t1"
        assert started.parent_span_id == "s1"

    def test_trace_fields_preserved_through_complete(self) -> None:
        run = self._make_run(trace_id="t2", parent_span_id="s2").start()
        completed = run.complete(summary="done")
        assert completed.trace_id == "t2"
        assert completed.parent_span_id == "s2"

    def test_trace_fields_preserved_through_fail(self) -> None:
        run = self._make_run(trace_id="t3", parent_span_id="s3").start()
        failed = run.fail(error="boom")
        assert failed.trace_id == "t3"
        assert failed.parent_span_id == "s3"

    def test_trace_fields_preserved_through_cancel(self) -> None:
        run = self._make_run(trace_id="t4", parent_span_id="s4")
        cancelled = run.cancel(reason="user cancelled")
        assert cancelled.trace_id == "t4"
        assert cancelled.parent_span_id == "s4"

    def test_trace_fields_preserved_through_time_out(self) -> None:
        run = self._make_run(trace_id="t5", parent_span_id="s5")
        timed_out = run.time_out()
        assert timed_out.trace_id == "t5"
        assert timed_out.parent_span_id == "s5"

    def test_trace_fields_in_event_data(self) -> None:
        run = self._make_run(trace_id="trace-abc", parent_span_id="span-xyz")
        data = run.to_event_data()
        assert data["trace_id"] == "trace-abc"
        assert data["parent_span_id"] == "span-xyz"

    def test_trace_fields_none_in_event_data(self) -> None:
        run = self._make_run()
        data = run.to_event_data()
        assert data["trace_id"] is None
        assert data["parent_span_id"] is None

    def test_frozen_immutability_trace_id(self) -> None:
        run = self._make_run(trace_id="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            run.trace_id = "changed"  # type: ignore[misc]

    def test_frozen_immutability_parent_span_id(self) -> None:
        run = self._make_run(parent_span_id="y")
        with pytest.raises(dataclasses.FrozenInstanceError):
            run.parent_span_id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SubAgentRun.with_trace_context()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentRunWithTraceContext:
    def _make_run(self, **overrides: object) -> SubAgentRun:
        defaults: dict[str, object] = {
            "conversation_id": "conv-1",
            "subagent_name": "researcher",
            "task": "find data",
        }
        defaults.update(overrides)
        return SubAgentRun(**defaults)  # type: ignore[arg-type]

    def test_attach_trace_context_on_pending(self) -> None:
        run = self._make_run()
        updated = run.with_trace_context(trace_id="t1", parent_span_id="s1")
        assert updated.trace_id == "t1"
        assert updated.parent_span_id == "s1"

    def test_attach_trace_context_without_parent_span(self) -> None:
        run = self._make_run()
        updated = run.with_trace_context(trace_id="t1")
        assert updated.trace_id == "t1"
        assert updated.parent_span_id is None

    def test_returns_new_instance(self) -> None:
        run = self._make_run()
        updated = run.with_trace_context(trace_id="t1")
        assert updated is not run
        assert run.trace_id is None

    def test_rejects_empty_trace_id(self) -> None:
        run = self._make_run()
        with pytest.raises(ValueError, match="trace_id cannot be empty"):
            run.with_trace_context(trace_id="")

    def test_rejects_whitespace_trace_id(self) -> None:
        run = self._make_run()
        with pytest.raises(ValueError, match="trace_id cannot be empty"):
            run.with_trace_context(trace_id="   ")

    def test_rejects_running_status(self) -> None:
        run = self._make_run().start()
        with pytest.raises(ValueError, match="must be pending"):
            run.with_trace_context(trace_id="t1")

    def test_rejects_completed_status(self) -> None:
        run = self._make_run().start().complete(summary="done")
        with pytest.raises(ValueError, match="must be pending"):
            run.with_trace_context(trace_id="t1")

    def test_rejects_failed_status(self) -> None:
        run = self._make_run().start().fail(error="err")
        with pytest.raises(ValueError, match="must be pending"):
            run.with_trace_context(trace_id="t1")

    def test_rejects_cancelled_status(self) -> None:
        run = self._make_run().cancel()
        with pytest.raises(ValueError, match="must be pending"):
            run.with_trace_context(trace_id="t1")

    def test_rejects_timed_out_status(self) -> None:
        run = self._make_run().time_out()
        with pytest.raises(ValueError, match="must be pending"):
            run.with_trace_context(trace_id="t1")

    def test_preserves_other_fields(self) -> None:
        run = self._make_run(run_id="r1")
        updated = run.with_trace_context(trace_id="t1", parent_span_id="s1")
        assert updated.run_id == "r1"
        assert updated.conversation_id == "conv-1"
        assert updated.subagent_name == "researcher"
        assert updated.task == "find data"
        assert updated.status == SubAgentRunStatus.PENDING

    def test_overwrite_existing_trace_context(self) -> None:
        run = self._make_run(trace_id="old-trace", parent_span_id="old-span")
        updated = run.with_trace_context(trace_id="new-trace", parent_span_id="new-span")
        assert updated.trace_id == "new-trace"
        assert updated.parent_span_id == "new-span"


# ---------------------------------------------------------------------------
# AgentNamespacePort — Protocol conformance
# ---------------------------------------------------------------------------


@dataclass
class _StubNamespaceAdapter:
    store: dict[str, str] = dataclasses.field(default_factory=dict)

    async def get_key(self, project_id: str, agent_id: str, key: str) -> str | None:
        return self.store.get(f"{project_id}:{agent_id}:{key}")

    async def set_key(
        self,
        project_id: str,
        agent_id: str,
        key: str,
        value: str,
        ttl_seconds: int | None = None,
    ) -> None:
        self.store[f"{project_id}:{agent_id}:{key}"] = value

    async def delete_key(self, project_id: str, agent_id: str, key: str) -> bool:
        k = f"{project_id}:{agent_id}:{key}"
        if k in self.store:
            del self.store[k]
            return True
        return False

    async def list_keys(self, project_id: str, agent_id: str, pattern: str = "*") -> list[str]:
        prefix = f"{project_id}:{agent_id}:"
        return [k.removeprefix(prefix) for k in self.store if k.startswith(prefix)]

    async def clear_namespace(self, project_id: str, agent_id: str) -> int:
        prefix = f"{project_id}:{agent_id}:"
        to_del = [k for k in self.store if k.startswith(prefix)]
        for k in to_del:
            del self.store[k]
        return len(to_del)

    async def get_many(
        self, project_id: str, agent_id: str, keys: list[str]
    ) -> dict[str, str | None]:
        return {k: self.store.get(f"{project_id}:{agent_id}:{k}") for k in keys}

    async def set_many(
        self,
        project_id: str,
        agent_id: str,
        mapping: dict[str, str],
        ttl_seconds: int | None = None,
    ) -> None:
        for k, v in mapping.items():
            self.store[f"{project_id}:{agent_id}:{k}"] = v


@pytest.mark.unit
class TestAgentNamespacePortConformance:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_StubNamespaceAdapter(), AgentNamespacePort)

    def test_protocol_is_runtime_checkable_decorator(self) -> None:
        assert runtime_checkable in (
            getattr(AgentNamespacePort, "__protocol_attrs__", None),
        ) or hasattr(AgentNamespacePort, "__protocol_attrs__")

    async def test_get_set_key(self) -> None:
        adapter = _StubNamespaceAdapter()
        await adapter.set_key("p1", "a1", "foo", "bar")
        result = await adapter.get_key("p1", "a1", "foo")
        assert result == "bar"

    async def test_get_nonexistent_key(self) -> None:
        adapter = _StubNamespaceAdapter()
        result = await adapter.get_key("p1", "a1", "missing")
        assert result is None

    async def test_delete_key_returns_true_when_exists(self) -> None:
        adapter = _StubNamespaceAdapter()
        await adapter.set_key("p1", "a1", "k", "v")
        assert await adapter.delete_key("p1", "a1", "k") is True

    async def test_delete_key_returns_false_when_missing(self) -> None:
        adapter = _StubNamespaceAdapter()
        assert await adapter.delete_key("p1", "a1", "k") is False

    async def test_list_keys(self) -> None:
        adapter = _StubNamespaceAdapter()
        await adapter.set_key("p1", "a1", "k1", "v1")
        await adapter.set_key("p1", "a1", "k2", "v2")
        keys = await adapter.list_keys("p1", "a1")
        assert sorted(keys) == ["k1", "k2"]

    async def test_clear_namespace(self) -> None:
        adapter = _StubNamespaceAdapter()
        await adapter.set_key("p1", "a1", "k1", "v1")
        await adapter.set_key("p1", "a1", "k2", "v2")
        count = await adapter.clear_namespace("p1", "a1")
        assert count == 2
        assert await adapter.get_key("p1", "a1", "k1") is None

    async def test_namespace_isolation(self) -> None:
        adapter = _StubNamespaceAdapter()
        await adapter.set_key("p1", "a1", "k", "v1")
        await adapter.set_key("p1", "a2", "k", "v2")
        assert await adapter.get_key("p1", "a1", "k") == "v1"
        assert await adapter.get_key("p1", "a2", "k") == "v2"

    async def test_get_many(self) -> None:
        adapter = _StubNamespaceAdapter()
        await adapter.set_key("p1", "a1", "k1", "v1")
        result = await adapter.get_many("p1", "a1", ["k1", "k2"])
        assert result == {"k1": "v1", "k2": None}

    async def test_set_many(self) -> None:
        adapter = _StubNamespaceAdapter()
        await adapter.set_many("p1", "a1", {"k1": "v1", "k2": "v2"})
        assert await adapter.get_key("p1", "a1", "k1") == "v1"
        assert await adapter.get_key("p1", "a1", "k2") == "v2"


# ---------------------------------------------------------------------------
# AgentCredentialScopePort — Protocol conformance
# ---------------------------------------------------------------------------


@dataclass
class _StubCredentialScopeAdapter:
    store: dict[str, str] = dataclasses.field(default_factory=dict)

    async def get_credential(
        self, project_id: str, agent_id: str, credential_key: str
    ) -> str | None:
        return self.store.get(f"{project_id}:{agent_id}:{credential_key}")

    async def set_credential(
        self,
        project_id: str,
        agent_id: str,
        credential_key: str,
        credential_value: str,
        ttl_seconds: int | None = None,
    ) -> None:
        self.store[f"{project_id}:{agent_id}:{credential_key}"] = credential_value

    async def delete_credential(self, project_id: str, agent_id: str, credential_key: str) -> bool:
        k = f"{project_id}:{agent_id}:{credential_key}"
        if k in self.store:
            del self.store[k]
            return True
        return False

    async def list_credential_keys(self, project_id: str, agent_id: str) -> list[str]:
        prefix = f"{project_id}:{agent_id}:"
        return [k.removeprefix(prefix) for k in self.store if k.startswith(prefix)]

    async def has_credential(self, project_id: str, agent_id: str, credential_key: str) -> bool:
        return f"{project_id}:{agent_id}:{credential_key}" in self.store

    async def clear_credentials(self, project_id: str, agent_id: str) -> int:
        prefix = f"{project_id}:{agent_id}:"
        to_del = [k for k in self.store if k.startswith(prefix)]
        for k in to_del:
            del self.store[k]
        return len(to_del)


@pytest.mark.unit
class TestAgentCredentialScopePortConformance:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_StubCredentialScopeAdapter(), AgentCredentialScopePort)

    async def test_get_set_credential(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        await adapter.set_credential("p1", "a1", "api_key", "secret123")
        result = await adapter.get_credential("p1", "a1", "api_key")
        assert result == "secret123"

    async def test_get_nonexistent_credential(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        result = await adapter.get_credential("p1", "a1", "missing")
        assert result is None

    async def test_delete_credential_returns_true(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        await adapter.set_credential("p1", "a1", "k", "v")
        assert await adapter.delete_credential("p1", "a1", "k") is True

    async def test_delete_credential_returns_false(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        assert await adapter.delete_credential("p1", "a1", "k") is False

    async def test_list_credential_keys(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        await adapter.set_credential("p1", "a1", "key1", "v1")
        await adapter.set_credential("p1", "a1", "key2", "v2")
        keys = await adapter.list_credential_keys("p1", "a1")
        assert sorted(keys) == ["key1", "key2"]

    async def test_has_credential_true(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        await adapter.set_credential("p1", "a1", "k", "v")
        assert await adapter.has_credential("p1", "a1", "k") is True

    async def test_has_credential_false(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        assert await adapter.has_credential("p1", "a1", "k") is False

    async def test_clear_credentials(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        await adapter.set_credential("p1", "a1", "k1", "v1")
        await adapter.set_credential("p1", "a1", "k2", "v2")
        count = await adapter.clear_credentials("p1", "a1")
        assert count == 2
        assert await adapter.get_credential("p1", "a1", "k1") is None

    async def test_credential_isolation_between_agents(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        await adapter.set_credential("p1", "a1", "token", "secret-a1")
        await adapter.set_credential("p1", "a2", "token", "secret-a2")
        assert await adapter.get_credential("p1", "a1", "token") == "secret-a1"
        assert await adapter.get_credential("p1", "a2", "token") == "secret-a2"

    async def test_credential_isolation_between_projects(self) -> None:
        adapter = _StubCredentialScopeAdapter()
        await adapter.set_credential("p1", "a1", "token", "secret-p1")
        await adapter.set_credential("p2", "a1", "token", "secret-p2")
        assert await adapter.get_credential("p1", "a1", "token") == "secret-p1"
        assert await adapter.get_credential("p2", "a1", "token") == "secret-p2"
