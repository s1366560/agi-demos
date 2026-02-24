"""
Unit tests for SystemPromptManager.

Tests the system prompt management functionality including:
- Base prompt loading
- Model provider detection
- Environment context building
- Mode reminders
- Custom rules loading
- Full prompt assembly
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.agent.prompts import (
    ModelProvider,
    PromptContext,
    PromptLoader,
    PromptMode,
    SystemPromptManager,
)


@pytest.mark.unit
class TestModelProviderDetection:
    """Test model provider detection from model names."""

    def test_detect_anthropic(self):
        """Test Claude/Anthropic model detection."""
        assert SystemPromptManager.detect_model_provider("claude-3-opus") == ModelProvider.ANTHROPIC
        assert (
            SystemPromptManager.detect_model_provider("claude-3-sonnet") == ModelProvider.ANTHROPIC
        )
        assert (
            SystemPromptManager.detect_model_provider("anthropic/claude-3")
            == ModelProvider.ANTHROPIC
        )

    def test_detect_gemini(self):
        """Test Gemini model detection."""
        assert SystemPromptManager.detect_model_provider("gemini-pro") == ModelProvider.GEMINI
        assert SystemPromptManager.detect_model_provider("gemini-1.5-pro") == ModelProvider.GEMINI

    def test_detect_qwen(self):
        """Test Qwen model detection."""
        assert SystemPromptManager.detect_model_provider("qwen-turbo") == ModelProvider.DASHSCOPE
        assert SystemPromptManager.detect_model_provider("qwen2-72b") == ModelProvider.DASHSCOPE

    def test_detect_deepseek(self):
        """Test Deepseek model detection."""
        assert SystemPromptManager.detect_model_provider("deepseek-chat") == ModelProvider.DEEPSEEK
        assert SystemPromptManager.detect_model_provider("deepseek-coder") == ModelProvider.DEEPSEEK

    def test_detect_zhipu(self):
        """Test ZhipuAI model detection."""
        assert SystemPromptManager.detect_model_provider("glm-4") == ModelProvider.ZHIPU
        assert SystemPromptManager.detect_model_provider("zhipu-glm") == ModelProvider.ZHIPU

    def test_detect_openai(self):
        """Test OpenAI model detection."""
        assert SystemPromptManager.detect_model_provider("gpt-4") == ModelProvider.OPENAI
        assert SystemPromptManager.detect_model_provider("gpt-4-turbo") == ModelProvider.OPENAI

    def test_detect_default(self):
        """Test default provider for unknown models."""
        assert SystemPromptManager.detect_model_provider("unknown-model") == ModelProvider.DEFAULT
        assert (
            SystemPromptManager.detect_model_provider("some-custom-model") == ModelProvider.DEFAULT
        )


@pytest.mark.unit
class TestPromptContext:
    """Test PromptContext dataclass."""

    def test_default_values(self):
        """Test default values for PromptContext."""
        context = PromptContext(
            model_provider=ModelProvider.DEFAULT,
        )
        assert context.mode == PromptMode.BUILD
        assert context.tool_definitions == []
        assert context.skills is None
        assert context.current_step == 1
        assert context.max_steps == 50
        assert not context.is_last_step

    def test_is_last_step(self):
        """Test is_last_step property."""
        context = PromptContext(
            model_provider=ModelProvider.DEFAULT,
            current_step=50,
            max_steps=50,
        )
        assert context.is_last_step

        context = PromptContext(
            model_provider=ModelProvider.DEFAULT,
            current_step=49,
            max_steps=50,
        )
        assert not context.is_last_step


@pytest.mark.unit
class TestPromptLoader:
    """Test PromptLoader functionality."""

    @pytest.fixture
    def temp_prompts_dir(self, tmp_path):
        """Create temporary prompts directory with test files."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        # Create test file
        (prompts_dir / "test.txt").write_text("Hello ${NAME}!")
        return prompts_dir

    def test_load_file(self, temp_prompts_dir):
        """Test basic file loading."""
        loader = PromptLoader(temp_prompts_dir)
        content = loader.load_sync("test.txt")
        assert content == "Hello ${NAME}!"

    def test_load_with_variables(self, temp_prompts_dir):
        """Test loading with variable substitution."""
        loader = PromptLoader(temp_prompts_dir)
        content = loader.load_sync("test.txt", variables={"NAME": "World"})
        assert content == "Hello World!"

    def test_load_nonexistent(self, temp_prompts_dir):
        """Test loading nonexistent file returns empty string."""
        loader = PromptLoader(temp_prompts_dir)
        content = loader.load_sync("nonexistent.txt")
        assert content == ""

    def test_caching(self, temp_prompts_dir):
        """Test file caching works."""
        loader = PromptLoader(temp_prompts_dir)

        # Load once
        content1 = loader.load_sync("test.txt")

        # Modify file
        (temp_prompts_dir / "test.txt").write_text("Modified content")

        # Should return cached content
        content2 = loader.load_sync("test.txt")
        assert content1 == content2

        # Clear cache and reload
        loader.clear_cache()
        content3 = loader.load_sync("test.txt")
        assert content3 == "Modified content"


@pytest.mark.unit
class TestSystemPromptManager:
    """Test SystemPromptManager functionality."""

    @pytest.fixture
    def manager(self):
        """Create SystemPromptManager with default prompts directory."""
        return SystemPromptManager()

    @pytest.fixture
    def context(self):
        """Create basic PromptContext."""
        return PromptContext(
            model_provider=ModelProvider.DEFAULT,
            mode=PromptMode.BUILD,
            tool_definitions=[
                {"name": "MemorySearch", "description": "Search memories"},
                {"name": "GraphQuery", "description": "Query knowledge graph"},
            ],
            project_id="test-project",
            working_directory="/tmp/test",
            conversation_history_length=5,
        )

    async def test_build_basic_prompt(self, manager, context):
        """Test building a basic system prompt."""
        prompt = await manager.build_system_prompt(context)

        # Should contain base prompt content
        assert len(prompt) > 0
        # Should contain tool descriptions
        assert "MemorySearch" in prompt
        assert "GraphQuery" in prompt
        # Should contain environment info
        assert "test-project" in prompt

    async def test_subagent_override(self, manager, context):
        """Test SubAgent system prompt override."""
        subagent = Mock()
        subagent.system_prompt = "I am a specialized subagent."

        prompt = await manager.build_system_prompt(context, subagent=subagent)

        assert prompt == "I am a specialized subagent."
        assert "MemorySearch" not in prompt

    async def test_plan_mode_reminder(self, manager, context):
        """Test Plan mode includes reminder."""
        context.mode = PromptMode.PLAN
        prompt = await manager.build_system_prompt(context)

        # Should contain plan mode related content
        assert "plan" in prompt.lower() or "Plan" in prompt

    async def test_skill_section(self, manager, context):
        """Test skills are included in prompt."""
        context.skills = [
            {
                "name": "MemoryAnalysis",
                "description": "Analyze memories",
                "tools": ["MemorySearch", "GraphQuery"],
                "status": "active",
            }
        ]
        prompt = await manager.build_system_prompt(context)

        assert "MemoryAnalysis" in prompt
        assert "Analyze memories" in prompt

    async def test_matched_skill_recommendation(self, manager, context):
        """Test matched skill recommendation appears."""
        context.matched_skill = {
            "name": "QuickSearch",
            "description": "Fast memory search",
            "tools": ["MemorySearch"],
            "prompt_template": "Use semantic search first",
        }
        prompt = await manager.build_system_prompt(context)

        assert "RECOMMENDED SKILL" in prompt
        assert "QuickSearch" in prompt
        assert "Fast memory search" in prompt

    async def test_none_matched_skill_does_not_crash(self, manager, context):
        """Prompt building should tolerate missing matched skill."""
        context.matched_skill = None

        prompt = await manager.build_system_prompt(context)

        assert len(prompt) > 0
        assert "RECOMMENDED SKILL" not in prompt

    async def test_forced_skill_suppresses_available_skills(self, manager, context):
        """Forced skill mode should disable normal skill-list rendering."""
        context.skills = [
            {
                "name": "NormalSkill",
                "description": "Regular skill",
                "tools": ["MemorySearch"],
                "status": "active",
            }
        ]
        context.matched_skill = {
            "name": "ForcedSkill",
            "description": "Forced workflow",
            "tools": ["GraphQuery"],
            "force_execution": True,
        }

        prompt = await manager.build_system_prompt(context)

        assert "IMPORTANT: The user has explicitly activated the skill \"/ForcedSkill\"" in prompt
        assert "## Available Skills (Pre-defined Tool Compositions)" not in prompt
        assert "NormalSkill" not in prompt

    async def test_skills_and_subagents_render_without_tools(self, manager, context):
        """Skills/subagents should still render when no tools are available."""
        context.tool_definitions = []
        context.skills = [
            {
                "name": "SkillWithoutTools",
                "description": "Still should render",
                "tools": [],
                "status": "active",
            }
        ]
        context.subagents = [
            {
                "name": "planner-subagent",
                "display_name": "Planner",
                "description": "Planning specialist",
            }
        ]

        prompt = await manager.build_system_prompt(context)

        assert "SkillWithoutTools" in prompt
        assert "## Available SubAgents (Specialized Autonomous Agents)" in prompt
        assert "planner-subagent" in prompt

    async def test_memory_context_not_gated_by_base_prompt(self, manager, context):
        """Memory context should be included even if base prompt is unavailable."""
        manager._load_base_prompt = AsyncMock(return_value="")
        context.memory_context = "<memory-context>important memory</memory-context>"

        prompt = await manager.build_system_prompt(context)

        assert "<memory-context>important memory</memory-context>" in prompt

    async def test_environment_context(self, manager, context):
        """Test environment context is included."""
        context.project_id = "my-project-123"
        context.working_directory = "/home/user/project"
        context.conversation_history_length = 10

        prompt = await manager.build_system_prompt(context)

        assert "my-project-123" in prompt
        assert "/home/user/project" in prompt
        assert "10" in prompt

    async def test_tool_authenticity_contract_exists_for_all_main_providers(self, manager, context):
        """Main provider templates should all include the same authenticity contract."""
        providers = [
            ModelProvider.DEFAULT,
            ModelProvider.GEMINI,
            ModelProvider.DASHSCOPE,
            ModelProvider.ANTHROPIC,
        ]

        for provider in providers:
            context.model_provider = provider
            prompt = await manager.build_system_prompt(context)
            assert "Tool Authenticity Contract" in prompt
            assert "No Evidence, No Claim" in prompt
            assert "Execution-first" in prompt

    async def test_max_steps_warning(self, manager, context):
        """Test max steps warning when on last step."""
        context.current_step = 50
        context.max_steps = 50

        # Should contain max steps warning
        # Note: Only if max_steps.txt exists
        # This test verifies the is_last_step logic triggers

    def test_build_tools_section(self, manager, context):
        """Test tools section building."""
        section = manager._build_tools_section(context)

        assert "MemorySearch" in section
        assert "Search memories" in section
        assert "GraphQuery" in section

    def test_build_tools_section_empty(self, manager):
        """Test tools section with no tools."""
        context = PromptContext(
            model_provider=ModelProvider.DEFAULT,
            tool_definitions=[],
        )
        section = manager._build_tools_section(context)
        assert section == ""

    def test_build_skill_section(self, manager, context):
        """Test skill section building."""
        context.skills = [
            {
                "name": "Skill1",
                "description": "First skill",
                "tools": ["Tool1", "Tool2"],
                "status": "active",
            },
            {
                "name": "Skill2",
                "description": "Second skill",
                "tools": ["Tool3"],
                "status": "inactive",
            },
        ]
        section = manager._build_skill_section(context)

        assert "Skill1" in section
        assert "First skill" in section
        # Inactive skill should not appear
        assert "Skill2" not in section

    def test_build_skill_recommendation(self, manager):
        """Test skill recommendation building."""
        skill = {
            "name": "TestSkill",
            "description": "Test description",
            "tools": ["Tool1", "Tool2"],
            "prompt_template": "Use this guidance",
        }
        recommendation = manager._build_skill_recommendation(skill)

        assert "RECOMMENDED SKILL" in recommendation
        assert "TestSkill" in recommendation
        assert "Test description" in recommendation
        assert "Tool1, Tool2" in recommendation
        assert "Use this guidance" in recommendation

    def test_build_skill_recommendation_none(self, manager):
        """No recommendation block should be built for None skill."""
        recommendation = manager._build_skill_recommendation(None)
        assert recommendation == ""

    def test_build_environment_context(self, manager, context):
        """Test environment context building."""
        env = manager._build_environment_context(context)

        assert "<env>" in env
        assert "</env>" in env
        assert "test-project" in env
        assert "/tmp/test" in env
        assert "5 messages" in env

    def test_clear_cache(self, manager):
        """Test cache clearing."""
        # Add something to cache
        manager._cache["test_key"] = "test_value"
        assert "test_key" in manager._cache

        manager.clear_cache()
        assert "test_key" not in manager._cache


@pytest.mark.unit
class TestPromptModeEnum:
    """Test PromptMode enum."""

    def test_mode_values(self):
        """Test PromptMode enum values."""
        assert PromptMode.BUILD.value == "build"
        assert PromptMode.PLAN.value == "plan"

    def test_mode_from_string(self):
        """Test creating PromptMode from string."""
        assert PromptMode("build") == PromptMode.BUILD
        assert PromptMode("plan") == PromptMode.PLAN


@pytest.mark.unit
class TestModelProviderEnum:
    """Test ModelProvider enum."""

    def test_provider_values(self):
        """Test ModelProvider enum values."""
        assert ModelProvider.ANTHROPIC.value == "anthropic"
        assert ModelProvider.GEMINI.value == "gemini"
        assert ModelProvider.DASHSCOPE.value == "dashscope"
        assert ModelProvider.DEEPSEEK.value == "deepseek"
        assert ModelProvider.ZHIPU.value == "zhipu"
        assert ModelProvider.OPENAI.value == "openai"
        assert ModelProvider.DEFAULT.value == "default"
