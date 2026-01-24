"""
LearnPattern use case (T075)

Use case for learning a new workflow pattern from a successful agent execution.

When an agent completes a complex query successfully, the workflow is analyzed
and potentially stored as a pattern for future reuse.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.domain.model.agent.workflow_pattern import PatternStep, WorkflowPattern
from src.domain.ports.repositories.workflow_pattern_repository import WorkflowPatternRepositoryPort


@dataclass
class LearnPatternRequest:
    """Request to learn a pattern from an execution."""

    tenant_id: str
    name: Optional[str]  # Will be generated if not provided
    description: str
    conversation_id: str
    execution_id: str
    steps: List[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class LearnPatternResult:
    """Result of learning a pattern."""

    pattern: Optional[WorkflowPattern]
    was_new_pattern: bool  # True if created new, False if updated existing


class LearnPattern:
    """
    Use case for learning workflow patterns from successful executions.

    This use case analyzes successful agent executions and extracts
    reusable workflow patterns that can be matched to future queries.
    """

    def __init__(self, repository: WorkflowPatternRepositoryPort):
        self._repository = repository

    async def execute(self, request: LearnPatternRequest) -> WorkflowPattern:
        """
        Execute the pattern learning use case.

        Args:
            request: The pattern learning request

        Returns:
            The created or updated WorkflowPattern

        Raises:
            ValueError: If the request is invalid
        """
        if not request.tenant_id:
            raise ValueError("tenant_id is required")
        if not request.description:
            raise ValueError("description is required")
        if not request.steps:
            raise ValueError("at least one step is required")

        # Check if a similar pattern already exists
        existing_patterns = await self._repository.list_by_tenant(request.tenant_id)
        similar_pattern = self._find_similar_pattern(request, existing_patterns)

        # Convert steps to PatternStep objects
        pattern_steps = [
            PatternStep(
                step_number=step_data["step_number"],
                description=step_data["description"],
                tool_name=step_data["tool_name"],
                expected_output_format=step_data.get("expected_output_format", "text"),
                similarity_threshold=step_data.get("similarity_threshold", 0.8),
                tool_parameters=step_data.get("tool_parameters"),
            )
            for step_data in request.steps
        ]

        if similar_pattern:
            # Update existing pattern
            updated_pattern = WorkflowPattern(
                id=similar_pattern.id,
                tenant_id=similar_pattern.tenant_id,
                name=similar_pattern.name,
                description=similar_pattern.description,
                steps=similar_pattern.steps,
                success_rate=similar_pattern.success_rate,
                usage_count=similar_pattern.usage_count + 1,
                created_at=similar_pattern.created_at,
                updated_at=datetime.now(timezone.utc),
                metadata=similar_pattern.metadata,
            )
            await self._repository.update(updated_pattern)
            return updated_pattern
        else:
            # Create new pattern
            pattern_id = f"pattern-{request.tenant_id}-{datetime.now(timezone.utc).timestamp()}"

            pattern = WorkflowPattern(
                id=pattern_id,
                tenant_id=request.tenant_id,
                name=request.name or self._generate_name(request),
                description=request.description,
                steps=pattern_steps,
                success_rate=1.0,  # New pattern starts with perfect success rate
                usage_count=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                metadata={
                    **(request.metadata or {}),
                    "source_conversation": request.conversation_id,
                    "source_execution": request.execution_id,
                },
            )

            return await self._repository.create(pattern)

    def _find_similar_pattern(
        self,
        request: LearnPatternRequest,
        existing_patterns: List[WorkflowPattern],
    ) -> Optional[WorkflowPattern]:
        """
        Find an existing pattern that is similar to the request.

        Similarity is based on:
        1. Step structure (same tools in same order)
        2. Description similarity

        Args:
            request: The pattern learning request
            existing_patterns: Existing patterns to search

        Returns:
            A similar pattern if found, None otherwise
        """
        if not existing_patterns:
            return None

        # Check for patterns with same number of steps
        same_length_patterns = [p for p in existing_patterns if len(p.steps) == len(request.steps)]

        if not same_length_patterns:
            return None

        # Check for exact tool name match in sequence
        request_tools = [step.get("tool_name") for step in request.steps]

        for pattern in same_length_patterns:
            pattern_tools = [step.tool_name for step in pattern.steps]

            if request_tools == pattern_tools:
                # Same tools in same order - check description similarity
                similarity = pattern.calculate_similarity(request.description)
                if similarity > 0.7:  # Threshold for considering similar
                    return pattern

        return None

    def _generate_name(self, request: LearnPatternRequest) -> str:
        """Generate a name for the pattern based on its description and steps."""
        # Extract key terms from description
        words = request.description.lower().split()

        # Remove common words
        stop_words = {"the", "a", "an", "for", "to", "with", "and", "or", "in", "on", "at"}
        keywords = [w for w in words if w not in stop_words and len(w) > 3]

        if keywords:
            return f"{' '.join(keywords[:3]).title()} Pattern"

        # Fallback to tool names
        tools = [step.get("tool_name", "tool") for step in request.steps]
        return f"{'-'.join(tools[:3]).title()} Workflow"
