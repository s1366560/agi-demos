"""Review Gate ports — abstract interfaces for the 3-layer review pipeline.

Implementations live under ``src/infrastructure/adapters/secondary/review/``
(not part of this scaffold). Each layer's port deliberately returns *only*
its layer's contract type — the orchestration that fans these into a final
``GateDecision`` belongs to an application service that calls a
Gate Specialist agent.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.model.review import (
    EntrixVerdict,
    GateDecision,
    HarnessSignal,
)


class HarnessMonitorPort(Protocol):
    """Layer 1 — emit objective execution signals.

    Implementations watch sandbox/test/build runners and produce
    ``HarnessSignal`` rows. They MUST NOT classify outcomes as pass/fail.
    """

    async def collect(self, *, workspace_id: str, task_id: str) -> tuple[HarnessSignal, ...]: ...


class EntrixFitnessPort(Protocol):
    """Layer 2 — deterministic hard-gate evaluation.

    Returns boolean per gate plus a flat list of missing required-evidence
    keys. No natural-language verdict is allowed at this layer.
    """

    async def evaluate(
        self,
        *,
        workspace_id: str,
        task_id: str,
        signals: tuple[HarnessSignal, ...],
    ) -> EntrixVerdict: ...


class GateSpecialistPort(Protocol):
    """Layer 3 — agent-authored final decision.

    Implementations MUST be backed by a Gate Specialist agent invoked via a
    structured tool-call (per the Agent First rule). The implementation is
    responsible for passing the canonical story's acceptance criteria and
    the lower-layer artifacts to the agent and parsing its tool-call output
    into a ``GateDecision``.
    """

    async def decide(
        self,
        *,
        workspace_id: str,
        task_id: str,
        canonical_story_yaml: str,
        signals: tuple[HarnessSignal, ...],
        entrix: EntrixVerdict,
    ) -> GateDecision: ...


__all__ = [
    "EntrixFitnessPort",
    "GateSpecialistPort",
    "HarnessMonitorPort",
]
