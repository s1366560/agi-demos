"""Validates filesystem-loaded SubAgent definitions for safety and correctness."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import ClassVar

from src.infrastructure.agent.subagent.markdown_parser import SubAgentMarkdown

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a SubAgent definition.

    Attributes:
        valid: Whether the definition passed all error-level checks.
        errors: Hard failures that prevent loading.
        warnings: Soft issues logged but not blocking.
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SubAgentValidator:
    """Validates parsed SubAgent markdown definitions.

    Checks safety constraints (restricted tools, prompt length) and
    correctness constraints (required fields, numeric ranges) before
    a definition is promoted to a SubAgent domain entity.
    """

    RESTRICTED_TOOLS: ClassVar[set[str]] = {"plugin_manager", "env_var_set"}
    MAX_PROMPT_LENGTH: ClassVar[int] = 50_000
    KNOWN_MODELS: ClassVar[set[str]] = {
        "inherit",
        "opus",
        "sonnet",
        "haiku",
        "gpt-4",
        "gpt-4o",
        "gemini",
        "gemini-pro",
        "qwen-max",
        "qwen-plus",
        "deepseek",
        "deepseek-chat",
        "claude-3-5-sonnet",
        "claude-sonnet",
    }

    def validate(self, markdown: SubAgentMarkdown) -> ValidationResult:
        """Validate a parsed SubAgent markdown definition.

        Args:
            markdown: Parsed markdown to validate.

        Returns:
            ValidationResult with errors (blocking) and warnings (informational).
        """
        errors: list[str] = []
        warnings: list[str] = []

        self._check_identity_fields(markdown, errors, warnings)
        self._check_safety_constraints(markdown, errors, warnings)
        self._check_numeric_ranges(markdown, errors)

        # mode validation (defense in depth -- parser should catch this)
        if markdown.mode not in ("subagent", "primary", "all"):
            errors.append("mode must be one of 'subagent', 'primary', 'all'")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Private validation groups
    # ------------------------------------------------------------------

    def _check_identity_fields(
        self,
        markdown: SubAgentMarkdown,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """Validate name and description fields."""
        if not markdown.name or not markdown.name.strip():
            errors.append("name must not be empty")
        elif len(markdown.name) > 100:
            errors.append("name must be 1-100 characters")

        if not markdown.description or not markdown.description.strip():
            warnings.append("description is empty - agent may not be routable")

    def _check_safety_constraints(
        self,
        markdown: SubAgentMarkdown,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """Validate prompt length, restricted tools, spawn, and model."""
        if len(markdown.content) > self.MAX_PROMPT_LENGTH:
            errors.append(
                f"system prompt exceeds maximum length of {self.MAX_PROMPT_LENGTH} characters"
            )

        if markdown.tools:
            tool_set = {t.lower() for t in markdown.tools}
            restricted = tool_set & self.RESTRICTED_TOOLS
            if restricted:
                restricted_names = ", ".join(sorted(restricted))
                errors.append(
                    f"restricted tools not allowed for filesystem agents: {restricted_names}"
                )

        if markdown.allow_spawn and not markdown.tools:
            warnings.append("allow_spawn is true but no tools are defined")

        if markdown.model_raw not in self.KNOWN_MODELS:
            warnings.append(
                f"unrecognized model '{markdown.model_raw}' - will fall back to inherit"
            )

    @staticmethod
    def _check_numeric_ranges(
        markdown: SubAgentMarkdown,
        errors: list[str],
    ) -> None:
        """Validate numeric configuration ranges."""
        if markdown.temperature is not None and not (0.0 <= markdown.temperature <= 2.0):
            errors.append("temperature must be between 0.0 and 2.0")

        if markdown.max_iterations is not None and not (1 <= markdown.max_iterations <= 50):
            errors.append("max_iterations must be between 1 and 50")

        if markdown.max_tokens is not None and not (1 <= markdown.max_tokens <= 1_000_000):
            errors.append("max_tokens must be between 1 and 1000000")

        if markdown.max_retries is not None and not (0 <= markdown.max_retries <= 10):
            errors.append("max_retries must be between 0 and 10")
