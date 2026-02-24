"""
ToolComposition entity (T108).

Represents a composition of multiple tools that work together
to accomplish complex tasks through intelligent chaining.

Key Features:
- Sequential tool execution with data transformations
- Fallback alternatives for failed tools
- Success rate tracking for learning

Attributes:
    tools: Ordered list of tool names in the composition chain
    execution_template: Defines how tools are composed (sequential, parallel, conditional)
    success_count/failure_count: Usage statistics for learning
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast


@dataclass
class ToolComposition:
    """
    A composition of multiple tools that work together.

    This entity represents a chain of tools that can be executed
    together to accomplish complex tasks. The composition includes
    information about:
    - Which tools to use and in what order
    - How to transform data between tools
    - Alternative tools if primary ones fail
    - Historical success rate

    Attributes:
        id: Unique identifier for this composition
        tenant_id: Tenant identifier for multi-tenant isolation
        project_id: Optional project identifier for project-level isolation
        name: Human-readable name
        description: What this composition does
        tools: Ordered list of tool names
        execution_template: How to compose tools (structure, transformations)
        success_count: Number of successful executions
        failure_count: Number of failed executions
        usage_count: Total number of times used
        created_at: When this composition was created
        updated_at: When this composition was last modified
    """

    id: str
    tenant_id: str  # Required for multi-tenant isolation
    name: str
    description: str
    project_id: str | None = None  # Optional project-level isolation
    tools: list[str] = field(default_factory=list)
    execution_template: dict[str, Any] = field(default_factory=dict)
    success_count: int = 0
    failure_count: int = 0
    usage_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        """Validate the composition."""
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")
        if not self.tools:
            raise ValueError("tools cannot be empty")
        if self.success_count < 0:
            raise ValueError("success_count must be non-negative")
        if self.failure_count < 0:
            raise ValueError("failure_count must be non-negative")
        if self.usage_count < 0:
            raise ValueError("usage_count must be non-negative")

    @property
    def success_rate(self) -> float:
        """
        Calculate the success rate of this composition.

        Returns:
            Success rate as a float between 0 and 1
        """
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0  # Assume success if never executed
        return self.success_count / total

    def get_primary_tool(self) -> str:
        """
        Get the first tool in the composition chain.

        Returns:
            Name of the primary tool
        """
        return self.tools[0] if self.tools else ""

    def can_execute_with(self, available_tools: set[str]) -> bool:
        """
        Check if all required tools are available.

        Args:
            available_tools: Set of available tool names

        Returns:
            True if all required tools are available
        """
        required_tools = set(self.tools)
        return required_tools.issubset(available_tools)

    def has_circular_dependency(self) -> bool:
        """
        Check if the composition has circular dependencies.

        A circular dependency occurs when a tool depends on itself
        either directly or indirectly through the chain.

        Returns:
            True if circular dependency detected
        """
        # Simple check: no tool should appear twice in the chain
        # More complex checks would require analyzing the execution_template
        return len(self.tools) != len(set(self.tools))

    def record_usage(self, success: bool) -> "ToolComposition":
        """
        Record a usage of this composition.

        Args:
            success: Whether the execution was successful

        Returns:
            Updated composition
        """
        return ToolComposition(
            id=self.id,
            tenant_id=self.tenant_id,
            name=self.name,
            description=self.description,
            project_id=self.project_id,
            tools=list(self.tools),
            execution_template=dict(self.execution_template),
            success_count=self.success_count + (1 if success else 0),
            failure_count=self.failure_count + (0 if success else 1),
            usage_count=self.usage_count + 1,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def get_fallback_tools(self) -> list[str]:
        """
        Get fallback alternative tools from the execution template.

        Returns:
            List of fallback tool names
        """
        return cast(list[str], self.execution_template.get("fallback_alternatives", []))

    def get_composition_type(self) -> str:
        """
        Get the type of composition (sequential, parallel, conditional).

        Returns:
            Composition type string
        """
        return cast(str, self.execution_template.get("type", "sequential"))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "tools": list(self.tools),
            "execution_template": dict(self.execution_template),
            "success_rate": self.success_rate,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def create(
        cls,
        tenant_id: str,
        name: str,
        description: str,
        tools: list[str],
        composition_type: str = "sequential",
        fallback_alternatives: list[str] | None = None,
        project_id: str | None = None,
    ) -> "ToolComposition":
        """
        Create a new tool composition.

        Args:
            tenant_id: Tenant identifier for multi-tenant isolation
            name: Human-readable name
            description: What this composition does
            tools: Ordered list of tool names
            composition_type: Type of composition (sequential, parallel, conditional)
            fallback_alternatives: Optional list of alternative tools
            project_id: Optional project identifier for project-level isolation

        Returns:
            New tool composition
        """
        import uuid

        execution_template = {
            "type": composition_type,
            "fallback_alternatives": fallback_alternatives or [],
        }

        return cls(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            description=description,
            project_id=project_id,
            tools=tools,
            execution_template=execution_template,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolComposition":
        """Create from dictionary (e.g., from database)."""

        # Handle ISO 8601 timestamps with 'Z' suffix
        def parse_timestamp(timestamp_str: str) -> datetime:
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            return datetime.fromisoformat(timestamp_str)

        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            project_id=data.get("project_id"),
            tools=data.get("tools", []),
            execution_template=data.get("execution_template", {}),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            usage_count=data.get("usage_count", 0),
            created_at=parse_timestamp(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
            updated_at=parse_timestamp(data["updated_at"])
            if "updated_at" in data
            else datetime.now(UTC),
        )


# Default composition templates
DEFAULT_SEQUENTIAL_TEMPLATE = {
    "type": "sequential",
    "fallback_alternatives": [],
}

DEFAULT_PARALLEL_TEMPLATE = {
    "type": "parallel",
    "aggregation": "merge",  # or "concatenate", "prioritize"
    "fallback_alternatives": [],
}

DEFAULT_CONDITIONAL_TEMPLATE = {
    "type": "conditional",
    "condition": None,  # To be filled with specific condition
    "fallback_alternatives": [],
}
