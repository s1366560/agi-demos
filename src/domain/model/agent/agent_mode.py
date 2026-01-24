"""AgentMode enum for agent operation modes.

Defines the operating modes for the Agent system:
- BUILD: Full permissions, development work
- PLAN: Read-only + Plan editing, planning and design
- EXPLORE: Pure read-only, code exploration (SubAgent mode)
"""

from enum import Enum


class AgentMode(str, Enum):
    """Agent operation mode.

    BUILD: Full permissions for development work. Can read, write, edit files,
           run commands, and perform all operations.

    PLAN: Read-only mode with Plan document editing. Used for exploration and
          planning before implementation. Can read code, search, and edit the
          Plan document, but cannot modify project files.

    EXPLORE: Pure read-only mode for code exploration. Used as a SubAgent in
             Plan mode. Can only read files, search, and navigate the codebase.
    """

    BUILD = "build"
    PLAN = "plan"
    EXPLORE = "explore"
