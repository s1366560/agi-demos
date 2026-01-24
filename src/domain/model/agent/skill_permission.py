"""Skill Permission System - Three-state permission control for skills.

Reference: vendor/opencode/packages/opencode/src/permission/next.ts

Implements allow/deny/ask permission control with wildcard pattern matching.
This provides fine-grained access control for skills based on configurable rules.

Features:
- Three-state permission: ALLOW, DENY, ASK
- Wildcard pattern matching (e.g., "dangerous-*", "*")
- Last-match-wins rule evaluation (later rules override earlier ones)
- Default to ASK if no rule matches
"""

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class SkillPermissionAction(str, Enum):
    """Permission action for skill access.

    Reference: OpenCode PermissionAction
    """

    ALLOW = "allow"  # Permission granted automatically
    DENY = "deny"  # Permission denied, raises error
    ASK = "ask"  # Requires user confirmation


@dataclass(frozen=True)
class SkillPermissionRule:
    """A rule that defines permission for matching skill patterns.

    Attributes:
        pattern: Skill name pattern (supports wildcards like "*", "dangerous-*")
        action: Permission action to take when pattern matches
        description: Optional human-readable description of this rule

    Examples:
        SkillPermissionRule("*", SkillPermissionAction.ASK)  # Ask for all skills
        SkillPermissionRule("code-*", SkillPermissionAction.ALLOW)  # Allow code-* skills
        SkillPermissionRule("dangerous-*", SkillPermissionAction.DENY)  # Deny dangerous-* skills
    """

    pattern: str
    action: SkillPermissionAction
    description: Optional[str] = None

    def __post_init__(self):
        """Validate the rule."""
        if not self.pattern:
            raise ValueError("pattern cannot be empty")

    def matches(self, skill_name: str) -> bool:
        """Check if this rule matches a skill name.

        Uses fnmatch for Unix shell-style wildcard matching:
        - * matches everything
        - ? matches any single character
        - [seq] matches any character in seq
        - [!seq] matches any character not in seq

        Args:
            skill_name: Name of the skill to check

        Returns:
            True if the pattern matches the skill name
        """
        return fnmatch.fnmatch(skill_name, self.pattern)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "pattern": self.pattern,
            "action": self.action.value,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillPermissionRule":
        """Create from dictionary."""
        return cls(
            pattern=data["pattern"],
            action=SkillPermissionAction(data["action"]),
            description=data.get("description"),
        )


@dataclass
class SkillPermissionRuleset:
    """A collection of skill permission rules.

    Rules are evaluated in order, with later rules taking precedence
    over earlier ones (last-match-wins).

    Attributes:
        rules: List of permission rules
        name: Optional name for this ruleset
    """

    rules: List[SkillPermissionRule] = field(default_factory=list)
    name: Optional[str] = None

    def add_rule(self, rule: SkillPermissionRule) -> None:
        """Add a rule to the ruleset."""
        self.rules.append(rule)

    def add_rules(self, rules: List[SkillPermissionRule]) -> None:
        """Add multiple rules to the ruleset."""
        self.rules.extend(rules)

    def evaluate(self, skill_name: str) -> SkillPermissionAction:
        """Evaluate permission for a skill.

        Uses last-match-wins strategy: iterates through rules in reverse
        and returns the action of the first matching rule.

        Args:
            skill_name: Name of the skill to check

        Returns:
            Permission action (defaults to ASK if no rule matches)
        """
        for rule in reversed(self.rules):
            if rule.matches(skill_name):
                return rule.action
        return SkillPermissionAction.ASK  # Default to ask

    def get_matching_rule(self, skill_name: str) -> Optional[SkillPermissionRule]:
        """Get the matching rule for a skill.

        Args:
            skill_name: Name of the skill to check

        Returns:
            The matching rule, or None if no rule matches
        """
        for rule in reversed(self.rules):
            if rule.matches(skill_name):
                return rule
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "rules": [rule.to_dict() for rule in self.rules],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillPermissionRuleset":
        """Create from dictionary."""
        return cls(
            name=data.get("name"),
            rules=[SkillPermissionRule.from_dict(r) for r in data.get("rules", [])],
        )


def evaluate_skill_permission(
    skill_name: str,
    rules: List[SkillPermissionRule],
) -> SkillPermissionAction:
    """Evaluate skill permission using a list of rules.

    Convenience function for evaluating permission without creating a ruleset.

    Args:
        skill_name: Name of the skill to check
        rules: List of permission rules

    Returns:
        Permission action (defaults to ASK if no rule matches)
    """
    for rule in reversed(rules):
        if rule.matches(skill_name):
            return rule.action
    return SkillPermissionAction.ASK


def default_skill_ruleset() -> SkillPermissionRuleset:
    """Create a default skill permission ruleset.

    Default rules:
    - Allow all skills by default (can be overridden per-agent)

    Returns:
        Default ruleset
    """
    return SkillPermissionRuleset(
        name="default",
        rules=[
            SkillPermissionRule(
                pattern="*",
                action=SkillPermissionAction.ALLOW,
                description="Allow all skills by default",
            ),
        ],
    )


def restricted_skill_ruleset() -> SkillPermissionRuleset:
    """Create a restricted skill permission ruleset.

    Restricted rules:
    - Ask for all skills by default
    - Deny dangerous-* skills

    Returns:
        Restricted ruleset
    """
    return SkillPermissionRuleset(
        name="restricted",
        rules=[
            SkillPermissionRule(
                pattern="*",
                action=SkillPermissionAction.ASK,
                description="Ask for all skills by default",
            ),
            SkillPermissionRule(
                pattern="dangerous-*",
                action=SkillPermissionAction.DENY,
                description="Deny dangerous skills",
            ),
        ],
    )


def merge_rulesets(*rulesets: SkillPermissionRuleset) -> SkillPermissionRuleset:
    """Merge multiple rulesets into one.

    Rules from later rulesets take precedence over earlier ones.

    Args:
        *rulesets: Rulesets to merge

    Returns:
        Merged ruleset
    """
    merged = SkillPermissionRuleset(name="merged")
    for ruleset in rulesets:
        merged.add_rules(ruleset.rules)
    return merged
