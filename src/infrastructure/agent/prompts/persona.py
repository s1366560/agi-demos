"""First-class persona types for the agent soul/identity system.

Elevates soul/identity/user-profile from optional strings to structured,
validated types with metadata (source tracking, truncation info, diagnostics).

Design reference: OpenClaw's system-prompt-report.ts and identity-file.ts.

Classes:
    PersonaSource: Enum tracking where persona content originated.
    PersonaField: Single persona field with metadata.
    AgentPersona: Complete persona container (soul + identity + user_profile).
    PromptSectionEntry: Single section in a prompt report.
    PromptReport: Diagnostic report of what sections were included in a prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class PersonaSource(str, Enum):
    """Origin of a persona field's content.

    Attributes:
        WORKSPACE: Loaded from .memstack/workspace/ in the sandbox (project-level).
        TEMPLATE: Fell back to the default template in prompts/workspace/.
        TENANT: Loaded from tenant-level workspace directory.
        CONFIG: Provided via API/config (future use).
        NONE: No content was loaded.
    """

    WORKSPACE = "workspace"
    TEMPLATE = "template"
    TENANT = "tenant"
    CONFIG = "config"
    NONE = "none"


@dataclass(frozen=True)
class PersonaField:
    """A single persona field with its content and metadata.

    Attributes:
        content: The text content (possibly truncated). Empty string when absent.
        source: Where the content was loaded from.
        raw_chars: Original character count before truncation.
        injected_chars: Character count after truncation.
        is_truncated: Whether the content was truncated.
        filename: The source filename (e.g. "SOUL.md").
    """

    content: str = ""
    source: PersonaSource = PersonaSource.NONE
    raw_chars: int = 0
    injected_chars: int = 0
    is_truncated: bool = False
    filename: str = ""

    @property
    def is_loaded(self) -> bool:
        """Check if this field has meaningful content."""
        return bool(self.content) and self.source != PersonaSource.NONE

    @staticmethod
    def empty(filename: str = "") -> PersonaField:
        """Create an empty persona field."""
        return PersonaField(filename=filename)


@dataclass(frozen=True)
class AgentPersona:
    """Complete persona container: soul + identity + user_profile.

    This is the first-class citizen type for persona data in the prompt
    pipeline. It replaces bare ``str | None`` fields throughout the system.

    Attributes:
        soul: The agent's personality/soul definition (SOUL.md).
        identity: The agent's identity definition (IDENTITY.md).
        user_profile: The user's profile/preferences (USER.md).
        agents: The project's agent configuration (AGENTS.md).
        tools: The project's tool configuration (TOOLS.md).
    """

    soul: PersonaField = field(default_factory=lambda: PersonaField.empty("SOUL.md"))
    identity: PersonaField = field(
        default_factory=lambda: PersonaField.empty("IDENTITY.md"),
    )
    user_profile: PersonaField = field(
        default_factory=lambda: PersonaField.empty("USER.md"),
    )
    agents: PersonaField = field(default_factory=lambda: PersonaField.empty("AGENTS.md"))
    tools: PersonaField = field(
        default_factory=lambda: PersonaField.empty("TOOLS.md"),
    )

    @property
    def has_any(self) -> bool:
        """Check if any persona field has content."""
        return self.soul.is_loaded or self.identity.is_loaded or self.user_profile.is_loaded or self.agents.is_loaded or self.tools.is_loaded

    @property
    def total_chars(self) -> int:
        """Total injected characters across all persona fields."""
        return (
            self.soul.injected_chars
            + self.identity.injected_chars
            + self.user_profile.injected_chars
            + self.agents.injected_chars
            + self.tools.injected_chars
        )

    @property
    def total_raw_chars(self) -> int:
        """Total raw characters before truncation across all fields."""
        return self.soul.raw_chars + self.identity.raw_chars + self.user_profile.raw_chars + self.agents.raw_chars + self.tools.raw_chars

    @property
    def any_truncated(self) -> bool:
        """Check if any field was truncated."""
        return (
            self.soul.is_truncated or self.identity.is_truncated or self.user_profile.is_truncated
            or self.agents.is_truncated
            or self.tools.is_truncated
        )

    def loaded_fields(self) -> list[PersonaField]:
        """Return only the fields that have content."""
        return [f for f in (self.soul, self.identity, self.user_profile, self.agents, self.tools) if f.is_loaded]

    @staticmethod
    def empty() -> AgentPersona:
        """Create an empty persona with no content."""
        return AgentPersona()

    # --- Backward-compatible accessors for PromptContext migration ---

    @property
    def soul_text(self) -> str | None:
        """Backward-compatible accessor for soul content."""
        return self.soul.content if self.soul.is_loaded else None

    @property
    def identity_text(self) -> str | None:
        """Backward-compatible accessor for identity content."""
        return self.identity.content if self.identity.is_loaded else None

    @property
    def user_profile_text(self) -> str | None:
        """Backward-compatible accessor for user profile content."""
        return self.user_profile.content if self.user_profile.is_loaded else None
    @property
    def agents_text(self) -> str | None:
        """Backward-compatible accessor for agents content."""
        return self.agents.content if self.agents.is_loaded else None

    @property
    def tools_text(self) -> str | None:
        """Backward-compatible accessor for tools content."""
        return self.tools.content if self.tools.is_loaded else None


@dataclass(frozen=True)
class PromptSectionEntry:
    """A single section entry in the prompt report.

    Attributes:
        name: Section name (e.g. "base_prompt", "soul", "tools").
        chars: Character count of this section.
        included: Whether this section was included in the final prompt.
        source: Optional source info (e.g. "workspace", "template").
        truncated: Whether this section was truncated.
    """

    name: str
    chars: int = 0
    included: bool = True
    source: str = ""
    truncated: bool = False


@dataclass
class PromptReport:
    """Diagnostic report of what was included in a system prompt.

    Tracks all sections, their character counts, and whether they were
    included. Useful for debugging prompt assembly and monitoring token
    budgets.

    Reference: OpenClaw's system-prompt-report.ts.

    Attributes:
        sections: Ordered list of section entries.
        total_chars: Total character count of the assembled prompt.
        persona: The AgentPersona used (for persona-specific diagnostics).
        warnings: Any warnings generated during prompt assembly.
    """

    sections: list[PromptSectionEntry] = field(default_factory=list)
    total_chars: int = 0
    persona: AgentPersona = field(default_factory=AgentPersona.empty)
    warnings: list[str] = field(default_factory=list)

    def add_section(
        self,
        name: str,
        content: str,
        *,
        source: str = "",
        truncated: bool = False,
    ) -> None:
        """Record a section that was included in the prompt."""
        self.sections.append(
            PromptSectionEntry(
                name=name,
                chars=len(content),
                included=True,
                source=source,
                truncated=truncated,
            ),
        )

    def add_skipped(self, name: str, reason: str = "") -> None:
        """Record a section that was skipped."""
        self.sections.append(
            PromptSectionEntry(name=name, chars=0, included=False, source=reason),
        )

    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)
        logger.warning("Prompt assembly warning: %s", warning)

    @property
    def included_section_count(self) -> int:
        """Number of sections that were included."""
        return sum(1 for s in self.sections if s.included)

    def summary(self) -> str:
        """Human-readable summary of the prompt report."""
        lines = [f"Prompt Report: {self.total_chars} chars, {self.included_section_count} sections"]
        for section in self.sections:
            status = "OK" if section.included else "SKIPPED"
            trunc = " [TRUNCATED]" if section.truncated else ""
            src = f" ({section.source})" if section.source else ""
            lines.append(f"  [{status}] {section.name}: {section.chars} chars{trunc}{src}")
        if self.warnings:
            lines.append("  Warnings:")
            for w in self.warnings:
                lines.append(f"    - {w}")
        return "\n".join(lines)
