"""Maximal Marginal Relevance (MMR) re-ranking.

Ported from Moltbot's mmr.ts. Balances relevance and diversity
using Jaccard similarity on token sets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


class HasContentAndScore(Protocol):
    """Protocol for items that can be MMR-reranked."""

    content: str
    score: float


def tokenize(text: str) -> set[str]:
    """Extract lowercase alphanumeric tokens from text."""
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def text_similarity(text_a: str, text_b: str) -> float:
    """Compute text similarity using Jaccard on tokens."""
    return jaccard_similarity(tokenize(text_a), tokenize(text_b))


@dataclass
class MMRItem:
    """Wrapper for items during MMR reranking."""

    index: int
    content: str
    relevance: float
    mmr_score: float = 0.0


def mmr_rerank(
    items: list[dict[str, Any]],
    lambda_: float = 0.7,
    content_key: str = "content",
    score_key: str = "score",
) -> list[dict[str, Any]]:
    """Re-rank items using Maximal Marginal Relevance.

    MMR score = lambda * relevance - (1 - lambda) * max_similarity_to_selected

    Args:
        items: List of result dicts with content and score.
        lambda_: Balance between relevance (1.0) and diversity (0.0).
        content_key: Key for content text in item dict.
        score_key: Key for relevance score in item dict.

    Returns:
        Re-ranked list of items with updated scores.
    """
    if not items or len(items) <= 1:
        return items

    # Normalize scores to [0, 1]
    scores = [item.get(score_key, 0.0) for item in items]
    min_score = min(scores)
    max_score = max(scores)
    score_range = max_score - min_score if max_score > min_score else 1.0

    candidates = [
        MMRItem(
            index=i,
            content=item.get(content_key, ""),
            relevance=(item.get(score_key, 0.0) - min_score) / score_range,
        )
        for i, item in enumerate(items)
    ]

    selected: list[MMRItem] = []
    remaining = list(candidates)

    while remaining:
        best_idx = -1
        best_mmr = float("-inf")

        for i, candidate in enumerate(remaining):
            if not selected:
                max_sim = 0.0
            else:
                max_sim = max(text_similarity(candidate.content, s.content) for s in selected)

            mmr_score = lambda_ * candidate.relevance - (1.0 - lambda_) * max_sim
            if mmr_score > best_mmr:
                best_mmr = mmr_score
                best_idx = i

        if best_idx >= 0:
            chosen = remaining.pop(best_idx)
            chosen.mmr_score = best_mmr
            selected.append(chosen)

    # Map back to original items with updated scores
    result = []
    for rank, item in enumerate(selected):
        original = dict(items[item.index])
        # Assign rank-based score: highest MMR gets highest score
        original[score_key] = 1.0 - (rank / len(selected))
        result.append(original)

    return result
