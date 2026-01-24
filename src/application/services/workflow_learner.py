"""
WorkflowLearner service (T077)

Service for automatically learning workflow patterns from successful agent executions.

This service orchestrates the pattern learning process:
1. Analyzes successful agent executions
2. Extracts workflow structure
3. Creates or updates pattern definitions
4. Tracks pattern usage and success rates
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.application.use_cases.agent.find_similar_pattern import (
    FindSimilarPattern,
    FindSimilarPatternRequest,
)
from src.application.use_cases.agent.learn_pattern import LearnPattern, LearnPatternRequest
from src.domain.model.agent.workflow_pattern import WorkflowPattern
from src.domain.ports.repositories.workflow_pattern_repository import WorkflowPatternRepositoryPort

logger = logging.getLogger(__name__)


@dataclass
class ExecutionStep:
    """
    A single step from an agent execution.

    Represents one tool invocation or action taken during execution.
    """

    step_number: int
    description: str
    tool_name: str
    expected_output_format: str = "text"
    similarity_threshold: float = 0.8
    tool_parameters: Optional[Dict[str, Any]] = None


@dataclass
class ExecutionAnalysis:
    """
    Analysis of a completed agent execution.

    Contains the extracted workflow structure from an execution.
    """

    conversation_id: str
    execution_id: str
    tenant_id: str
    query: str
    steps: List[ExecutionStep]
    was_successful: bool
    execution_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_learn_request(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> LearnPatternRequest:
        """
        Convert this analysis to a LearnPatternRequest.

        Args:
            name: Optional name for the pattern
            description: Optional description (defaults to query)

        Returns:
            LearnPatternRequest ready for use with LearnPattern use case
        """
        return LearnPatternRequest(
            tenant_id=self.tenant_id,
            name=name,
            description=description or self.query,
            conversation_id=self.conversation_id,
            execution_id=self.execution_id,
            steps=[
                {
                    "step_number": step.step_number,
                    "description": step.description,
                    "tool_name": step.tool_name,
                    "expected_output_format": step.expected_output_format,
                    "similarity_threshold": step.similarity_threshold,
                    "tool_parameters": step.tool_parameters,
                }
                for step in self.steps
            ],
            metadata={
                "original_query": self.query,
                "was_successful": self.was_successful,
                **self.execution_metadata,
            },
        )


@dataclass
class LearningResult:
    """
    Result of the pattern learning process.

    Indicates what action was taken and the resulting pattern.
    """

    action: str  # "created", "updated", "skipped"
    pattern: Optional[WorkflowPattern]
    similarity_score: Optional[float] = None  # If updated, similarity to existing
    reason: Optional[str] = None  # If skipped, why


class WorkflowLearner:
    """
    Service for learning workflow patterns from agent executions.

    This service coordinates the analysis of successful executions
    and the creation/update of workflow patterns.

    Learning criteria:
    - Only learns from successful executions
    - Requires at least 2 steps (single-step queries don't need patterns)
    - Merges with similar existing patterns (>70% similarity)
    - Tracks success rate over time
    """

    def __init__(
        self,
        learn_pattern: LearnPattern,
        find_similar_pattern: FindSimilarPattern,
        repository: WorkflowPatternRepositoryPort,
    ):
        self._learn_pattern = learn_pattern
        self._find_similar_pattern = find_similar_pattern
        self._repository = repository

    async def learn_from_execution(
        self,
        analysis: ExecutionAnalysis,
    ) -> LearningResult:
        """
        Learn a pattern from a completed execution.

        Args:
            analysis: The execution analysis

        Returns:
            LearningResult indicating what happened
        """
        # Only learn from successful executions
        if not analysis.was_successful:
            return LearningResult(
                action="skipped",
                pattern=None,
                reason="Execution was not successful",
            )

        # Require at least 2 steps for meaningful patterns
        if len(analysis.steps) < 2:
            return LearningResult(
                action="skipped",
                pattern=None,
                reason="Execution had fewer than 2 steps",
            )

        # Check for similar existing patterns
        search_request = FindSimilarPatternRequest(
            tenant_id=analysis.tenant_id,
            query=analysis.query,
            min_similarity=0.7,
            limit=1,
        )

        search_result = await self._find_similar_pattern.execute(search_request)

        if search_result.matches:
            # Similar pattern exists - will be merged in LearnPattern
            similar_result = search_result.matches[0]
            pattern = await self._learn_pattern.execute(analysis.to_learn_request())

            return LearningResult(
                action="updated",
                pattern=pattern,
                similarity_score=similar_result.similarity_score,
            )
        else:
            # Create new pattern
            pattern = await self._learn_pattern.execute(analysis.to_learn_request())

            return LearningResult(
                action="created",
                pattern=pattern,
            )

    async def find_pattern_for_query(
        self,
        tenant_id: str,
        query: str,
    ) -> Optional[WorkflowPattern]:
        """
        Find the best pattern for a given query.

        Args:
            tenant_id: Tenant to search within
            query: Query to match

        Returns:
            Best matching pattern, or None if no good match
        """
        return await self._find_similar_pattern.find_best_match(
            tenant_id=tenant_id,
            query=query,
            min_success_rate=0.6,  # Require 60% success rate
        )

    async def get_all_tenant_patterns(
        self,
        tenant_id: str,
    ) -> List[WorkflowPattern]:
        """
        Get all patterns for a tenant.

        Args:
            tenant_id: Tenant to get patterns for

        Returns:
            List of all patterns for the tenant
        """
        return await self._repository.list_by_tenant(tenant_id)

    async def analyze_execution(
        self,
        conversation_id: str,
        execution_id: str,
        tenant_id: str,
        query: str,
        execution_trace: List[Dict[str, Any]],
        was_successful: bool,
    ) -> ExecutionAnalysis:
        """
        Analyze an execution trace to extract workflow structure.

        Args:
            conversation_id: ID of the conversation
            execution_id: ID of the execution
            tenant_id: Tenant ID
            query: Original user query
            execution_trace: Trace of tool calls/actions
            was_successful: Whether execution succeeded

        Returns:
            ExecutionAnalysis with extracted workflow steps
        """
        steps = []

        for i, trace_item in enumerate(execution_trace, start=1):
            # Extract step information from trace
            tool_name = trace_item.get("tool", trace_item.get("action", "unknown"))
            description = trace_item.get("description", f"Execute {tool_name}")
            output_format = trace_item.get("output_format", "text")

            step = ExecutionStep(
                step_number=i,
                description=description,
                tool_name=tool_name,
                expected_output_format=output_format,
                similarity_threshold=trace_item.get("similarity_threshold", 0.8),
                tool_parameters=trace_item.get("parameters"),
            )
            steps.append(step)

        return ExecutionAnalysis(
            conversation_id=conversation_id,
            execution_id=execution_id,
            tenant_id=tenant_id,
            query=query,
            steps=steps,
            was_successful=was_successful,
            execution_metadata={
                "trace_length": len(execution_trace),
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def record_pattern_execution(
        self,
        pattern_id: str,
        success: bool,
    ) -> Optional[WorkflowPattern]:
        """
        Record the result of a pattern execution.

        Updates the pattern's success rate and usage count.

        Args:
            pattern_id: ID of the pattern that was used
            success: Whether the execution was successful

        Returns:
            Updated pattern, or None if pattern not found
        """
        pattern = await self._repository.get_by_id(pattern_id)

        if pattern:
            updated_pattern = pattern.update_execution_result(success)
            await self._repository.update(updated_pattern)
            return updated_pattern

        return None
