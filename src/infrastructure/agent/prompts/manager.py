"""
System Prompt Manager - Core class for managing and assembling system prompts.

This module implements a modular prompt management system inspired by
OpenCode's system.ts architecture.

Key features:
- Multi-model adaptation (different prompts for Claude, Gemini, Qwen)
- Dynamic mode management (Plan/Build modes)
- Environment context injection
- Custom rules loading (.memstack/AGENTS.md, CLAUDE.md)
- File-based prompt templates with caching
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PromptMode(str, Enum):
    """Agent execution mode."""

    BUILD = "build"
    PLAN = "plan"


class ModelProvider(str, Enum):
    """LLM provider types for prompt adaptation."""

    ANTHROPIC = "anthropic"  # Claude models
    GEMINI = "gemini"  # Google Gemini
    QWEN = "qwen"  # Alibaba Qwen
    DEEPSEEK = "deepseek"  # Deepseek
    ZHIPU = "zhipu"  # ZhipuAI
    OPENAI = "openai"  # OpenAI GPT
    DEFAULT = "default"  # Default/fallback


@dataclass
class PromptContext:
    """
    Context for building system prompts.

    Contains all the dynamic information needed to assemble
    a complete system prompt for the agent.
    """

    # Model and mode
    model_provider: ModelProvider
    mode: PromptMode = PromptMode.BUILD

    # Tools and capabilities
    tool_definitions: List[Dict[str, Any]] = field(default_factory=list)
    skills: Optional[List[Dict[str, Any]]] = None
    subagents: Optional[List[Dict[str, Any]]] = None
    matched_skill: Optional[Dict[str, Any]] = None

    # Project context
    project_id: str = ""
    tenant_id: str = ""
    working_directory: str = ""

    # Conversation state
    conversation_history_length: int = 0
    user_query: str = ""

    # Execution state
    current_step: int = 1
    max_steps: int = 50

    @property
    def is_last_step(self) -> bool:
        """Check if this is the last allowed step."""
        return self.current_step >= self.max_steps


class SystemPromptManager:
    """
    System Prompt Manager - Assembles complete system prompts for the agent.

    This class manages the loading, caching, and assembly of system prompts
    from multiple sources:
    - Base prompts (model-specific)
    - Mode reminders (Plan/Build)
    - Section modules (safety, memory guidance)
    - Environment context
    - Custom rules (.memstack/AGENTS.md, CLAUDE.md)

    Reference: OpenCode's SystemPrompt namespace (system.ts)
    """

    # File extensions for custom rules
    RULE_FILE_NAMES = [".memstack/AGENTS.md", "CLAUDE.md"]

    # Default sandbox workspace path - Agent should only see sandbox, not host filesystem
    DEFAULT_SANDBOX_WORKSPACE = Path("/workspace")

    def __init__(
        self,
        prompts_dir: Optional[Path] = None,
        project_root: Optional[Path] = None,
    ):
        """
        Initialize the SystemPromptManager.

        Args:
            prompts_dir: Directory containing prompt template files.
                        Defaults to the prompts directory in this module.
            project_root: Root directory of the project for loading custom rules.
                         Defaults to sandbox workspace (/workspace).
        """
        self.prompts_dir = prompts_dir or Path(__file__).parent
        # Always use sandbox workspace path, never expose host filesystem
        self.project_root = project_root or self.DEFAULT_SANDBOX_WORKSPACE
        self._cache: Dict[str, str] = {}

    async def build_system_prompt(
        self,
        context: PromptContext,
        subagent: Optional[Any] = None,
    ) -> str:
        """
        Build the complete system prompt for the agent.

        Assembly order:
        1. SubAgent override (if provided)
        2. Base system prompt (model-specific)
        3. Forced skill injection (if user specified /skill-name, placed here
           for maximum LLM attention; skips skills listing to reduce noise)
        4. Tools section
        5. Skills section (skipped when forced skill is active)
        6. Non-forced skill recommendation (confidence-based match)
        7. Environment context
        8. Mode reminder (Plan/Build)
        9. Max steps warning (if applicable)
        10. Custom rules (.memstack/AGENTS.md)

        Args:
            context: The prompt context containing all dynamic information.
            subagent: Optional SubAgent instance. If provided with a
                     system_prompt, it overrides all other prompts.

        Returns:
            Complete system prompt string.
        """
        # 1. SubAgent override takes priority
        if subagent and hasattr(subagent, "system_prompt") and subagent.system_prompt:
            logger.debug(f"Using SubAgent system prompt: {subagent.name}")
            return subagent.system_prompt

        sections: List[str] = []

        # Check if we have a forced skill (highest priority injection)
        is_forced_skill = (
            context.matched_skill
            and context.matched_skill.get("force_execution", False)
        )

        # 2. Base system prompt (model-specific)
        base_prompt = await self._load_base_prompt(context.model_provider)
        if base_prompt:
            sections.append(base_prompt)

        # 3. Forced skill injection (immediately after base prompt for maximum attention)
        if is_forced_skill:
            skill_injection = self._build_skill_recommendation(context.matched_skill)
            sections.append(skill_injection)

        # 4. Section modules (safety, memory guidance) - embedded in base prompt
        # Note: These are included in the base prompt files for better organization

        # 5. Tools section
        tools_section = self._build_tools_section(context)
        if tools_section:
            sections.append(tools_section)

        # 6. Skills section (skip when forced skill is active to reduce noise)
        if context.skills and not is_forced_skill:
            skill_section = self._build_skill_section(context)
            if skill_section:
                sections.append(skill_section)

        # 6.5. SubAgents section (available specialized agents for delegation)
        if context.subagents:
            subagent_section = self._build_subagent_section(context)
            if subagent_section:
                sections.append(subagent_section)

        # 7. Non-forced skill recommendation (confidence-based match)
        if context.matched_skill and not is_forced_skill:
            skill_recommendation = self._build_skill_recommendation(context.matched_skill)
            sections.append(skill_recommendation)

        # 7. Environment context
        env_context = self._build_environment_context(context)
        sections.append(env_context)

        # 7.5. Workspace filesystem guidelines
        workspace_guidelines = await self._load_file("sections/workspace.txt")
        if workspace_guidelines:
            sections.append(workspace_guidelines)

        # 8. Mode reminder
        mode_reminder = await self._load_mode_reminder(context.mode)
        if mode_reminder:
            sections.append(mode_reminder)

        # 9. Max steps warning
        if context.is_last_step:
            max_steps_warning = await self._load_file("reminders/max_steps.txt")
            if max_steps_warning:
                sections.append(max_steps_warning)

        # 10. Custom rules (.memstack/AGENTS.md, CLAUDE.md)
        custom_rules = await self._load_custom_rules()
        if custom_rules:
            sections.append(custom_rules)

        return "\n\n".join(filter(None, sections))

    async def _load_base_prompt(self, provider: ModelProvider) -> str:
        """
        Load the base system prompt for a specific model provider.

        Args:
            provider: The model provider type.

        Returns:
            Base prompt content or empty string if not found.
        """
        filename_map = {
            ModelProvider.ANTHROPIC: "anthropic.txt",
            ModelProvider.GEMINI: "gemini.txt",
            ModelProvider.QWEN: "qwen.txt",
            ModelProvider.DEEPSEEK: "default.txt",  # Use default for now
            ModelProvider.ZHIPU: "qwen.txt",  # Similar to Qwen
            ModelProvider.OPENAI: "default.txt",
            ModelProvider.DEFAULT: "default.txt",
        }

        filename = filename_map.get(provider, "default.txt")
        return await self._load_file(f"system/{filename}")

    def _build_environment_context(self, context: PromptContext) -> str:
        """
        Build the environment context section.

        Reference: OpenCode system.ts:55-78

        Args:
            context: The prompt context.

        Returns:
            Environment context XML block.
        """
        # Always use sandbox workspace path - never expose host filesystem
        # Git status is detected within sandbox, not host
        workspace_path = context.working_directory or str(self.DEFAULT_SANDBOX_WORKSPACE)
        sandbox_git_dir = Path(workspace_path) / ".git"
        is_git_repo = sandbox_git_dir.exists() if Path(workspace_path).exists() else False

        return f"""<env>
Working Directory: {workspace_path}
Project ID: {context.project_id}
Is Git Repository: {"Yes" if is_git_repo else "No"}
Platform: Linux (Sandbox Container)
Current Time: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC (%A)")}
Conversation History: {context.conversation_history_length} messages
Current Step: {context.current_step}/{context.max_steps}
</env>"""

    def _build_tools_section(self, context: PromptContext) -> str:
        """
        Build the available tools section.

        Args:
            context: The prompt context.

        Returns:
            Tools section string.
        """
        if not context.tool_definitions:
            return ""

        tool_descriptions = "\n".join(
            [
                f"- {t.get('name', 'unknown')}: {t.get('description', '')}"
                for t in context.tool_definitions
            ]
        )

        section = f"""## Available Tools

{tool_descriptions}

Use these tools to search memories, query the knowledge graph, create memories, and interact with external services."""

        # Add Canvas hint when MCP tools are present
        mcp_tools = [
            t.get("name", "") for t in context.tool_definitions
            if t.get("name", "").startswith("mcp__")
        ]
        if mcp_tools:
            names = ", ".join(mcp_tools[:5])
            section += f"""

NOTE: The following MCP server tools may have interactive UIs that auto-render in Canvas when called: {names}. If these tools declare _meta.ui, their UI opens automatically."""

        return section

    def _build_skill_section(self, context: PromptContext) -> str:
        """
        Build the available skills section.

        Args:
            context: The prompt context.

        Returns:
            Skills section string or empty if no skills.
        """
        if not context.skills:
            return ""

        # Filter active skills
        active_skills = [s for s in context.skills if s.get("status") == "active"]

        if not active_skills:
            return ""

        # Limit to 5 skills to avoid prompt bloat
        skill_descs = "\n".join(
            [
                f"- {s.get('name', 'unknown')}: {s.get('description', '')} (tools: {', '.join(s.get('tools', []))})"
                for s in active_skills[:5]
            ]
        )

        return f"""## Available Skills (Pre-defined Tool Compositions)

{skill_descs}

When a skill matches the user's request, you can use its tools in sequence for optimal results."""

    def _build_subagent_section(self, context: PromptContext) -> str:
        """
        Build the available SubAgents section.

        Lists SubAgents with descriptions so the LLM can decide
        when to delegate via the delegate_to_subagent tool.
        Includes parallel delegation guidance when 2+ SubAgents exist.

        Args:
            context: The prompt context.

        Returns:
            SubAgents section string or empty if no subagents.
        """
        if not context.subagents:
            return ""

        subagent_descs = "\n".join(
            [
                f"- **{sa.get('name', 'unknown')}** ({sa.get('display_name', '')}): "
                f"{sa.get('trigger_description', sa.get('description', 'general tasks'))}"
                for sa in context.subagents
            ]
        )

        # Add parallel delegation guidance when multiple SubAgents available
        parallel_guidance = ""
        if len(context.subagents) >= 2:
            parallel_guidance = """

**Parallel execution**: When you have 2+ independent tasks for different SubAgents,
use `parallel_delegate_subagents` to run them simultaneously instead of calling
`delegate_to_subagent` multiple times sequentially."""

        return f"""## Available SubAgents (Specialized Autonomous Agents)

You have access to specialized SubAgents via the `delegate_to_subagent` tool.
Each SubAgent runs independently with its own context and tools.

{subagent_descs}

**When to delegate**: The task clearly matches a SubAgent's specialty and can be described as a self-contained unit.
**When NOT to delegate**: Simple questions, tasks requiring your current context, or tasks where you need intermediate results.{parallel_guidance}"""

    def _build_skill_recommendation(self, skill: Dict[str, Any]) -> str:
        """
        Build the skill injection section.

        Uses mandatory wording when force_execution is True (slash-command),
        otherwise uses recommendation wording (confidence-based match).

        Args:
            skill: The matched skill dictionary (may include force_execution flag).

        Returns:
            Skill injection XML block.
        """
        is_forced = skill.get("force_execution", False)
        name = skill.get("name", "unknown")
        description = skill.get("description", "")
        tools = ", ".join(skill.get("tools", []))

        if is_forced:
            content = f"""<mandatory-skill priority="highest">
IMPORTANT: The user has explicitly activated the skill "/{name}" via slash command.
This is your PRIMARY DIRECTIVE for this conversation turn.

You MUST:
1. Follow ALL skill instructions below exactly as specified
2. Use the skill's workflow, tools, and output format as described
3. Do NOT skip, summarize, or modify the execution plan
4. Do NOT ask for confirmation before executing - proceed immediately
5. Do NOT call the skill_loader tool - the skill instructions are already provided below
6. Do NOT load or switch to any other skill - only "{name}" is active

Skill: {name}
Description: {description}"""
            if tools:
                content += f"\nRequired tools: {tools}"
            if skill.get("prompt_template"):
                content += f"""

=== SKILL INSTRUCTIONS (follow these precisely) ===
{skill['prompt_template']}
=== END SKILL INSTRUCTIONS ==="""
            content += "\n</mandatory-skill>"
        else:
            content = f"""<skill-recommendation>
RECOMMENDED SKILL: {name}
Description: {description}
Use these tools in order: {tools}"""
            if skill.get("prompt_template"):
                content += f"\nGuidance: {skill['prompt_template']}"
            content += "\n</skill-recommendation>"

        return content

    async def _load_mode_reminder(self, mode: PromptMode) -> Optional[str]:
        """
        Load the mode-specific reminder.

        Args:
            mode: The current agent mode.

        Returns:
            Mode reminder content or None.
        """
        if mode == PromptMode.PLAN:
            return await self._load_file("reminders/plan_mode.txt")
        if mode == PromptMode.BUILD:
            return await self._load_file("reminders/build_mode.txt")
        return None

    async def _load_custom_rules(self) -> str:
        """
        Load custom rules from sandbox workspace files.

        Security: Only loads rules from sandbox workspace (/workspace),
        never from host filesystem to prevent information leakage.

        Search order (first found wins):
        1. Sandbox workspace .memstack/AGENTS.md
        2. Sandbox workspace CLAUDE.md

        Reference: OpenCode system.ts:94-155

        Returns:
            Custom rules content with source attribution.
        """
        rules: List[str] = []

        # Only search sandbox workspace - never expose host filesystem
        sandbox_workspace = self.DEFAULT_SANDBOX_WORKSPACE
        if sandbox_workspace.exists():
            for filename in self.RULE_FILE_NAMES:
                file_path = sandbox_workspace / filename
                if file_path.exists():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        rules.append(f"# Instructions from: {file_path}\n\n{content}")
                        break  # Only load first found
                    except Exception as e:
                        logger.warning(f"Failed to load custom rules from {file_path}: {e}")

        # Note: Global config from host (~/.config/memstack) is intentionally NOT loaded
        # to prevent host filesystem information leakage to sandbox agent

        return "\n\n".join(rules)

    async def _load_file(self, relative_path: str) -> str:
        """
        Load a prompt file with caching.

        Args:
            relative_path: Path relative to prompts_dir.

        Returns:
            File content or empty string if not found.
        """
        cache_key = relative_path

        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]

        file_path = self.prompts_dir / relative_path

        if not file_path.exists():
            logger.debug(f"Prompt file not found: {file_path}")
            return ""

        try:
            content = file_path.read_text(encoding="utf-8").strip()
            self._cache[cache_key] = content
            return content
        except Exception as e:
            logger.error(f"Failed to load prompt file {file_path}: {e}")
            return ""

    def clear_cache(self) -> None:
        """Clear the prompt file cache."""
        self._cache.clear()

    @staticmethod
    def detect_model_provider(model_name: str) -> ModelProvider:
        """
        Detect the model provider from a model name.

        Args:
            model_name: The model name string (e.g., "claude-3-opus", "gemini-pro").

        Returns:
            The detected ModelProvider enum value.
        """
        model_lower = model_name.lower()

        if "claude" in model_lower or "anthropic" in model_lower:
            return ModelProvider.ANTHROPIC
        elif "gemini" in model_lower:
            return ModelProvider.GEMINI
        elif "qwen" in model_lower:
            return ModelProvider.QWEN
        elif "deepseek" in model_lower:
            return ModelProvider.DEEPSEEK
        elif "glm" in model_lower or "zhipu" in model_lower:
            return ModelProvider.ZHIPU
        elif "gpt" in model_lower or "openai" in model_lower:
            return ModelProvider.OPENAI
        else:
            return ModelProvider.DEFAULT
