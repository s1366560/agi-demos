"""Lossless resume payloads for ordinary human answers."""

from __future__ import annotations

import json


def ordinary_resume_metadata(value: object) -> dict[str, str]:
    """Keep text verbatim and serialize structured choices as canonical JSON."""
    answer = (
        value
        if isinstance(value, str)
        else json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
        )
    )
    return {"resume_answer": answer, "resume_answer_encoding": "utf-8"}
