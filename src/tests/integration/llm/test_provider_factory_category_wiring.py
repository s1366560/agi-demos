"""Integration tests for AIServiceFactory.create_llm_client_for_category.

Verifies the wiring between CategoryRouter and create_litellm_client
inside the category-based model routing path.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.llm.provider_factory import AIServiceFactory


@pytest.mark.integration
class TestCategoryRouterWiring:
    """Verify create_llm_client_for_category routes correctly."""

    @patch(
        "src.infrastructure.llm.litellm.litellm_client.create_litellm_client",
    )
    @patch(
        "src.infrastructure.llm.model_catalog.get_model_catalog_service",
    )
    @patch(
        "src.infrastructure.llm.category_router.CategoryRouter",
    )
    def test_category_router_overrides_model(
        self,
        mock_router_cls: MagicMock,
        mock_catalog: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """When route() returns preferred_models, the first
        model overrides the original ProviderConfig.model."""
        # Arrange
        detected_category = MagicMock(name="detected_category")
        routed = MagicMock()
        routed.preferred_models = ["better-model"]
        routed.category.value = "code"
        routed.confidence = 0.95

        mock_router_cls.return_value.detect_category.return_value = detected_category
        mock_router_cls.return_value.route.return_value = routed

        original_cfg = MagicMock()
        original_cfg.provider_type.value = "openai"
        original_cfg.llm_model = "gpt-4"
        original_cfg.llm_small_model = "gpt-4o-mini"
        original_cfg.embedding_model = "text-embedding-3"
        original_cfg.reranker_model = "rerank-v1"

        overridden_cfg = MagicMock(name="overridden_cfg")
        original_cfg.model_copy.return_value = overridden_cfg

        mock_create.return_value = MagicMock(name="client")

        # Act
        result = AIServiceFactory.create_llm_client_for_category(
            provider_config=original_cfg,
            task_description="Write Python code",
        )

        # Assert -- router was called
        mock_router_cls.assert_called_once_with(
            provider_configs={"openai": ["gpt-4", "gpt-4o-mini"]},
        )
        mock_router_cls.return_value.detect_category.assert_called_once_with(
            "Write Python code",
        )
        mock_router_cls.return_value.route.assert_called_once_with(
            category=detected_category,
        )
        # Assert -- ProviderConfig is copied with overridden model
        original_cfg.model_copy.assert_called_once_with(update={"llm_model": "better-model"})
        # Assert -- create_litellm_client receives overridden cfg and catalog
        mock_create.assert_called_once_with(
            overridden_cfg,
            cache=None,
            catalog=mock_catalog.return_value,
        )
        assert result is mock_create.return_value

    @patch(
        "src.infrastructure.llm.litellm.litellm_client.create_litellm_client",
    )
    @patch(
        "src.infrastructure.llm.model_catalog.get_model_catalog_service",
    )
    @patch(
        "src.infrastructure.llm.category_router.CategoryRouter",
    )
    def test_category_router_no_override_when_empty(
        self,
        mock_router_cls: MagicMock,
        mock_catalog: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """When preferred_models is empty, original config
        is forwarded unchanged."""
        # Arrange
        detected_category = MagicMock(name="detected_category")
        routed = MagicMock()
        routed.preferred_models = []

        mock_router_cls.return_value.detect_category.return_value = detected_category
        mock_router_cls.return_value.route.return_value = routed

        original_cfg = MagicMock()
        original_cfg.provider_type.value = "openai"
        original_cfg.llm_model = "original-model"
        original_cfg.llm_small_model = None
        mock_create.return_value = MagicMock(name="client")

        # Act
        result = AIServiceFactory.create_llm_client_for_category(
            provider_config=original_cfg,
            task_description="Hello world",
        )

        # Assert -- original config passed through as-is
        mock_router_cls.return_value.detect_category.assert_called_once_with(
            "Hello world",
        )
        mock_router_cls.return_value.route.assert_called_once_with(
            category=detected_category,
        )
        original_cfg.model_copy.assert_not_called()
        mock_create.assert_called_once_with(
            original_cfg,
            cache=None,
            catalog=mock_catalog.return_value,
        )
        assert result is mock_create.return_value

    @patch(
        "src.infrastructure.llm.litellm.litellm_client.create_litellm_client",
    )
    @patch(
        "src.infrastructure.llm.model_catalog.get_model_catalog_service",
    )
    @patch(
        "src.infrastructure.llm.category_router.CategoryRouter",
    )
    def test_category_router_preserves_other_config_fields(
        self,
        mock_router_cls: MagicMock,
        mock_catalog: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """When model is overridden, api_key / base_url /
        embedding_model / rerank_model stay unchanged."""
        # Arrange
        detected_category = MagicMock(name="detected_category")
        routed = MagicMock()
        routed.preferred_models = ["new-model"]
        routed.category.value = "analysis"
        routed.confidence = 0.8

        mock_router_cls.return_value.detect_category.return_value = detected_category
        mock_router_cls.return_value.route.return_value = routed

        original_cfg = MagicMock()
        original_cfg.provider_type.value = "gemini"
        original_cfg.llm_model = "old-model"
        original_cfg.llm_small_model = "small-model"
        original_cfg.embedding_model = "embed-v2"
        original_cfg.reranker_model = "rerank-v2"

        rebuilt_cfg = MagicMock(name="rebuilt_cfg")
        original_cfg.model_copy.return_value = rebuilt_cfg

        mock_create.return_value = MagicMock(name="client")

        # Act
        AIServiceFactory.create_llm_client_for_category(
            provider_config=original_cfg,
            task_description="Analyze data",
            cache=True,
        )

        # Assert -- model is the only requested field update
        original_cfg.model_copy.assert_called_once_with(update={"llm_model": "new-model"})

        # cache kwarg forwarded
        mock_create.assert_called_once_with(
            rebuilt_cfg,
            cache=True,
            catalog=mock_catalog.return_value,
        )
