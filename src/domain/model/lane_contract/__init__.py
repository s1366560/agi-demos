"""Lane contract — distilled from routa's per-column specialist prompts.

Each lane (Backlog / Todo / Dev / Review / Done / Blocked) declares a
structured contract: required card sections, entry-gate checks (must hold
for upstream output to be trusted), and exit-gate checks (must hold before
the agent is allowed to advance the card).

Contracts are *value objects* — append-only, immutable, never mutated. The
deterministic gate evaluator lives alongside as a free function so the
domain stays free of I/O.

Per Agent-First: the structural section/key check (membership) is
deterministic; any judgement about whether content "is good enough" must be
delegated to an agent tool-call.
"""

from src.domain.model.lane_contract.artifact_gate import (
    ArtifactGapReport,
    LaneArtifactRequirement,
    RequiredArtifactKind,
    default_lane_artifact_requirements,
    evaluate_artifact_gap,
)
from src.domain.model.lane_contract.contract import (
    GateCheck,
    GateEvaluation,
    GateResult,
    LaneContract,
    LaneContractRegistry,
    default_kanban_contracts,
    evaluate_gate,
)

__all__ = [
    "ArtifactGapReport",
    "GateCheck",
    "GateEvaluation",
    "GateResult",
    "LaneArtifactRequirement",
    "LaneContract",
    "LaneContractRegistry",
    "RequiredArtifactKind",
    "default_kanban_contracts",
    "default_lane_artifact_requirements",
    "evaluate_artifact_gap",
    "evaluate_gate",
]
