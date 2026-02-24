"""
WorkflowPattern entity (T074)

Represents a learned workflow pattern from successful agent executions.
Patterns are used to recognize similar queries and reuse proven approaches.

Patterns are tenant-scoped (FR-019) - shared across all projects within a tenant
but isolated between tenants.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class PatternStep:
    """
    A single step in a workflow pattern.

    Attributes:
        step_number: Order of this step in the workflow
        description: Human-readable description of what this step does
        tool_name: Name of the agent tool used in this step
        expected_output_format: Format of the expected output (text, chart, structured, etc.)
        similarity_threshold: Minimum similarity score for query matching (0-1)
        tool_parameters: Optional parameters passed to the tool
    """

    step_number: int
    description: str
    tool_name: str
    expected_output_format: str
    similarity_threshold: float = 0.8
    tool_parameters: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate the pattern step."""
        if self.step_number < 1:
            raise ValueError("step_number must be >= 1")
        if not self.description:
            raise ValueError("description cannot be empty")
        if not self.tool_name:
            raise ValueError("tool_name cannot be empty")
        if not 0 <= self.similarity_threshold <= 1:
            raise ValueError("similarity_threshold must be between 0 and 1")

    def calculate_similarity(self, query: str, step_description: str) -> float:
        """
        Calculate similarity between this step and a query step.

        Uses simple keyword overlap for similarity calculation.
        Can be enhanced with more sophisticated NLP.
        """
        query_lower = query.lower()
        step_lower = step_description.lower()

        # Extract keywords from description
        keywords = set(step_lower.split())
        query_keywords = set(query_lower.split())

        if not keywords:
            return 0.0

        # Calculate overlap
        overlap = keywords.intersection(query_keywords)
        return len(overlap) / len(keywords) if keywords else 0.0


@dataclass
class WorkflowPattern:
    """
    A learned workflow pattern from successful agent executions.

    Patterns capture the structure of successful workflows so they can be
    recognized and reused when similar queries are made.

    Tenant-level scoping (FR-019):
    - Patterns are shared across all projects within a tenant
    - Each tenant has its own set of learned patterns
    - This enables knowledge reuse while maintaining tenant isolation

    Attributes:
        id: Unique identifier for this pattern
        tenant_id: ID of the tenant that owns this pattern
        name: Human-readable name for this pattern
        description: Description of what this pattern does
        steps: Ordered list of steps in the workflow
        success_rate: Historical success rate (0-1)
        usage_count: Number of times this pattern has been used
        created_at: When this pattern was first learned
        updated_at: When this pattern was last modified
        metadata: Optional additional metadata about the pattern
    """

    id: str
    tenant_id: str
    name: str
    description: str
    steps: list[PatternStep]
    success_rate: float
    usage_count: int
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate the workflow pattern."""
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")
        if not self.description:
            raise ValueError("description cannot be empty")
        if not 0 <= self.success_rate <= 1:
            raise ValueError("success_rate must be between 0 and 1")
        if self.usage_count < 0:
            raise ValueError("usage_count must be >= 0")
        if self.steps is None:
            raise ValueError("steps cannot be None")

    def calculate_similarity(self, query: str) -> float:
        """
        Calculate similarity score between this pattern and a query.

        The similarity is based on:
        1. Description keyword overlap
        2. Step descriptions
        3. Tool names used

        Returns a score between 0 and 1.
        """
        query_lower = query.lower()

        # Check description similarity
        description_keywords = set(self.description.lower().split())
        query_keywords = set(query_lower.split())

        if description_keywords:
            desc_overlap = description_keywords.intersection(query_keywords)
            desc_score = len(desc_overlap) / len(description_keywords)
        else:
            desc_score = 0.0

        # Check step descriptions
        step_scores = []
        for step in self.steps:
            step_keywords = set(step.description.lower().split())
            if step_keywords:
                step_overlap = step_keywords.intersection(query_keywords)
                step_scores.append(len(step_overlap) / len(step_keywords))

        avg_step_score = sum(step_scores) / len(step_scores) if step_scores else 0.0

        # Combine scores (weighted average)
        combined_score = (desc_score * 0.4) + (avg_step_score * 0.6)

        return min(combined_score, 1.0)

    def update_execution_result(self, success: bool) -> "WorkflowPattern":
        """
        Update the pattern's success rate and usage count based on an execution result.

        Args:
            success: Whether the execution was successful

        Returns:
            A new WorkflowPattern with updated metrics
        """
        new_usage_count = self.usage_count + 1

        # Update success rate using running average
        if self.usage_count == 0:
            new_success_rate = 1.0 if success else 0.0
        else:
            # New average = (old_avg * n + new_value) / (n + 1)
            new_value = 1.0 if success else 0.0
            new_success_rate = (self.success_rate * self.usage_count + new_value) / new_usage_count

        return WorkflowPattern(
            id=self.id,
            tenant_id=self.tenant_id,
            name=self.name,
            description=self.description,
            steps=self.steps,
            success_rate=new_success_rate,
            usage_count=new_usage_count,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "steps": [
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
            "success_rate": self.success_rate,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowPattern":
        """Create from dictionary (e.g., from database)."""
        steps = [
            PatternStep(
                step_number=step_data["step_number"],
                description=step_data["description"],
                tool_name=step_data["tool_name"],
                expected_output_format=step_data.get("expected_output_format", "text"),
                similarity_threshold=step_data.get("similarity_threshold", 0.8),
                tool_parameters=step_data.get("tool_parameters"),
            )
            for step_data in data.get("steps", [])
        ]

        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            name=data["name"],
            description=data["description"],
            steps=steps,
            success_rate=data.get("success_rate", 1.0),
            usage_count=data.get("usage_count", 0),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(UTC),
            metadata=data.get("metadata"),
        )
