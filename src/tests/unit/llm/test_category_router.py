"""Unit tests for category-based model routing."""

from __future__ import annotations

import pytest

from src.infrastructure.llm.category_router import (
    CategoryModelConfig,
    CategoryRouter,
    TaskCategory,
    build_default_mappings,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_DASHSCOPE_MODELS = [
    "qwen-max",
    "qwen-plus",
    "qwen-turbo",
    "qwen-vl-max",
    "qwen-vl-plus",
]

_OPENAI_MODELS = ["gpt-4o", "gpt-4o-mini"]

_DEEPSEEK_MODELS = ["deepseek-chat"]

_GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-pro"]


@pytest.fixture()
def full_provider_configs() -> dict[str, list[str]]:
    """Provider configs with models from all major providers."""
    return {
        "dashscope": _DASHSCOPE_MODELS,
        "openai": _OPENAI_MODELS,
        "deepseek": _DEEPSEEK_MODELS,
        "gemini": _GEMINI_MODELS,
    }


@pytest.fixture()
def dashscope_only_configs() -> dict[str, list[str]]:
    """Provider configs limited to Dashscope only."""
    return {"dashscope": _DASHSCOPE_MODELS}


@pytest.fixture()
def router(full_provider_configs: dict[str, list[str]]) -> CategoryRouter:
    """CategoryRouter with all providers available."""
    return CategoryRouter(provider_configs=full_provider_configs)


@pytest.fixture()
def dashscope_router(dashscope_only_configs: dict[str, list[str]]) -> CategoryRouter:
    """CategoryRouter with only Dashscope models."""
    return CategoryRouter(provider_configs=dashscope_only_configs)


# ===================================================================
# TaskCategory enum
# ===================================================================


@pytest.mark.unit
class TestTaskCategory:
    """Verify TaskCategory enum values and membership."""

    def test_all_expected_categories_exist(self) -> None:
        """All required categories are present in the enum."""
        expected = {
            "code",
            "analysis",
            "writing",
            "conversation",
            "planning",
            "tool_use",
            "vision",
            "embedding",
            "default",
        }
        actual = {c.value for c in TaskCategory}
        assert actual == expected

    def test_category_is_string_enum(self) -> None:
        """TaskCategory values are strings (str, Enum)."""
        assert isinstance(TaskCategory.CODE, str)
        assert TaskCategory.CODE == "code"


# ===================================================================
# CategoryModelConfig dataclass
# ===================================================================


@pytest.mark.unit
class TestCategoryModelConfig:
    """Verify CategoryModelConfig construction and defaults."""

    def test_minimal_construction(self) -> None:
        """Config can be built with only category."""
        config = CategoryModelConfig(category=TaskCategory.DEFAULT)
        assert config.category == TaskCategory.DEFAULT
        assert config.preferred_models == []
        assert config.fallback_model is None
        assert config.max_tokens_override is None
        assert config.temperature_override is None

    def test_full_construction(self) -> None:
        """Config respects all explicit keyword arguments."""
        config = CategoryModelConfig(
            category=TaskCategory.CODE,
            preferred_models=["deepseek-chat", "qwen-plus"],
            fallback_model="qwen-turbo",
            max_tokens_override=4096,
            temperature_override=0.0,
        )
        assert config.preferred_models == ["deepseek-chat", "qwen-plus"]
        assert config.fallback_model == "qwen-turbo"
        assert config.max_tokens_override == 4096
        assert config.temperature_override == 0.0


# ===================================================================
# Default mappings
# ===================================================================


@pytest.mark.unit
class TestDefaultMappings:
    """Verify the built-in default category -> model mappings."""

    def test_all_categories_have_defaults(self) -> None:
        """Every TaskCategory has a default mapping."""
        defaults = build_default_mappings()
        for cat in TaskCategory:
            assert cat in defaults, f"Missing default mapping for {cat}"

    def test_code_defaults_prefer_deepseek(self) -> None:
        """CODE category defaults to deepseek-chat first."""
        defaults = build_default_mappings()
        code_config = defaults[TaskCategory.CODE]
        assert code_config.preferred_models[0] == "deepseek-chat"
        assert code_config.temperature_override == 0.0

    def test_analysis_defaults_prefer_reasoning_models(self) -> None:
        """ANALYSIS defaults to strong reasoning models."""
        defaults = build_default_mappings()
        analysis_config = defaults[TaskCategory.ANALYSIS]
        assert "qwen-max" in analysis_config.preferred_models
        assert analysis_config.temperature_override == 0.2

    def test_writing_has_higher_temperature(self) -> None:
        """WRITING category has a higher temperature for creativity."""
        defaults = build_default_mappings()
        writing_config = defaults[TaskCategory.WRITING]
        assert writing_config.temperature_override is not None
        assert writing_config.temperature_override >= 0.5

    def test_vision_includes_multimodal_models(self) -> None:
        """VISION category prefers multimodal-capable models."""
        defaults = build_default_mappings()
        vision_config = defaults[TaskCategory.VISION]
        assert "qwen-vl-max" in vision_config.preferred_models


# ===================================================================
# CategoryRouter.route()
# ===================================================================


@pytest.mark.unit
class TestCategoryRouterRoute:
    """Test route() model selection logic."""

    def test_route_code_with_all_providers(
        self,
        router: CategoryRouter,
    ) -> None:
        """CODE route returns filtered preferred models."""
        config = router.route(TaskCategory.CODE)
        assert config.category == TaskCategory.CODE
        # deepseek-chat and qwen-plus should both survive filtering
        assert "deepseek-chat" in config.preferred_models
        assert "qwen-plus" in config.preferred_models

    def test_route_filters_by_available_providers(
        self,
        router: CategoryRouter,
    ) -> None:
        """Route limits models to specified available providers."""
        config = router.route(
            TaskCategory.CODE,
            available_providers=["dashscope"],
        )
        # deepseek-chat is NOT in dashscope
        assert "deepseek-chat" not in config.preferred_models
        # qwen-plus IS in dashscope
        assert "qwen-plus" in config.preferred_models

    def test_route_fallback_when_no_preferred_available(
        self,
        full_provider_configs: dict[str, list[str]],
    ) -> None:
        """When no preferred model is available, use fallback."""
        # Create a router with a custom mapping whose preferred models
        # are not in any provider
        custom = {
            TaskCategory.CODE: CategoryModelConfig(
                category=TaskCategory.CODE,
                preferred_models=["nonexistent-model-a", "nonexistent-model-b"],
                fallback_model="qwen-turbo",
            ),
        }
        router = CategoryRouter(
            provider_configs=full_provider_configs,
            custom_mappings=custom,
        )
        config = router.route(TaskCategory.CODE)
        # Fallback should be used
        assert config.preferred_models == ["qwen-turbo"]
        assert config.fallback_model is None

    def test_route_returns_unfiltered_when_nothing_matches(
        self,
    ) -> None:
        """When neither preferred nor fallback is available, return unfiltered."""
        empty_providers: dict[str, list[str]] = {"empty_provider": []}
        custom = {
            TaskCategory.CODE: CategoryModelConfig(
                category=TaskCategory.CODE,
                preferred_models=["nonexistent-a"],
                fallback_model="nonexistent-b",
            ),
        }
        router = CategoryRouter(
            provider_configs=empty_providers,
            custom_mappings=custom,
        )
        config = router.route(TaskCategory.CODE)
        # Returns original unfiltered config
        assert config.preferred_models == ["nonexistent-a"]
        assert config.fallback_model == "nonexistent-b"

    def test_route_unknown_category_falls_back_to_default(
        self,
        full_provider_configs: dict[str, list[str]],
    ) -> None:
        """An unmapped category falls back to DEFAULT mapping."""
        # Build default mappings that exclude EMBEDDING
        defaults = build_default_mappings()
        del defaults[TaskCategory.EMBEDDING]
        router = CategoryRouter(
            provider_configs=full_provider_configs,
            default_mappings=defaults,
        )
        config = router.route(TaskCategory.EMBEDDING)
        # Should get DEFAULT config
        assert config.category == TaskCategory.DEFAULT

    def test_route_preserves_overrides(
        self,
        router: CategoryRouter,
    ) -> None:
        """Route preserves max_tokens_override and temperature_override."""
        config = router.route(TaskCategory.CODE)
        assert config.temperature_override == 0.0

    def test_route_dashscope_only_conversation(
        self,
        dashscope_router: CategoryRouter,
    ) -> None:
        """CONVERSATION route with only Dashscope selects qwen-turbo."""
        config = dashscope_router.route(TaskCategory.CONVERSATION)
        assert "qwen-turbo" in config.preferred_models

    def test_route_vision_with_dashscope_only(
        self,
        dashscope_router: CategoryRouter,
    ) -> None:
        """VISION route with Dashscope includes qwen-vl-max."""
        config = dashscope_router.route(TaskCategory.VISION)
        assert "qwen-vl-max" in config.preferred_models


# ===================================================================
# CategoryRouter.detect_category()
# ===================================================================


@pytest.mark.unit
class TestDetectCategory:
    """Test safe default category detection without local text heuristics."""

    @pytest.mark.parametrize(
        "query",
        [
            "Write a Python function to sort a list using recursion",
            "Analyze the correlation between these data statistics",
            "Write an essay summarizing the article about climate",
            "Create a project roadmap with milestones and schedule",
            "Look at this screenshot and describe the diagram",
            "Hello, how are you today?",
        ],
    )
    def test_detect_nonempty_query_returns_conversation(
        self,
        router: CategoryRouter,
        query: str,
    ) -> None:
        """Natural-language category judgment is broker-owned."""
        assert router.detect_category(query) == TaskCategory.CONVERSATION

    def test_detect_empty_query_returns_default(
        self,
        router: CategoryRouter,
    ) -> None:
        """Empty or whitespace-only query returns DEFAULT."""
        assert router.detect_category("") == TaskCategory.DEFAULT
        assert router.detect_category("   ") == TaskCategory.DEFAULT

    def test_detect_tools_requested_bias(self, router: CategoryRouter) -> None:
        """With tools_requested=True, low-scoring query -> TOOL_USE."""
        query = "Hello, how are you?"
        result = router.detect_category(query, tools_requested=True)
        assert result == TaskCategory.TOOL_USE

    def test_detect_tools_requested_strong_category_wins(
        self,
        router: CategoryRouter,
    ) -> None:
        """tools_requested is the only structural bias in this sync fallback."""
        query = "Write a Python function to debug and refactor this code"
        result = router.detect_category(query, tools_requested=True)
        assert result == TaskCategory.TOOL_USE

    def test_detect_empty_with_tools_returns_tool_use(
        self,
        router: CategoryRouter,
    ) -> None:
        """Empty query with tools_requested returns TOOL_USE."""
        assert router.detect_category("", tools_requested=True) == TaskCategory.TOOL_USE


# ===================================================================
# Custom mapping overrides
# ===================================================================


@pytest.mark.unit
class TestCustomMappings:
    """Test that custom_mappings override defaults."""

    def test_custom_mapping_overrides_default(
        self,
        full_provider_configs: dict[str, list[str]],
    ) -> None:
        """A custom mapping replaces the default for that category."""
        custom_code = CategoryModelConfig(
            category=TaskCategory.CODE,
            preferred_models=["gpt-4o"],
            fallback_model="gpt-4o-mini",
            temperature_override=0.1,
        )
        router = CategoryRouter(
            provider_configs=full_provider_configs,
            custom_mappings={TaskCategory.CODE: custom_code},
        )
        config = router.route(TaskCategory.CODE)
        assert "gpt-4o" in config.preferred_models
        assert config.temperature_override == 0.1

    def test_custom_mapping_does_not_affect_others(
        self,
        full_provider_configs: dict[str, list[str]],
    ) -> None:
        """Overriding CODE does not change ANALYSIS."""
        custom_code = CategoryModelConfig(
            category=TaskCategory.CODE,
            preferred_models=["gpt-4o"],
        )
        router = CategoryRouter(
            provider_configs=full_provider_configs,
            custom_mappings={TaskCategory.CODE: custom_code},
        )
        analysis_config = router.route(TaskCategory.ANALYSIS)
        # ANALYSIS should still have its default models
        assert "qwen-max" in analysis_config.preferred_models

    def test_custom_mapping_new_category_behavior(
        self,
        full_provider_configs: dict[str, list[str]],
    ) -> None:
        """Custom mapping can override DEFAULT fallback."""
        custom_default = CategoryModelConfig(
            category=TaskCategory.DEFAULT,
            preferred_models=["gpt-4o"],
            fallback_model="gpt-4o-mini",
            max_tokens_override=2048,
        )
        router = CategoryRouter(
            provider_configs=full_provider_configs,
            custom_mappings={TaskCategory.DEFAULT: custom_default},
        )
        config = router.route(TaskCategory.DEFAULT)
        assert config.preferred_models == ["gpt-4o"]
        assert config.max_tokens_override == 2048


# ===================================================================
# Router properties
# ===================================================================


@pytest.mark.unit
class TestRouterProperties:
    """Test read-only properties of CategoryRouter."""

    def test_available_models_is_frozenset(
        self,
        router: CategoryRouter,
    ) -> None:
        """available_models returns a frozenset."""
        assert isinstance(router.available_models, frozenset)

    def test_available_models_contains_all_providers(
        self,
        router: CategoryRouter,
    ) -> None:
        """available_models includes models from every provider."""
        models = router.available_models
        assert "qwen-max" in models
        assert "gpt-4o" in models
        assert "deepseek-chat" in models
        assert "gemini-2.0-flash" in models

    def test_available_models_strips_provider_prefix(self) -> None:
        """Models with provider/ prefix are stored bare."""
        configs = {"dashscope": ["dashscope/qwen-max"]}
        router = CategoryRouter(provider_configs=configs)
        assert "qwen-max" in router.available_models
        assert "dashscope/qwen-max" not in router.available_models

    def test_mappings_returns_copy(self, router: CategoryRouter) -> None:
        """mappings property returns a new dict each time."""
        m1 = router.mappings
        m2 = router.mappings
        assert m1 is not m2
        assert m1 == m2
