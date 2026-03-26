"""Tests for Phase 3 Wave 2: RoutingContext VO, domain ports, and events."""

from __future__ import annotations

import dataclasses
from typing import runtime_checkable

import pytest

from src.domain.events.agent_events import (
    ContextCompactedEvent,
    SessionForkedEvent,
    SessionMergedEvent,
)
from src.domain.events.types import EVENT_CATEGORIES, AgentEventType, EventCategory
from src.domain.model.agent.routing_context import RoutingContext
from src.domain.ports.agent.context_engine_port import ContextEnginePort
from src.domain.ports.agent.message_router_port import MessageRouterPort


@pytest.mark.unit
class TestRoutingContext:
    def test_creation_with_required_fields(self) -> None:
        rc = RoutingContext(
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        assert rc.conversation_id == "conv-1"
        assert rc.project_id == "proj-1"
        assert rc.tenant_id == "tenant-1"

    def test_default_channel_type(self) -> None:
        rc = RoutingContext(
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        assert rc.channel_type == "web"

    def test_default_parent_conversation_id_is_none(self) -> None:
        rc = RoutingContext(
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        assert rc.parent_conversation_id is None

    def test_custom_channel_type(self) -> None:
        rc = RoutingContext(
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            channel_type="feishu",
        )
        assert rc.channel_type == "feishu"

    def test_with_parent_conversation_id(self) -> None:
        rc = RoutingContext(
            conversation_id="child-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            parent_conversation_id="parent-1",
        )
        assert rc.parent_conversation_id == "parent-1"

    def test_frozen_immutability(self) -> None:
        rc = RoutingContext(
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rc.conversation_id = "changed"  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        rc1 = RoutingContext(
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        rc2 = RoutingContext(
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        assert rc1 == rc2

    def test_inequality_on_different_values(self) -> None:
        rc1 = RoutingContext(
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        rc2 = RoutingContext(
            conversation_id="conv-2",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        assert rc1 != rc2


@pytest.mark.unit
class TestContextEnginePort:
    def test_is_runtime_checkable(self) -> None:
        assert (
            getattr(ContextEnginePort, "__protocol_attrs__", None) is not None
            or hasattr(ContextEnginePort, "__callable_proto_members_only__")
            or runtime_checkable
        )

    def test_has_on_message_ingest(self) -> None:
        assert hasattr(ContextEnginePort, "on_message_ingest")

    def test_has_assemble_context(self) -> None:
        assert hasattr(ContextEnginePort, "assemble_context")

    def test_has_compact_context(self) -> None:
        assert hasattr(ContextEnginePort, "compact_context")

    def test_has_after_turn(self) -> None:
        assert hasattr(ContextEnginePort, "after_turn")

    def test_has_on_subagent_ended(self) -> None:
        assert hasattr(ContextEnginePort, "on_subagent_ended")

    def test_method_count(self) -> None:
        methods = [
            m
            for m in dir(ContextEnginePort)
            if not m.startswith("_") and callable(getattr(ContextEnginePort, m, None))
        ]
        assert len(methods) == 5


@pytest.mark.unit
class TestMessageRouterPort:
    def test_has_resolve_agent(self) -> None:
        assert hasattr(MessageRouterPort, "resolve_agent")

    def test_has_register_binding(self) -> None:
        assert hasattr(MessageRouterPort, "register_binding")

    def test_has_remove_binding(self) -> None:
        assert hasattr(MessageRouterPort, "remove_binding")

    def test_method_count(self) -> None:
        methods = [
            m
            for m in dir(MessageRouterPort)
            if not m.startswith("_") and callable(getattr(MessageRouterPort, m, None))
        ]
        assert len(methods) == 3


@pytest.mark.unit
class TestContextCompactedEvent:
    def test_creation(self) -> None:
        event = ContextCompactedEvent(
            conversation_id="conv-1",
            before_tokens=8000,
            after_tokens=4000,
        )
        assert event.conversation_id == "conv-1"
        assert event.before_tokens == 8000
        assert event.after_tokens == 4000
        assert event.event_type == AgentEventType.CONTEXT_COMPACTED

    def test_frozen(self) -> None:
        event = ContextCompactedEvent(
            conversation_id="conv-1",
            before_tokens=8000,
            after_tokens=4000,
        )
        with pytest.raises(Exception):
            event.before_tokens = 999

    def test_to_event_dict(self) -> None:
        event = ContextCompactedEvent(
            conversation_id="conv-1",
            before_tokens=8000,
            after_tokens=4000,
        )
        d = event.to_event_dict()
        assert d["type"] == "context_compacted"
        assert d["data"]["conversation_id"] == "conv-1"
        assert d["data"]["before_tokens"] == 8000
        assert d["data"]["after_tokens"] == 4000
        assert "event_type" not in d["data"]
        assert "timestamp" not in d["data"]
        assert "timestamp" in d


@pytest.mark.unit
class TestSessionForkedEvent:
    def test_creation(self) -> None:
        event = SessionForkedEvent(
            parent_conversation_id="parent-1",
            child_conversation_id="child-1",
        )
        assert event.parent_conversation_id == "parent-1"
        assert event.child_conversation_id == "child-1"
        assert event.event_type == AgentEventType.SESSION_FORKED

    def test_frozen(self) -> None:
        event = SessionForkedEvent(
            parent_conversation_id="parent-1",
            child_conversation_id="child-1",
        )
        with pytest.raises(Exception):
            event.parent_conversation_id = "changed"

    def test_to_event_dict(self) -> None:
        event = SessionForkedEvent(
            parent_conversation_id="parent-1",
            child_conversation_id="child-1",
        )
        d = event.to_event_dict()
        assert d["type"] == "session_forked"
        assert d["data"]["parent_conversation_id"] == "parent-1"
        assert d["data"]["child_conversation_id"] == "child-1"
        assert "event_type" not in d["data"]
        assert "timestamp" not in d["data"]


@pytest.mark.unit
class TestSessionMergedEvent:
    def test_creation(self) -> None:
        event = SessionMergedEvent(
            parent_conversation_id="parent-1",
            child_conversation_id="child-1",
            merge_strategy="result_only",
        )
        assert event.parent_conversation_id == "parent-1"
        assert event.child_conversation_id == "child-1"
        assert event.merge_strategy == "result_only"
        assert event.event_type == AgentEventType.SESSION_MERGED

    def test_frozen(self) -> None:
        event = SessionMergedEvent(
            parent_conversation_id="parent-1",
            child_conversation_id="child-1",
            merge_strategy="summary",
        )
        with pytest.raises(Exception):
            event.merge_strategy = "changed"

    def test_to_event_dict(self) -> None:
        event = SessionMergedEvent(
            parent_conversation_id="parent-1",
            child_conversation_id="child-1",
            merge_strategy="full_history",
        )
        d = event.to_event_dict()
        assert d["type"] == "session_merged"
        assert d["data"]["parent_conversation_id"] == "parent-1"
        assert d["data"]["child_conversation_id"] == "child-1"
        assert d["data"]["merge_strategy"] == "full_history"
        assert "event_type" not in d["data"]
        assert "timestamp" not in d["data"]


@pytest.mark.unit
class TestPhase3Wave2EventTypes:
    def test_context_compacted_enum_exists(self) -> None:
        assert AgentEventType.CONTEXT_COMPACTED.value == "context_compacted"

    def test_session_forked_enum_exists(self) -> None:
        assert AgentEventType.SESSION_FORKED.value == "session_forked"

    def test_session_merged_enum_exists(self) -> None:
        assert AgentEventType.SESSION_MERGED.value == "session_merged"

    def test_context_compacted_category(self) -> None:
        assert EVENT_CATEGORIES[AgentEventType.CONTEXT_COMPACTED] == EventCategory.SYSTEM

    def test_session_forked_category(self) -> None:
        assert EVENT_CATEGORIES[AgentEventType.SESSION_FORKED] == EventCategory.AGENT

    def test_session_merged_category(self) -> None:
        assert EVENT_CATEGORIES[AgentEventType.SESSION_MERGED] == EventCategory.AGENT


@pytest.mark.unit
class TestPhase3Wave2Exports:
    def test_routing_context_importable_from_agent_init(self) -> None:
        from src.domain.model.agent import RoutingContext as RoutingContextAlias

        assert RoutingContextAlias is RoutingContext

    def test_context_engine_port_importable_from_ports_init(self) -> None:
        from src.domain.ports.agent import ContextEnginePort as ContextEnginePortAlias

        assert ContextEnginePortAlias is ContextEnginePort

    def test_message_router_port_importable_from_ports_init(self) -> None:
        from src.domain.ports.agent import MessageRouterPort as MessageRouterPortAlias

        assert MessageRouterPortAlias is MessageRouterPort

    def test_events_in_all_export(self) -> None:
        from src.domain.events import agent_events

        assert "ContextCompactedEvent" in agent_events.__all__
        assert "SessionForkedEvent" in agent_events.__all__
        assert "SessionMergedEvent" in agent_events.__all__
