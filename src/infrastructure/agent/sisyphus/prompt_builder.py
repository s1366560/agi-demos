"""Dynamic prompt builder for the built-in Sisyphus agent."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SisyphusPromptContext:
    """Runtime context used to build the Sisyphus system prompt."""

    model_name: str
    max_steps: int
    tools: list[Any]
    skills: list[Any]
    subagents: list[Any]


class SisyphusPromptBuilder:
    """Build the primary system prompt for the built-in Sisyphus agent."""

    def build(self, context: SisyphusPromptContext) -> str:
        """Return the fully rendered Sisyphus prompt."""
        sections = [
            self._build_identity_section(context),
            self._build_operating_model_section(context),
            self._build_capabilities_section(context),
            self._build_model_overlay(context.model_name),
        ]
        return "\n\n".join(section for section in sections if section)

    def _build_identity_section(self, context: SisyphusPromptContext) -> str:
        return (
            "# Sisyphus\n"
            "You are Sisyphus, the primary orchestration agent. Your job is to turn user intent into a "
            "finished result by planning only as much as needed, using tools aggressively, and driving "
            "execution forward without waiting for avoidable confirmation.\n\n"
            f"You may use up to {context.max_steps} main reasoning steps in this session."
        )

    def _build_operating_model_section(self, context: SisyphusPromptContext) -> str:
        return (
            "## Operating Model\n"
            "1. Move from understanding to execution quickly.\n"
            "2. Use todo tracking when the work spans multiple actions.\n"
            "3. Prefer direct tool use over telling the user what should be done.\n"
            "4. Delegate only when a specialized skill or subagent is materially better.\n"
            "5. When you stop, leave the user with a stable outcome, not an unfinished thought.\n"
            "6. Treat tool output as the source of truth and adjust the plan after each observation."
        )

    def _build_capabilities_section(self, context: SisyphusPromptContext) -> str:
        tool_lines = self._render_tools(context.tools)
        skill_lines = self._render_named_items(context.skills, "name", "description")
        subagent_lines = self._render_named_items(context.subagents, "name", "description")
        sections = [
            "## Available Runtime Capabilities",
            tool_lines,
            "### Skills\n" + (skill_lines or "- No skills are currently loaded."),
            "### Subagents\n" + (subagent_lines or "- No subagents are currently available."),
        ]
        return "\n\n".join(sections)

    def _render_tools(self, tools: list[Any]) -> str:
        if not tools:
            return "### Tools\n- No tools are currently available."

        grouped: dict[str, list[str]] = defaultdict(list)
        for tool in tools:
            name = str(getattr(tool, "name", "")).strip()
            if not name:
                continue
            category = str(getattr(tool, "category", "general")).strip() or "general"
            description = str(getattr(tool, "description", "")).strip()
            grouped[category].append(f"- `{name}`: {description}" if description else f"- `{name}`")

        if not grouped:
            return "### Tools\n- No tools are currently available."

        sections = ["### Tools"]
        for category in sorted(grouped):
            sections.append(f"#### {category}")
            sections.extend(grouped[category])
        return "\n".join(sections)

    def _render_named_items(
        self,
        items: list[Any],
        name_attr: str,
        description_attr: str,
    ) -> str:
        lines: list[str] = []
        for item in items:
            name = str(getattr(item, name_attr, "")).strip()
            if not name:
                continue
            description = str(getattr(item, description_attr, "")).strip()
            lines.append(f"- `{name}`: {description}" if description else f"- `{name}`")
        return "\n".join(lines)

    def _build_model_overlay(self, model_name: str) -> str:
        normalized = (model_name or "").strip().lower()
        if "gpt-5" in normalized:
            return (
                "## Model Overlay\n"
                "You are running on a GPT-5 family model. Keep reasoning tight, favor decisive tool calls, "
                "and avoid verbose preambles before acting."
            )
        if "gemini" in normalized:
            return (
                "## Model Overlay\n"
                "You are running on a Gemini family model. Make the next action explicit, keep state "
                "consistent across turns, and restate the execution goal before delegating."
            )
        return (
            "## Model Overlay\n"
            "Be concise, execution-oriented, and resilient to partial progress."
        )
