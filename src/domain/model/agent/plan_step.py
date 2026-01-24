"""PlanStep value object for work plan steps."""

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class PlanStep:
    """A single step in a work-level plan.

    Attributes:
        step_number: Sequential number of this step in the plan
        description: Human-readable description of what this step does
        thought_prompt: Prompt to guide task-level thinking for this step
        required_tools: List of tool names needed for this step
        expected_output: Description of what this step should produce
        dependencies: List of step numbers that must complete before this step
    """

    step_number: int
    description: str
    thought_prompt: str
    required_tools: list[str]
    expected_output: str
    dependencies: list[int]

    def is_ready(self, completed_steps: set[int]) -> bool:
        """Check if this step's dependencies are met.

        Args:
            completed_steps: Set of step numbers that have been completed

        Returns:
            True if all dependencies are satisfied, False otherwise
        """
        return set(self.dependencies).issubset(completed_steps)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation of this step
        """
        return asdict(self)

    def __post_init__(self) -> None:
        """Validate the plan step."""
        if self.step_number < 0:
            raise ValueError("step_number must be non-negative")
        if not self.description:
            raise ValueError("description cannot be empty")
        if not self.thought_prompt:
            raise ValueError("thought_prompt cannot be empty")
        if not self.expected_output:
            raise ValueError("expected_output cannot be empty")
        for dep in self.dependencies:
            if dep < 0:
                raise ValueError(f"Dependency step number must be non-negative, got {dep}")
            if dep == self.step_number:
                raise ValueError("Step cannot depend on itself")
