"""ReflectionService — orchestrates the friction → playbook reflection loop.

Responsibilities:
1. Ingest task lifecycle events → derive ``FrictionSignal`` (deterministic).
2. On a structural trigger (window full / time tick), call the reflector
   port and persist returned ``ReflectionVerdict`` decisions to the playbook
   repository.

Per Agent-First: the *trigger* (counter / tick) is deterministic, but the
*verdict* (create / reinforce / deprecate) MUST come from ``ReflectorPort``.
This service does NOT make subjective calls.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.model.flow.playbook import (
    Playbook,
    PlaybookStatus,
    PlaybookStep,
    TriggerPattern,
)
from src.domain.model.flow.reflection_verdict import ReflectionAction, ReflectionVerdict
from src.domain.ports.repositories.friction_ledger import FrictionLedger
from src.domain.ports.repositories.playbook_repository import PlaybookRepository
from src.domain.ports.services.reflector_port import ReflectorPort

logger = logging.getLogger(__name__)


class ReflectionService:
    """Coordinates friction ingestion + reflector invocation + playbook upsert."""

    def __init__(
        self,
        *,
        ledger: FrictionLedger,
        playbooks: PlaybookRepository,
        reflector: ReflectorPort,
        window_minutes: int = 60 * 24,
    ) -> None:
        self._ledger = ledger
        self._playbooks = playbooks
        self._reflector = reflector
        self._window = timedelta(minutes=window_minutes)

    async def ingest_friction(self, signal: FrictionSignal) -> None:
        """Append a friction signal to the ledger.

        Pure pass-through; lives here so callers depend on the application
        layer rather than reaching into the ledger directly.
        """
        await self._ledger.append(signal)

    async def derive_signal_from_lane_change(
        self,
        *,
        project_id: str,
        task_id: str,
        from_lane: str,
        to_lane: str,
        lane_order: list[str],
        metadata: dict[str, object] | None = None,
    ) -> FrictionSignal | None:
        """Derive a ``FrictionSignal`` from a lane transition, if any.

        Returns ``None`` if the move is forward (no friction). Backward
        movement → ``BOUNCE``. This is a *structural* derivation (positional
        comparison in lane_order), not a subjective judgment.
        """
        try:
            src_idx = lane_order.index(from_lane)
            dst_idx = lane_order.index(to_lane)
        except ValueError:
            return None
        if dst_idx >= src_idx:
            return None
        return FrictionSignal(
            project_id=project_id,
            task_id=task_id,
            kind=FrictionKind.BOUNCE,
            source_lane=from_lane,
            target_lane=to_lane,
            metadata=metadata or {},
            observed_at=datetime.now(UTC),
        )

    async def reflect_window(self, project_id: str) -> list[ReflectionVerdict]:
        """Run the reflection loop for the configured window.

        Returns the list of verdicts produced by the reflector (after they
        have been applied to the playbook repository). Empty list if no
        signals or no verdicts.
        """
        since = datetime.now(UTC) - self._window
        signals = await self._ledger.query_window(project_id, since=since)
        if not signals:
            return []

        existing = await self._playbooks.find_by_project(project_id)
        verdicts = await self._reflector.reflect(
            project_id=project_id,
            signals=signals,
            existing_playbooks=existing,
        )

        applied: list[ReflectionVerdict] = []
        for verdict in verdicts:
            try:
                if await self._apply_verdict(project_id, verdict):
                    applied.append(verdict)
            except Exception:
                logger.exception(
                    "Failed to apply reflection verdict",
                    extra={"project_id": project_id, "verdict": verdict.action.value},
                )
        return applied

    async def _apply_verdict(
        self, project_id: str, verdict: ReflectionVerdict
    ) -> bool:
        """Apply one verdict. Returns True if the repository was mutated.

        Each branch dispatches to a dedicated helper so the dispatcher itself
        stays a flat lookup (linting requires few return statements).
        """
        handlers = {
            ReflectionAction.NOOP: lambda: self._noop(),
            ReflectionAction.CREATE: lambda: self._apply_create(project_id, verdict),
            ReflectionAction.REINFORCE: lambda: self._apply_reinforce(verdict),
            ReflectionAction.DEPRECATE: lambda: self._apply_deprecate(verdict),
        }
        handler = handlers.get(verdict.action)
        if handler is None:
            return False
        return await handler()

    async def _noop(self) -> bool:
        return False

    async def _apply_create(
        self, project_id: str, verdict: ReflectionVerdict
    ) -> bool:
        payload = verdict.proposed_playbook or {}
        name = str(payload.get("name") or "Untitled playbook")
        playbook = Playbook(
            project_id=project_id,
            name=name,
            trigger=_build_trigger(payload.get("trigger") or {}),
            steps=_build_steps(payload.get("steps") or []),
            status=PlaybookStatus.ACTIVE,
        )
        await self._playbooks.save(playbook)
        return True

    async def _apply_reinforce(self, verdict: ReflectionVerdict) -> bool:
        existing = await self._load_referenced(verdict)
        if existing is None:
            return False
        updated = replace(
            existing,
            status=PlaybookStatus.ACTIVE,
            hit_count=existing.hit_count + 1,
            updated_at=datetime.now(UTC),
        )
        await self._playbooks.save(updated)
        return True

    async def _apply_deprecate(self, verdict: ReflectionVerdict) -> bool:
        existing = await self._load_referenced(verdict)
        if existing is None:
            return False
        updated = replace(
            existing,
            status=PlaybookStatus.DEPRECATED,
            updated_at=datetime.now(UTC),
        )
        await self._playbooks.save(updated)
        return True

    async def _load_referenced(self, verdict: ReflectionVerdict) -> Playbook | None:
        if verdict.playbook_id is None:
            logger.warning(
                "Verdict %s missing playbook_id; skipping",
                verdict.action.value,
            )
            return None
        existing = await self._playbooks.find_by_id(verdict.playbook_id)
        if existing is None:
            logger.warning(
                "Verdict references unknown playbook %s",
                verdict.playbook_id,
            )
        return existing


def _build_trigger(payload: object) -> TriggerPattern:
    if not isinstance(payload, dict):
        return TriggerPattern(description="(no description)")
    description = str(payload.get("description") or "(no description)")
    friction_kinds_raw = payload.get("friction_kinds") or ()
    lane_transitions_raw = payload.get("lane_transitions") or ()
    friction_kinds: tuple[str, ...] = tuple(
        str(k) for k in friction_kinds_raw if isinstance(friction_kinds_raw, (list, tuple))
    )
    lane_transitions: tuple[tuple[str, str], ...] = tuple(
        (str(pair[0]), str(pair[1]))
        for pair in lane_transitions_raw
        if isinstance(pair, (list, tuple)) and len(pair) == 2
    )
    return TriggerPattern(
        description=description,
        friction_kinds=friction_kinds,
        lane_transitions=lane_transitions,
    )


def _build_steps(payload: object) -> tuple[PlaybookStep, ...]:
    if not isinstance(payload, list):
        return ()
    out: list[PlaybookStep] = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        instruction = str(item.get("instruction") or "").strip()
        if not instruction:
            continue
        out.append(
            PlaybookStep(
                order=int(item.get("order", idx)),
                instruction=instruction,
                rationale=(str(item["rationale"]) if "rationale" in item else None),
            )
        )
    return tuple(out)
