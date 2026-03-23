"""Layered tool-policy enforcement composing Global -> Agent -> SubAgent policies."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.application.services.tool_policy_resolver import (
    ToolPolicy as AppToolPolicy,
    ToolPolicyResolver,
)
from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.tool_policy import ToolPolicy as DomainToolPolicy

logger = logging.getLogger(__name__)

PRECEDENCE_GLOBAL = 300
PRECEDENCE_AGENT = 200
PRECEDENCE_SUBAGENT = 100


@dataclass(frozen=True)
class ToolDenialResult:
    allowed: bool
    denial_reason: str | None = None
    policy_layer: str | None = None


class LayeredToolPolicyService:
    """Composes tool-access policies from multiple governance layers.

    Layer precedence (highest evaluated first):
        1. Global / tenant-level (precedence=300)
        2. Agent-level       (precedence=200)
        3. SubAgent-level    (precedence=100)

    Uses the existing ``ToolPolicyResolver`` internally by converting
    domain ``ToolPolicy`` VOs into application-level ``ToolPolicy`` instances.
    """

    def __init__(
        self,
        global_denied: frozenset[str] | None = None,
        global_allowed: frozenset[str] | None = None,
    ) -> None:
        self._global_denied = global_denied or frozenset()
        self._global_allowed = global_allowed

    def is_tool_allowed(
        self,
        tool_name: str,
        agent: Agent | None = None,
        subagent: SubAgent | None = None,
    ) -> ToolDenialResult:
        resolver = self._build_resolver(agent, subagent)
        if resolver.is_allowed(tool_name):
            return ToolDenialResult(allowed=True)

        reason = resolver.get_denial_reason(tool_name) or "Denied by policy"
        layer = self._identify_denying_layer(tool_name, agent, subagent)
        return ToolDenialResult(
            allowed=False,
            denial_reason=reason,
            policy_layer=layer,
        )

    def filter_tools(
        self,
        tool_names: list[str],
        agent: Agent | None = None,
        subagent: SubAgent | None = None,
    ) -> list[str]:
        resolver = self._build_resolver(agent, subagent)
        return resolver.filter_tools(tool_names)

    def _build_resolver(
        self,
        agent: Agent | None,
        subagent: SubAgent | None,
    ) -> ToolPolicyResolver:
        resolver = ToolPolicyResolver()

        if self._global_denied or self._global_allowed is not None:
            resolver.register_policy(
                AppToolPolicy(
                    source="global",
                    precedence=PRECEDENCE_GLOBAL,
                    allowed=self._global_allowed,
                    denied=self._global_denied,
                )
            )

        if agent is not None and agent.tool_policy is not None:
            resolver.register_policy(
                _domain_to_app_policy(agent.tool_policy, "agent", PRECEDENCE_AGENT)
            )

        if subagent is not None and subagent.tool_policy is not None:
            resolver.register_policy(
                _domain_to_app_policy(subagent.tool_policy, "subagent", PRECEDENCE_SUBAGENT)
            )

        return resolver

    def _identify_denying_layer(
        self,
        tool_name: str,
        agent: Agent | None,
        subagent: SubAgent | None,
    ) -> str:
        if tool_name in self._global_denied:
            return "global"
        if self._global_allowed is not None and tool_name not in self._global_allowed:
            if "*" not in (self._global_allowed or frozenset()):
                return "global"

        if agent is not None and agent.tool_policy is not None:
            if not agent.tool_policy.is_allowed(tool_name):
                return "agent"

        if subagent is not None and subagent.tool_policy is not None:
            if not subagent.tool_policy.is_allowed(tool_name):
                return "subagent"

        return "unknown"


def _domain_to_app_policy(
    domain_policy: DomainToolPolicy,
    source: str,
    precedence: int,
) -> AppToolPolicy:
    allowed: frozenset[str] | None = None
    if domain_policy.allow:
        allowed = frozenset(domain_policy.allow)

    return AppToolPolicy(
        source=source,
        precedence=precedence,
        allowed=allowed,
        denied=frozenset(domain_policy.deny),
    )
