"""
Built-in system skills for MemStack.

System skills are read-only and shared by all tenants.
They can be disabled or overridden at the tenant level.
"""

from pathlib import Path

# Path to the builtin skills directory
BUILTIN_SKILLS_DIR = Path(__file__).parent / "skills"


def get_builtin_skills_path() -> Path:
    """Get the path to the builtin skills directory."""
    return BUILTIN_SKILLS_DIR
