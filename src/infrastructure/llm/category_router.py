"""Category-based model routing for LLM task dispatch.

Routes tasks by semantic category (code, writing, analysis, etc.) to the
optimal model for that category, replacing hardcoded model names with
intent-driven selection.

Inspired by oh-my-opencode's category routing pattern.

Usage::

    router = CategoryRouter(
        provider_configs={"dashscope": ["qwen-max", "qwen-plus", "qwen-turbo"]},
    )
    category = router.detect_category("Write a Python function to sort a list")
    config = router.route(category)
    # config.preferred_models -> ["deepseek-chat", "qwen-plus", ...]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TaskCategory(str, Enum):
    """Semantic categories for LLM task routing.

    Each category maps to a class of tasks with distinct model affinity.
    Models that excel at code generation may underperform at creative
    writing and vice versa.
    """

    CODE = "code"
    ANALYSIS = "analysis"
    WRITING = "writing"
    CONVERSATION = "conversation"
    PLANNING = "planning"
    TOOL_USE = "tool_use"
    VISION = "vision"
    EMBEDDING = "embedding"
    DEFAULT = "default"


@dataclass(kw_only=True)
class CategoryModelConfig:
    """Model selection configuration for a single task category.

    Attributes:
        category: The semantic task category this config targets.
        preferred_models: Ordered list of preferred model names (bare,
            without provider prefix). The router tries these first.
        fallback_model: Optional fallback when none of the preferred
            models are available in the current provider set.
        max_tokens_override: Category-specific max output token limit.
            ``None`` means use the model default.
        temperature_override: Category-specific temperature. ``None``
            means use the caller default.
    """

    category: TaskCategory
    preferred_models: list[str] = field(default_factory=list)
    fallback_model: str | None = None
    max_tokens_override: int | None = None
    temperature_override: float | None = None


# ---------------------------------------------------------------------------
# Keyword tables for heuristic category detection
# ---------------------------------------------------------------------------

_CODE_KEYWORDS: frozenset[str] = frozenset(
    {
        "code",
        "function",
        "class",
        "debug",
        "refactor",
        "implement",
        "programming",
        "algorithm",
        "syntax",
        "compile",
        "runtime",
        "bug",
        "test",
        "unittest",
        "pytest",
        "api",
        "endpoint",
        "database",
        "sql",
        "query",
        "script",
        "variable",
        "loop",
        "recursion",
        "typescript",
        "python",
        "javascript",
        "rust",
        "java",
        "golang",
        "cpp",
        "html",
        "css",
        "regex",
        "git",
        "commit",
        "merge",
        "docker",
        "deploy",
    },
)

_ANALYSIS_KEYWORDS: frozenset[str] = frozenset(
    {
        "analyze",
        "analysis",
        "reason",
        "reasoning",
        "math",
        "calculate",
        "statistics",
        "data",
        "evaluate",
        "compare",
        "benchmark",
        "metric",
        "correlation",
        "hypothesis",
        "probability",
        "logic",
        "proof",
        "theorem",
        "equation",
        "formula",
    },
)

_WRITING_KEYWORDS: frozenset[str] = frozenset(
    {
        "write",
        "essay",
        "article",
        "blog",
        "document",
        "documentation",
        "summarize",
        "summary",
        "paraphrase",
        "rewrite",
        "proofread",
        "grammar",
        "creative",
        "story",
        "poem",
        "novel",
        "narrative",
        "draft",
        "copywriting",
        "content",
    },
)

_PLANNING_KEYWORDS: frozenset[str] = frozenset(
    {
        "plan",
        "planning",
        "roadmap",
        "decompose",
        "breakdown",
        "strategy",
        "architecture",
        "design",
        "milestone",
        "schedule",
        "prioritize",
        "organize",
        "workflow",
        "project",
        "sprint",
        "backlog",
    },
)

_VISION_KEYWORDS: frozenset[str] = frozenset(
    {
        "image",
        "picture",
        "photo",
        "screenshot",
        "diagram",
        "chart",
        "visual",
        "look at",
        "see",
        "ocr",
        "multimodal",
        "vision",
    },
)

_WORD_RE = re.compile(r"[a-z]+")


# ---------------------------------------------------------------------------
# Default category -> model mappings
# ---------------------------------------------------------------------------


def build_default_mappings() -> dict[TaskCategory, CategoryModelConfig]:
    """Return sensible default model preferences per category."""
    return {
        TaskCategory.CODE: CategoryModelConfig(
            category=TaskCategory.CODE,
            preferred_models=["deepseek-chat", "qwen-plus", "gpt-4o-mini"],
            fallback_model="qwen-turbo",
            temperature_override=0.0,
        ),
        TaskCategory.ANALYSIS: CategoryModelConfig(
            category=TaskCategory.ANALYSIS,
            preferred_models=["qwen-max", "gpt-4o", "deepseek-chat"],
            fallback_model="qwen-plus",
            temperature_override=0.2,
        ),
        TaskCategory.WRITING: CategoryModelConfig(
            category=TaskCategory.WRITING,
            preferred_models=["qwen-plus", "gpt-4o-mini", "claude-3-5-sonnet-20241022"],
            fallback_model="qwen-turbo",
            temperature_override=0.7,
        ),
        TaskCategory.CONVERSATION: CategoryModelConfig(
            category=TaskCategory.CONVERSATION,
            preferred_models=["qwen-turbo", "gpt-4o-mini", "gemini-2.0-flash"],
            fallback_model="qwen-plus",
            temperature_override=0.5,
        ),
        TaskCategory.PLANNING: CategoryModelConfig(
            category=TaskCategory.PLANNING,
            preferred_models=["qwen-max", "gpt-4o", "deepseek-chat"],
            fallback_model="qwen-plus",
            temperature_override=0.3,
        ),
        TaskCategory.TOOL_USE: CategoryModelConfig(
            category=TaskCategory.TOOL_USE,
            preferred_models=["gemini-2.0-flash", "qwen-plus", "gpt-4o-mini"],
            fallback_model="qwen-turbo",
            temperature_override=0.0,
        ),
        TaskCategory.VISION: CategoryModelConfig(
            category=TaskCategory.VISION,
            preferred_models=["qwen-vl-max", "gpt-4o", "gemini-1.5-pro"],
            fallback_model="qwen-vl-plus",
        ),
        TaskCategory.EMBEDDING: CategoryModelConfig(
            category=TaskCategory.EMBEDDING,
            preferred_models=["text-embedding-v3", "text-embedding-3-small"],
            fallback_model="text-embedding-v3",
        ),
        TaskCategory.DEFAULT: CategoryModelConfig(
            category=TaskCategory.DEFAULT,
            preferred_models=["qwen-plus", "gpt-4o-mini", "deepseek-chat"],
            fallback_model="qwen-turbo",
        ),
    }


def _strip_provider_prefix(model: str) -> str:
    """Strip provider prefix (e.g. 'dashscope/qwen-max' -> 'qwen-max')."""
    return model.split("/", 1)[-1] if "/" in model else model


class CategoryRouter:
    """Select the best model for a given task category.

    The router maintains a mapping of ``TaskCategory`` to
    ``CategoryModelConfig``.  When ``route()`` is called it filters the
    preferred model list by what is actually available (based on the
    ``provider_configs`` supplied at construction time) and returns the
    winning config.

    Args:
        provider_configs: Maps provider name to its list of available
            model names (bare, without prefix).
        custom_mappings: Optional overrides for the built-in default
            category -> model mappings.
    """

    def __init__(
        self,
        provider_configs: dict[str, list[str]],
        custom_mappings: dict[TaskCategory, CategoryModelConfig] | None = None,
        *,
        default_mappings: dict[TaskCategory, CategoryModelConfig] | None = None,
    ) -> None:
        super().__init__()
        self._provider_configs = provider_configs
        self._available_models = self._collect_available_models(provider_configs)
        self._mappings = (
            dict(default_mappings) if default_mappings is not None else build_default_mappings()
        )
        if custom_mappings:
            self._mappings.update(custom_mappings)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        category: TaskCategory,
        available_providers: list[str] | None = None,
    ) -> CategoryModelConfig:
        """Return the best ``CategoryModelConfig`` for *category*.

        If *available_providers* is given, only models belonging to those
        providers are considered.  Otherwise every model known to the
        router is eligible.

        When no preferred model survives the filter the fallback model is
        attempted.  If even the fallback is unavailable the config is
        returned as-is (caller is responsible for final resolution).
        """
        base_config = self._mappings.get(
            category,
            self._mappings[TaskCategory.DEFAULT],
        )

        pool = self._resolve_available_pool(available_providers)

        filtered = [m for m in base_config.preferred_models if m in pool]

        if filtered:
            return CategoryModelConfig(
                category=base_config.category,
                preferred_models=filtered,
                fallback_model=base_config.fallback_model,
                max_tokens_override=base_config.max_tokens_override,
                temperature_override=base_config.temperature_override,
            )

        # Try fallback
        if base_config.fallback_model and base_config.fallback_model in pool:
            logger.info(
                "No preferred model available for %s; using fallback %s",
                category.value,
                base_config.fallback_model,
            )
            return CategoryModelConfig(
                category=base_config.category,
                preferred_models=[base_config.fallback_model],
                fallback_model=None,
                max_tokens_override=base_config.max_tokens_override,
                temperature_override=base_config.temperature_override,
            )

        # Nothing matched -- return original config unchanged
        logger.warning(
            "No available model matched for category %s; returning unfiltered config",
            category.value,
        )
        return base_config

    def detect_category(
        self,
        query: str,
        tools_requested: bool = False,
    ) -> TaskCategory:
        """Heuristically detect the task category from *query* text.

        Uses simple keyword matching with weighted scoring.  When
        *tools_requested* is ``True`` the result is biased toward
        ``TOOL_USE`` unless another category scores significantly
        higher.
        """
        if not query or not query.strip():
            return TaskCategory.TOOL_USE if tools_requested else TaskCategory.DEFAULT

        words = set(_WORD_RE.findall(query.lower()))

        scores: dict[TaskCategory, int] = {
            TaskCategory.CODE: len(words & _CODE_KEYWORDS),
            TaskCategory.ANALYSIS: len(words & _ANALYSIS_KEYWORDS),
            TaskCategory.WRITING: len(words & _WRITING_KEYWORDS),
            TaskCategory.PLANNING: len(words & _PLANNING_KEYWORDS),
            TaskCategory.VISION: len(words & _VISION_KEYWORDS),
        }

        best_category = max(scores, key=lambda c: scores[c])
        best_score = scores[best_category]

        if tools_requested:
            # TOOL_USE wins unless another category has >= 2 keyword hits
            if best_score < 2:
                return TaskCategory.TOOL_USE

        if best_score == 0:
            return TaskCategory.TOOL_USE if tools_requested else TaskCategory.CONVERSATION

        return best_category

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def available_models(self) -> frozenset[str]:
        """All bare model names known to the router."""
        return self._available_models

    @property
    def mappings(self) -> dict[TaskCategory, CategoryModelConfig]:
        """Current category -> config mappings (read-only copy)."""
        return dict(self._mappings)

    # ------------------------------------------------------------------
    # Catalog-aware selection
    # ------------------------------------------------------------------

    def select_model_from_catalog(
        self,
        category: TaskCategory,
        available_providers: list[str] | None = None,
    ) -> str | None:
        """Select a model using the catalog for richer metadata.

        Attempts to find the best available model for *category* by
        consulting the ``ModelCatalogService``.  Returns the bare model
        name, or ``None`` when the catalog is unavailable or no model
        matched.

        Falls back to :meth:`route` when the catalog cannot help.
        """
        try:
            from src.infrastructure.llm.model_catalog import (
                get_model_catalog_service,
            )

            catalog = get_model_catalog_service()
        except Exception:
            return None

        config = self.route(category, available_providers)
        pool = self._resolve_available_pool(available_providers)

        # Check preferred models against catalog
        for model_name in config.preferred_models:
            meta = catalog.get_model(model_name)
            if meta is None:
                continue
            if meta.is_deprecated:
                continue
            if model_name in pool:
                return model_name

        # Try fallback
        if config.fallback_model:
            meta = catalog.get_model(config.fallback_model)
            if meta and not meta.is_deprecated:
                if config.fallback_model in pool:
                    return config.fallback_model

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_available_models(
        provider_configs: dict[str, list[str]],
    ) -> frozenset[str]:
        """Flatten provider model lists into a single set of bare names."""
        models: set[str] = set()
        for model_list in provider_configs.values():
            for model in model_list:
                models.add(_strip_provider_prefix(model))
        return frozenset(models)

    def _resolve_available_pool(
        self,
        available_providers: list[str] | None,
    ) -> frozenset[str]:
        """Resolve the set of models to consider for routing."""
        if available_providers is None:
            return self._available_models

        pool: set[str] = set()
        for provider in available_providers:
            for model in self._provider_configs.get(provider, []):
                pool.add(_strip_provider_prefix(model))
        return frozenset(pool)
