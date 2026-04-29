"""M3 — capability-scored :class:`TaskAllocatorPort` implementation.

Replaces the dispatcher's pure round-robin with a weighted fit score:

    score = 0.5 * skill_match + 0.3 * tool_match + 0.1 * load_balance + 0.1 * affinity

Where each component is in ``[0, 1]``:

* ``skill_match`` — Jaccard overlap of node.recommended_capabilities ∩ agent.capabilities
* ``tool_match`` — substring/token match of capability names against agent.tool_names
* ``load_balance`` — ``1 / (1 + active_task_count)`` — prefer lightly-loaded agents
* ``affinity`` — +1 if ``node.preferred_agent_id == agent.agent_id`` else 0

Unavailable or leader agents are filtered upfront (leaders should verify, not
execute). Ties fall back to ``affinity_tags`` then alphabetical ``agent_id``
for deterministic behavior across ticks.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from src.domain.model.workspace_plan import PlanNode
from src.domain.ports.services.task_allocator_port import (
    Allocation,
    TaskAllocatorPort,
    WorkspaceAgent,
)

logger = logging.getLogger(__name__)

_DEFAULT_EXECUTION_CAPABILITIES = frozenset(
    {
        "backend",
        "codegen",
        "file_edit",
        "frontend",
        "shell",
        "software_development",
        "testing",
    }
)


class CapabilityAllocator(TaskAllocatorPort):
    """Weighted capability scorer; greedy one-node-per-tick assignment."""

    def __init__(
        self,
        skill_weight: float = 0.5,
        tool_weight: float = 0.3,
        load_weight: float = 0.1,
        affinity_weight: float = 0.1,
        min_score: float = 0.01,
    ) -> None:
        total = skill_weight + tool_weight + load_weight + affinity_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"allocator weights must sum to 1.0 (got {total:.3f})")
        self._ws = skill_weight
        self._wt = tool_weight
        self._wl = load_weight
        self._wa = affinity_weight
        self._min_score = min_score

    async def allocate(
        self,
        ready_nodes: list[PlanNode],
        pool: list[WorkspaceAgent],
    ) -> list[Allocation]:
        available = [a for a in pool if a.is_available and not a.is_leader]
        if not available:
            return []

        # Sort nodes by priority desc then id for determinism.
        ready_sorted = sorted(ready_nodes, key=lambda n: (-n.priority, n.id))
        load: dict[str, int] = {a.agent_id: a.active_task_count for a in available}
        out: list[Allocation] = []
        for node in ready_sorted:
            best_agent, best_score, reasons = self._best_agent(node, available, load)
            if best_agent is None or best_score < self._min_score:
                logger.debug(
                    "no agent for node %s (best=%s score=%.3f)",
                    node.id,
                    getattr(best_agent, "agent_id", None),
                    best_score,
                )
                continue
            out.append(
                Allocation(
                    node_id=node.id,
                    agent_id=best_agent.agent_id,
                    score=best_score,
                    reasons=tuple(reasons),
                )
            )
            # Bump synthetic load so next iteration balances.
            load[best_agent.agent_id] = load.get(best_agent.agent_id, 0) + 1
        return out

    # --- scoring --------------------------------------------------------

    def _best_agent(
        self,
        node: PlanNode,
        agents: Iterable[WorkspaceAgent],
        load: dict[str, int],
    ) -> tuple[WorkspaceAgent | None, float, list[str]]:
        best: tuple[WorkspaceAgent | None, float, list[str]] = (None, -1.0, [])
        for agent in agents:
            score, reasons = self._score(node, agent, load)
            key = (score, -agent.active_task_count, agent.agent_id)
            best_key = (
                best[1],
                -(load.get(best[0].agent_id, 0) if best[0] else 0),
                best[0].agent_id if best[0] else "",
            )
            if key > best_key:
                best = (agent, score, reasons)
        return best

    def _score(
        self,
        node: PlanNode,
        agent: WorkspaceAgent,
        load: dict[str, int],
    ) -> tuple[float, list[str]]:
        cap_names = {c.name for c in node.recommended_capabilities}
        reasons: list[str] = []

        skill = _jaccard(cap_names, agent.capabilities)
        if not cap_names:
            skill = _default_execution_fit(agent.capabilities)
        if skill > 0:
            reasons.append(f"skill={skill:.2f}")

        tool = _name_token_match(cap_names, agent.tool_names)
        if tool > 0:
            reasons.append(f"tool={tool:.2f}")

        lb = 1.0 / (1.0 + load.get(agent.agent_id, 0))
        reasons.append(f"load={lb:.2f}")

        aff = 0.0
        if node.preferred_agent_id and node.preferred_agent_id == agent.agent_id:
            aff = 1.0
            reasons.append("affinity:preferred")
        # Also match on persona tags (used by MetaGPT-style personas).
        for tag in agent.affinity_tags:
            if tag in cap_names or tag in node.description.lower():
                aff = max(aff, 0.7)
                reasons.append(f"affinity:tag:{tag}")
                break

        score = self._ws * skill + self._wt * tool + self._wl * lb + self._wa * aff
        return score, reasons


def _jaccard(a: set[str], b: Iterable[str]) -> float:
    bs = set(b)
    if not a and not bs:
        return 0.0
    inter = len(a & bs)
    uni = len(a | bs)
    return inter / uni if uni else 0.0


def _default_execution_fit(capabilities: Iterable[str]) -> float:
    caps = set(capabilities)
    if not caps:
        return 0.0
    return len(caps & _DEFAULT_EXECUTION_CAPABILITIES) / len(
        _DEFAULT_EXECUTION_CAPABILITIES
    )


def _name_token_match(caps: set[str], tools: Iterable[str]) -> float:
    """Fractional match: share of caps whose token appears in any tool name."""
    if not caps:
        return 0.0
    tool_set = {t.lower() for t in tools}
    hits = 0
    for c in caps:
        needle = c.lower().split(":", 1)[-1]
        if any(needle in t for t in tool_set):
            hits += 1
    return hits / len(caps)
