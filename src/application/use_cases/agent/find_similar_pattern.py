"""
FindSimilarPattern use case (T076)

Use case for finding workflow patterns similar to a given query.

This is used during agent execution to recognize when a query matches
a learned workflow pattern, enabling the agent to reuse proven approaches.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.domain.model.agent.workflow_pattern import WorkflowPattern
from src.domain.ports.repositories.workflow_pattern_repository import WorkflowPatternRepositoryPort


@dataclass
class FindSimilarPatternRequest:
    """Request to find patterns similar to a query."""

    tenant_id: str
    query: str
    min_similarity: float = 0.7  # Minimum similarity threshold (0-1)
    limit: int = 10  # Maximum number of results to return
    min_success_rate: Optional[float] = None  # Optional minimum success rate filter


@dataclass
class SimilarPatternResult:
    """Result containing a pattern and its similarity score."""

    pattern: WorkflowPattern
    similarity_score: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "pattern": self.pattern.to_dict(),
            "similarity_score": self.similarity_score,
        }


@dataclass
class FindSimilarPatternResult:
    """Result of finding similar patterns."""

    matches: List[SimilarPatternResult]
    total_candidates: int  # Total patterns considered
    query: str
    threshold_used: float


class FindSimilarPattern:
    """
    Use case for finding workflow patterns similar to a query.

    This use case searches through learned patterns within a tenant
    and returns those that match the query above a similarity threshold.
    Results are ranked by similarity score.

    The matching considers:
    1. Pattern description similarity
    2. Step descriptions
    3. Tool names used
    """

    def __init__(self, repository: WorkflowPatternRepositoryPort):
        self._repository = repository

    async def execute(self, request: FindSimilarPatternRequest) -> FindSimilarPatternResult:
        """
        Execute the pattern finding use case.

        Args:
            request: The pattern finding request

        Returns:
            FindSimilarPatternResult containing ranked matches

        Raises:
            ValueError: If the request is invalid
        """
        if not request.tenant_id:
            raise ValueError("tenant_id is required")
        if not request.query:
            raise ValueError("query is required")
        if not 0 <= request.min_similarity <= 1:
            raise ValueError("min_similarity must be between 0 and 1")
        if request.limit < 1:
            raise ValueError("limit must be >= 1")

        # Get all patterns for the tenant
        all_patterns = await self._repository.list_by_tenant(request.tenant_id)

        # Apply optional success rate filter
        if request.min_success_rate is not None:
            all_patterns = [p for p in all_patterns if p.success_rate >= request.min_success_rate]

        # Calculate similarity for each pattern
        candidates = []
        for pattern in all_patterns:
            similarity = pattern.calculate_similarity(request.query)
            if similarity >= request.min_similarity:
                candidates.append(
                    SimilarPatternResult(
                        pattern=pattern,
                        similarity_score=similarity,
                    )
                )

        # Sort by similarity score (descending)
        candidates.sort(key=lambda x: x.similarity_score, reverse=True)

        # Apply limit
        matches = candidates[: request.limit]

        return FindSimilarPatternResult(
            matches=matches,
            total_candidates=len(all_patterns),
            query=request.query,
            threshold_used=request.min_similarity,
        )

    async def find_best_match(
        self,
        tenant_id: str,
        query: str,
        min_success_rate: float = 0.5,
    ) -> Optional[WorkflowPattern]:
        """
        Convenience method to find the single best matching pattern.

        Args:
            tenant_id: Tenant to search within
            query: Query to match against
            min_success_rate: Minimum success rate for patterns

        Returns:
            The best matching pattern, or None if no good match found
        """
        request = FindSimilarPatternRequest(
            tenant_id=tenant_id,
            query=query,
            min_similarity=0.6,  # Slightly lower threshold for best match
            limit=1,
            min_success_rate=min_success_rate,
        )

        result = await self.execute(request)

        if result.matches:
            return result.matches[0].pattern
        return None
