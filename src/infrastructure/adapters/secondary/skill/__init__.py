"""
Skill Resource Adapters Package.

Provides implementations of SkillResourcePort for different environments:
- LocalSkillResourceAdapter: Direct local file system access
- SandboxSkillResourceAdapter: Remote container injection via MCP
"""

from src.infrastructure.adapters.secondary.skill.local_skill_resource_adapter import (
    LocalSkillResourceAdapter,
)
from src.infrastructure.adapters.secondary.skill.sandbox_skill_resource_adapter import (
    SandboxSkillResourceAdapter,
)

__all__ = [
    "LocalSkillResourceAdapter",
    "SandboxSkillResourceAdapter",
]
