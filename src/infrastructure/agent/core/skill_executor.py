"""
Backward compatibility redirect.

SkillExecutor has been moved to src.infrastructure.agent.skill.skill_executor
This file provides backward compatibility for existing imports.
"""

from src.infrastructure.agent.skill.skill_executor import (
    SkillExecutionResult,
    SkillExecutor,
)

__all__ = ["SkillExecutor", "SkillExecutionResult"]
