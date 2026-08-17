"""Typed plugin event contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PluginEventMode(str, Enum):
    """Dispatch semantics owned by an event definition."""

    EMIT = "emit"
    WATERFALL = "waterfall"
    PARALLEL = "parallel"
    SERIAL = "serial"


class MissingNextPolicy(str, Enum):
    """Behavior when a waterfall listener returns without invoking ``next``."""

    ALLOW = "allow"
    CONTINUE = "continue"
    DENY = "deny"


@dataclass(frozen=True)
class EventDefinition:
    """One stable event name and its dispatch contract."""

    name: str
    mode: PluginEventMode
    missing_next_policy: MissingNextPolicy = MissingNextPolicy.ALLOW


PLATFORM_PLUGIN_EVENTS: frozenset[EventDefinition] = frozenset(
    {
        EventDefinition("agent.before_step", PluginEventMode.WATERFALL),
        EventDefinition("agent.before_request", PluginEventMode.WATERFALL),
        EventDefinition("llm.request", PluginEventMode.WATERFALL),
        EventDefinition(
            "tools.before_execute",
            PluginEventMode.WATERFALL,
            MissingNextPolicy.DENY,
        ),
        EventDefinition("tools.around_execute", PluginEventMode.WATERFALL),
        EventDefinition("tools.after_execute", PluginEventMode.SERIAL),
        EventDefinition("tools.result", PluginEventMode.EMIT),
        EventDefinition("agent.after_step", PluginEventMode.SERIAL),
        EventDefinition("agent.turn_stopping", PluginEventMode.SERIAL),
        EventDefinition("agent.after_turn", PluginEventMode.EMIT),
    }
)
