"""Helpers for loading builtin memory extraction skill prompts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from plugins.business.agent.skill_validation.markdown_parser import (
    MarkdownParseError,
    MarkdownParser,
)
from src.builtin import get_builtin_skills_path

MEMORY_CAPTURE_SKILL_NAME = "memory-capture-extraction"
MEMORY_FLUSH_SKILL_NAME = "memory-flush-extraction"


def get_memory_capture_prompt() -> str:
    """Return the builtin prompt used for turn-level memory capture."""
    return load_builtin_skill_prompt(MEMORY_CAPTURE_SKILL_NAME)


def get_memory_flush_prompt() -> str:
    """Return the builtin prompt used for pre-compaction memory flush."""
    return load_builtin_skill_prompt(MEMORY_FLUSH_SKILL_NAME)


@lru_cache(maxsize=8)
def load_builtin_skill_prompt(skill_name: str) -> str:
    """Load prompt content from a builtin SKILL.md file."""
    skill_path = _get_builtin_skill_file(skill_name)
    markdown = MarkdownParser().parse_file(str(skill_path))
    content = markdown.content.strip()
    if not content:
        raise MarkdownParseError("Builtin skill content is empty", str(skill_path))
    return content


def _get_builtin_skill_file(skill_name: str) -> Path:
    """Resolve the SKILL.md path for a builtin skill."""
    return get_builtin_skills_path() / skill_name / "SKILL.md"
