"""Runner protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from memstack_agent_evals.models import EvaluationCase, EvaluationResult


class AgentRunner(Protocol):
    """Black-box runner interface."""

    name: str

    def run(
        self,
        case: EvaluationCase,
        *,
        workspace: Path,
        output_dir: Path,
        dry_run: bool = False,
    ) -> EvaluationResult:
        """Run one evaluation case."""
