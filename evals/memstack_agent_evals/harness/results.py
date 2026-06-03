"""Result persistence."""

from __future__ import annotations

import json
from pathlib import Path

from memstack_agent_evals.models import EvaluationResult


def append_result(path: Path, result: EvaluationResult) -> None:
    """Append one result as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(result.model_dump_json() + "\n")


def write_json(path: Path, payload: object) -> None:
    """Write formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
