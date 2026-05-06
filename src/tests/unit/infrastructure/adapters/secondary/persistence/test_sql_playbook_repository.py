"""Tests for ``SqlPlaybookRepository`` round-trip + record_hit semantics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.flow.playbook import (
    Playbook,
    PlaybookStatus,
    PlaybookStep,
    TriggerPattern,
)
from src.infrastructure.adapters.secondary.persistence.sql_playbook_repository import (
    SqlPlaybookRepository,
)


def _make_playbook(*, pid: str = "pb-1", project_id: str = "proj-1") -> Playbook:
    now = datetime.now(UTC)
    return Playbook(
        id=pid,
        project_id=project_id,
        name="rerun-failing-test",
        trigger=TriggerPattern(
            description="lint fails repeatedly after edits",
            friction_kinds=("lint_failure", "rework"),
            lane_transitions=(("plan", "execute"), ("execute", "review")),
        ),
        steps=(
            PlaybookStep(order=1, instruction="run lint", rationale="catch early"),
            PlaybookStep(order=2, instruction="apply autofix", rationale=None),
        ),
        status=PlaybookStatus.ACTIVE,
        hit_count=3,
        last_used_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
async def repo(db_session: AsyncSession) -> SqlPlaybookRepository:
    return SqlPlaybookRepository(db_session)


class TestSqlPlaybookRepository:
    @pytest.mark.asyncio
    async def test_save_then_find_round_trips_all_fields(self, repo: SqlPlaybookRepository) -> None:
        original = _make_playbook()
        await repo.save(original)

        loaded = await repo.find_by_id(original.id)
        assert loaded is not None
        assert loaded.id == original.id
        assert loaded.project_id == original.project_id
        assert loaded.name == original.name
        assert loaded.status is PlaybookStatus.ACTIVE
        assert loaded.hit_count == 3
        # Trigger round-trip preserves tuples (not lists)
        assert loaded.trigger.description == original.trigger.description
        assert loaded.trigger.friction_kinds == ("lint_failure", "rework")
        assert loaded.trigger.lane_transitions == (
            ("plan", "execute"),
            ("execute", "review"),
        )
        # Steps round-trip preserves tuple-of-PlaybookStep
        assert len(loaded.steps) == 2
        assert loaded.steps[0].order == 1
        assert loaded.steps[0].instruction == "run lint"
        assert loaded.steps[1].rationale is None

    @pytest.mark.asyncio
    async def test_save_is_upsert_on_id(self, repo: SqlPlaybookRepository) -> None:
        original = _make_playbook()
        await repo.save(original)

        updated = Playbook(
            id=original.id,
            project_id=original.project_id,
            name="renamed-recipe",
            trigger=TriggerPattern(description="new pattern"),
            steps=(),
            status=PlaybookStatus.DEPRECATED,
            hit_count=99,
            last_used_at=original.last_used_at,
            created_at=original.created_at,
            updated_at=original.updated_at,
        )
        await repo.save(updated)

        loaded = await repo.find_by_id(original.id)
        assert loaded is not None
        assert loaded.name == "renamed-recipe"
        assert loaded.status is PlaybookStatus.DEPRECATED
        assert loaded.hit_count == 99
        assert loaded.steps == ()

    @pytest.mark.asyncio
    async def test_find_by_project_filters_by_status(self, repo: SqlPlaybookRepository) -> None:
        await repo.save(
            Playbook(
                id="pb-a",
                project_id="proj-A",
                name="a",
                trigger=TriggerPattern(description="x"),
                status=PlaybookStatus.ACTIVE,
            )
        )
        await repo.save(
            Playbook(
                id="pb-b",
                project_id="proj-A",
                name="b",
                trigger=TriggerPattern(description="y"),
                status=PlaybookStatus.DRAFT,
            )
        )
        await repo.save(
            Playbook(
                id="pb-c",
                project_id="proj-B",
                name="c",
                trigger=TriggerPattern(description="z"),
                status=PlaybookStatus.ACTIVE,
            )
        )

        all_a = await repo.find_by_project("proj-A")
        assert {p.id for p in all_a} == {"pb-a", "pb-b"}

        active_a = await repo.find_by_project("proj-A", status=PlaybookStatus.ACTIVE)
        assert [p.id for p in active_a] == ["pb-a"]

    @pytest.mark.asyncio
    async def test_record_hit_increments_and_bumps_timestamp(
        self, repo: SqlPlaybookRepository
    ) -> None:
        playbook = _make_playbook(pid="pb-hit")
        await repo.save(playbook)

        await repo.record_hit("pb-hit")
        loaded = await repo.find_by_id("pb-hit")
        assert loaded is not None
        assert loaded.hit_count == 4
        assert loaded.last_used_at is not None

    @pytest.mark.asyncio
    async def test_record_hit_is_noop_for_missing_id(self, repo: SqlPlaybookRepository) -> None:
        # Should not raise
        await repo.record_hit("does-not-exist")
        assert await repo.find_by_id("does-not-exist") is None

    @pytest.mark.asyncio
    async def test_find_by_id_returns_none_when_missing(self, repo: SqlPlaybookRepository) -> None:
        assert await repo.find_by_id("missing") is None
