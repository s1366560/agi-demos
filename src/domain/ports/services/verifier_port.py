"""Port: run acceptance criteria and produce a verification report."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    CriterionResult,
    PlanNode,
    VerificationReport,
)


@dataclass(frozen=True)
class VerificationContext:
    """Runtime bag passed to runners: artifacts, stdout, sandbox handle.

    ``sandbox`` is deliberately typed ``Any`` so we don't force a coupling
    between ``domain`` and the specific sandbox adapter implementations.
    """

    workspace_id: str
    node: PlanNode
    attempt_id: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    sandbox: Any = None  # LocalSandboxAdapter | MCPSandboxAdapter | None


class CriterionRunner(Protocol):
    """Runs a single criterion of a specific :class:`CriterionKind`."""

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult: ...


class VerifierPort(Protocol):
    """Aggregates criterion runners and produces a :class:`VerificationReport`."""

    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        """Run every criterion on ``ctx.node``. Never raises for criterion
        failures — they are expressed via the returned report. Only
        infrastructure-level exceptions (e.g. sandbox unreachable) should
        propagate.
        """
        ...
