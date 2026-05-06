"""Unit tests for ``LaneExperienceService``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.services.lane_experience_service import (
    LaneExperienceService,
    LaneJitContext,
)
from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.model.flow.playbook import (
    Playbook,
    PlaybookStatus,
    PlaybookStep,
    TriggerPattern,
)
from src.domain.model.lane_contract import (
    GateResult,
    LaneContractRegistry,
)
from src.infrastructure.adapters.secondary.in_memory.friction_loop import (
    InMemoryFrictionLedger,
    InMemoryPlaybookRepository,
)


@pytest.fixture()
def registry() -> LaneContractRegistry:
    return LaneContractRegistry.default()


async def _seed_friction(
    ledger: InMemoryFrictionLedger,
    *,
    project_id: str = "proj-1",
    now: datetime,
) -> None:
    samples = [
        FrictionSignal(
            project_id=project_id,
            task_id="task-1",
            kind=FrictionKind.BOUNCE,
            source_lane="dev",
            target_lane="todo",
            observed_at=now - timedelta(minutes=15),
        ),
        FrictionSignal(
            project_id=project_id,
            task_id="task-2",
            kind=FrictionKind.BOUNCE,
            source_lane="dev",
            target_lane="todo",
            observed_at=now - timedelta(minutes=10),
        ),
        FrictionSignal(
            project_id=project_id,
            task_id="task-3",
            kind=FrictionKind.RETRY,
            source_lane="dev",
            target_lane="dev",
            observed_at=now - timedelta(minutes=5),
        ),
    ]
    for sig in samples:
        await ledger.append(sig)


async def _seed_playbook(
    repo: InMemoryPlaybookRepository,
    *,
    project_id: str = "proj-1",
    name: str = "Stabilise dev → review handoff",
    transitions: tuple[tuple[str, str], ...] = (("dev", "review"),),
    hit_count: int = 3,
) -> Playbook:
    playbook = Playbook(
        project_id=project_id,
        name=name,
        trigger=TriggerPattern(
            description="Dev evidence missing AC verification",
            lane_transitions=transitions,
        ),
        steps=(
            PlaybookStep(order=1, instruction="Re-run unit tests before handoff."),
        ),
        status=PlaybookStatus.ACTIVE,
        hit_count=hit_count,
    )
    await repo.save(playbook)
    return playbook


@pytest.mark.asyncio
async def test_build_returns_jit_context_with_friction_summary(
    registry: LaneContractRegistry,
) -> None:
    ledger = InMemoryFrictionLedger()
    repo = InMemoryPlaybookRepository()
    now = datetime.now(UTC)
    await _seed_friction(ledger, now=now)

    service = LaneExperienceService(friction_ledger=ledger, playbook_repository=repo)
    contract = registry.get("todo")
    assert contract is not None
    card_body = "```yaml\nstory:\n  acceptance_criteria:\n    - id: AC1\n```"

    ctx = await service.build(
        project_id="proj-1",
        lane_contract=contract,
        card_body=card_body,
        from_lane_id="dev",
        now=now,
    )

    assert isinstance(ctx, LaneJitContext)
    rendered = ctx.render()
    assert "Lane 'Todo'" in rendered
    assert "bounce" in rendered.lower()
    # Entry gate passes for Todo because the YAML block is present.
    assert ctx.entry_gate is not None
    assert ctx.entry_gate.overall is GateResult.PASS


@pytest.mark.asyncio
async def test_build_surfaces_failed_entry_gate_in_render(
    registry: LaneContractRegistry,
) -> None:
    ledger = InMemoryFrictionLedger()
    repo = InMemoryPlaybookRepository()
    service = LaneExperienceService(friction_ledger=ledger, playbook_repository=repo)
    contract = registry.get("dev")
    assert contract is not None

    ctx = await service.build(
        project_id="proj-1",
        lane_contract=contract,
        card_body="No execution plan, no key files. Naked card.",
        from_lane_id="todo",
    )

    assert ctx.entry_gate is not None
    assert ctx.entry_gate.overall is GateResult.FAIL
    rendered = ctx.render()
    assert "Entry gate FAIL" in rendered
    assert "[has_execution_plan]" in rendered


@pytest.mark.asyncio
async def test_build_matches_playbook_for_correct_transition(
    registry: LaneContractRegistry,
) -> None:
    ledger = InMemoryFrictionLedger()
    repo = InMemoryPlaybookRepository()
    pb_match = await _seed_playbook(
        repo, transitions=(("dev", "review"),), hit_count=5
    )
    pb_other = await _seed_playbook(
        repo, name="Backlog hygiene", transitions=(("backlog", "todo"),), hit_count=8
    )

    service = LaneExperienceService(friction_ledger=ledger, playbook_repository=repo)
    contract = registry.get("review")
    assert contract is not None

    ctx = await service.build(
        project_id="proj-1",
        lane_contract=contract,
        card_body="## Dev Evidence\nChanged files: a.py\nAC verification: AC1 passes",
        from_lane_id="dev",
    )

    assert pb_match.id in ctx.matched_playbook_ids
    assert pb_other.id not in ctx.matched_playbook_ids
    rendered = ctx.render()
    assert "Stabilise dev" in rendered


@pytest.mark.asyncio
async def test_build_treats_unscoped_playbook_as_universal_match(
    registry: LaneContractRegistry,
) -> None:
    ledger = InMemoryFrictionLedger()
    repo = InMemoryPlaybookRepository()
    pb = await _seed_playbook(repo, transitions=())
    service = LaneExperienceService(friction_ledger=ledger, playbook_repository=repo)
    contract = registry.get("todo")
    assert contract is not None

    ctx = await service.build(
        project_id="proj-1",
        lane_contract=contract,
        card_body="```yaml\nstory:\n  acceptance_criteria: []\n```",
        from_lane_id="backlog",
    )

    assert pb.id in ctx.matched_playbook_ids
