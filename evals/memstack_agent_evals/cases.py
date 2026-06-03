"""Evaluation case loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from memstack_agent_evals.models import EvaluationCase


def load_case(path: Path) -> EvaluationCase:
    """Load one evaluation case from JSON or YAML."""
    raw = _load_mapping(path)
    case = EvaluationCase.model_validate(raw)
    if not case.target_repo.is_absolute():
        case.target_repo = (path.parent / case.target_repo).resolve()
    return case


def _load_mapping(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        data = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        raise ValueError(f"Unsupported case file type: {path.suffix}")
    if not isinstance(data, dict):
        raise ValueError(f"Case file must contain a mapping: {path}")
    return data
