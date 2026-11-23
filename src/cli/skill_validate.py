"""Compatibility entry point for the independently distributed Skill validator."""

from plugins.business.agent.skill_validation.cli import (
    main,
    validate_all,
    validate_single,
)

__all__ = ["main", "validate_all", "validate_single"]


if __name__ == "__main__":
    main()
