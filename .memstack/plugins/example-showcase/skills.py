"""Example skill factory for the showcase plugin.

Skill factories receive a PluginSkillBuildContext and return a dict of
skill_name -> skill_definition_dict. Each skill dict maps to a Skill domain
entity via the plugin_skills bridge module.

Required fields in each skill dict:
  - name: str
  - description: str
  - content: str (Markdown instructions for the agent)
  - trigger_keywords: list[str] (activation keywords)
"""

from __future__ import annotations

from typing import Any


def showcase_skill_factory(context: Any) -> dict[str, dict[str, Any]]:
    """Build showcase skills.

    Args:
        context: PluginSkillBuildContext with project_id, tenant_id, etc.

    Returns:
        Dict mapping skill name to skill definition dict.
    """
    return {
        "showcase-greeting": {
            "name": "showcase-greeting",
            "description": "A greeting skill that teaches the agent how to greet users in multiple languages.",
            "content": _GREETING_SKILL_CONTENT,
            "trigger_keywords": ["greet", "hello", "hi", "greeting", "welcome"],
        },
        "showcase-summary": {
            "name": "showcase-summary",
            "description": "A summary skill that teaches the agent how to produce concise summaries.",
            "content": _SUMMARY_SKILL_CONTENT,
            "trigger_keywords": ["summarize", "summary", "tldr", "brief"],
        },
    }


_GREETING_SKILL_CONTENT = """\
# Greeting Skill

Greet the user warmly in the appropriate language.

## Guidelines

- Detect the user's language from their message
- Respond with a culturally appropriate greeting
- Keep greetings concise (1-2 sentences)
- If language is ambiguous, default to the project's primary language

## Examples

| User Says | Response |
|-----------|----------|
| "Hello" | "Hello! How can I help you today?" |
| "Bonjour" | "Bonjour! Comment puis-je vous aider?" |
"""

_SUMMARY_SKILL_CONTENT = """\
# Summary Skill

Produce a concise summary of the provided content.

## Guidelines

- Keep summaries under 3 sentences unless the user requests more detail
- Preserve key facts, names, and numbers
- Use bullet points for multi-topic content
- Start with the most important information

## Output Format

**Summary:** <1-3 sentence summary>

**Key Points:**
- Point 1
- Point 2
"""
