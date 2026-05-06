"""Lane experience service — JIT runtime guidance for the next specialist.

Distilled from routa's ``src/core/kanban/task-lane-experience.ts``. When a
card crosses a lane boundary, we synthesize a compact guidance snapshot
from:

- recent ``FrictionSignal`` events for the project,
- active ``Playbook`` entries whose ``TriggerPattern`` matches the current
  lane transition,
- the lane contract entry-gate state (which structural checks failed).

The snapshot is rendered into a single ``[Runtime Guidance]`` block that the
``SessionProcessor`` already injects into every LLM call (see
``_session_instructions``). Subjective verdicts stay with the agent — this
service only *projects* observed structural facts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.model.flow.playbook import Playbook, PlaybookStatus
from src.domain.model.lane_contract import (
    GateEvaluation,
    GateResult,
    LaneContract,
    evaluate_gate,
)
from src.domain.ports.repositories.friction_ledger import FrictionLedger
from src.domain.ports.repositories.playbook_repository import PlaybookRepository

DEFAULT_WINDOW = timedelta(hours=24)
MAX_FRICTION_BULLETS = 5
MAX_PLAYBOOK_BULLETS = 3


@dataclass(frozen=True, kw_only=True)
class LaneJitContext:
    """Compact, rendered guidance for the next specialist.

    All fields are pre-rendered strings so the processor can splice the
    block into ``_session_instructions`` without re-parsing.
    """

    lane_id: str
    headline: str
    bullets: tuple[str, ...] = field(default_factory=tuple)
    entry_gate: GateEvaluation | None = None
    matched_playbook_ids: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        """Render as a single ``[Runtime Guidance]``-friendly string."""
        lines = [self.headline]
        if self.entry_gate is not None and self.entry_gate.overall is GateResult.FAIL:
            lines.append(
                f"Entry gate FAIL for lane '{self.lane_id}'. Address gate "
                f"checks before producing new artifacts:"
            )
            for check_key, result, label in self.entry_gate.checks:
                if result is GateResult.FAIL:
                    lines.append(f"  - [{check_key}] {label}")
        for bullet in self.bullets:
            lines.append(f"- {bullet}")
        return "\n".join(lines)


class LaneExperienceService:
    """Projects friction + playbooks into a per-lane guidance snapshot.

    Consumes :class:`FrictionLedger` and :class:`PlaybookRepository` ports,
    so it stays in the application layer.
    """

    def __init__(
        self,
        *,
        friction_ledger: FrictionLedger,
        playbook_repository: PlaybookRepository,
        window: timedelta = DEFAULT_WINDOW,
    ) -> None:
        self._friction_ledger = friction_ledger
        self._playbook_repository = playbook_repository
        self._window = window

    async def build(
        self,
        *,
        project_id: str,
        lane_contract: LaneContract,
        card_body: str,
        from_lane_id: str | None = None,
        now: datetime | None = None,
    ) -> LaneJitContext:
        """Build the JIT guidance snapshot for the lane the card just entered."""
        moment = now or datetime.now(UTC)
        signals = await self._friction_ledger.query_window(
            project_id,
            since=moment - self._window,
            until=moment,
        )
        playbooks = await self._playbook_repository.find_by_project(
            project_id,
            status=PlaybookStatus.ACTIVE,
            limit=50,
        )
        entry_eval = evaluate_gate(lane_contract, gate="entry", card_body=card_body)
        bullets = list(_render_friction_bullets(signals, lane_contract.lane_id))
        matched = _match_playbooks(playbooks, from_lane=from_lane_id, to_lane=lane_contract.lane_id)
        for pb in matched[:MAX_PLAYBOOK_BULLETS]:
            head = pb.name.strip() or pb.id
            top_step = pb.steps[0].instruction if pb.steps else pb.trigger.description
            bullets.append(f"Playbook '{head}': {top_step}")
        headline = (
            f"Lane '{lane_contract.display_name}' just received the card."
            f" Recent friction signals: {len(signals)}; matched playbooks: {len(matched)}."
        )
        return LaneJitContext(
            lane_id=lane_contract.lane_id,
            headline=headline,
            bullets=tuple(bullets),
            entry_gate=entry_eval,
            matched_playbook_ids=tuple(pb.id for pb in matched),
        )


def _render_friction_bullets(
    signals: list[FrictionSignal],
    lane_id: str,
) -> list[str]:
    """Summarise recent friction into at most ``MAX_FRICTION_BULLETS`` bullets."""
    if not signals:
        return []
    relevant = [
        s
        for s in signals
        if s.target_lane == lane_id or s.source_lane == lane_id or s.kind is FrictionKind.RETRY
    ]
    if not relevant:
        relevant = signals[-MAX_FRICTION_BULLETS:]
    counter: Counter[tuple[FrictionKind, str | None, str | None]] = Counter()
    for sig in relevant:
        counter[(sig.kind, sig.source_lane, sig.target_lane)] += 1
    bullets: list[str] = []
    for (kind, src, dst), count in counter.most_common(MAX_FRICTION_BULLETS):
        edge = f" {src}->{dst}" if src and dst else ""
        bullets.append(f"{kind.value}{edge} x{count}")
    return bullets


def _match_playbooks(
    playbooks: list[Playbook],
    *,
    from_lane: str | None,
    to_lane: str,
) -> list[Playbook]:
    """Return active playbooks whose trigger correlates with the lane move."""
    matched: list[Playbook] = []
    for pb in playbooks:
        if pb.status is not PlaybookStatus.ACTIVE:
            continue
        edges = pb.trigger.lane_transitions
        if not edges:
            matched.append(pb)
            continue
        for src, dst in edges:
            if dst == to_lane and (from_lane is None or src == from_lane):
                matched.append(pb)
                break
    matched.sort(key=lambda p: p.hit_count, reverse=True)
    return matched


__all__ = [
    "LaneExperienceService",
    "LaneJitContext",
]
