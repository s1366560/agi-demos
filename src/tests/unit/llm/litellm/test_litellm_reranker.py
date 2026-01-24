"""
Unit tests for LiteLLM Reranker adapter.

Tests the LiteLLMReranker implementation of Graphiti's CrossEncoderClient interface.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.litellm.litellm_reranker import LiteLLMReranker


class TestLiteLLMReranker:
    """Test suite for LiteLLMReranker."""

    @pytest.fixture
    def provider_config(self):
        """Create a test provider configuration."""
        return ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            reranker_model="gpt-4o-mini",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def reranker(self, provider_config):
        """Create a LiteLLMReranker instance."""
        with patch(
            "src.infrastructure.llm.litellm.litellm_reranker.get_encryption_service"
        ) as mock_get:
            mock_encryption = MagicMock()
            mock_encryption.decrypt.return_value = "sk-test-api-key"
            mock_get.return_value = mock_encryption
            return LiteLLMReranker(config=provider_config)

    @pytest.mark.asyncio
    async def test_rank_passages(self, reranker):
        """Test basic passage ranking."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {"content": '{"scores": [0.9, 0.7, 0.3, 0.8]}'}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            query = "What is AI?"
            passages = [
                "AI is artificial intelligence.",
                "Machine learning is a subset of AI.",
                "The sky is blue.",
                "Deep learning uses neural networks.",
            ]

            ranked = await reranker.rank(query, passages)

            # Should return 4 passages sorted by score
            assert len(ranked) == 4
            assert ranked[0][0] == "AI is artificial intelligence."  # 0.9
            assert ranked[1][0] == "Deep learning uses neural networks."  # 0.8
            assert ranked[2][0] == "Machine learning is a subset of AI."  # 0.7
            assert ranked[3][0] == "The sky is blue."  # 0.3

            # Check scores are descending
            scores = [score for _, score in ranked]
            assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_rank_single_passage(self, reranker):
        """Test ranking with single passage."""
        query = "Test query"
        passages = ["Single passage"]

        ranked = await reranker.rank(query, passages)

        assert len(ranked) == 1
        assert ranked[0][0] == "Single passage"
        assert ranked[0][1] == 1.0  # Single passage gets perfect score

    @pytest.mark.asyncio
    async def test_rank_empty_passages(self, reranker):
        """Test ranking with empty passages list."""
        query = "Test query"
        passages = []

        ranked = await reranker.rank(query, passages)

        assert ranked == []

    @pytest.mark.asyncio
    async def test_rank_handles_json_with_markdown(self, reranker):
        """Test that JSON response with markdown is handled correctly."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {"content": '```json\n{"scores": [0.8, 0.6]}\n```'}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            query = "Test query"
            passages = ["Passage 1", "Passage 2"]

            ranked = await reranker.rank(query, passages)

            assert len(ranked) == 2
            assert ranked[0][1] == 0.8
            assert ranked[1][1] == 0.6

    @pytest.mark.asyncio
    async def test_rank_normalizes_scores(self, reranker):
        """Test that scores are normalized to [0, 1] range."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {"content": '{"scores": [1.5, -0.5, 2.0, 0.3]}'}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            query = "Test query"
            passages = ["P1", "P2", "P3", "P4"]

            ranked = await reranker.rank(query, passages)

            # All scores should be clamped to [0, 1]
            for _, score in ranked:
                assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_rank_handles_wrong_score_count(self, reranker):
        """Test handling when response has wrong number of scores."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        # Only 3 scores for 4 passages
        mock_response.choices[0].message = {"content": '{"scores": [0.9, 0.7, 0.3]}'}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            query = "Test query"
            passages = ["P1", "P2", "P3", "P4"]

            ranked = await reranker.rank(query, passages)

            # Should pad with neutral scores
            assert len(ranked) == 4
            assert ranked[-1][1] == 0.5  # Padding score

    @pytest.mark.asyncio
    async def test_rank_handles_api_error(self, reranker):
        """Test ranking with API error."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = Exception("API error")

            query = "Test query"
            passages = ["P1", "P2"]

            ranked = await reranker.rank(query, passages)

            # Should fall back to original order with neutral scores
            assert len(ranked) == 2
            assert ranked[0][0] == "P1"
            assert ranked[0][1] == 0.5
            assert ranked[1][0] == "P2"
            assert ranked[1][1] == 0.5

    @pytest.mark.asyncio
    async def test_rank_handles_invalid_json(self, reranker):
        """Test ranking with invalid JSON response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {"content": "Invalid JSON"}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            query = "Test query"
            passages = ["P1", "P2"]

            ranked = await reranker.rank(query, passages)

            # Should return neutral scores
            assert len(ranked) == 2
            for _, score in ranked:
                assert score == 0.5

    @pytest.mark.asyncio
    async def test_uses_reranker_model_from_config(self, reranker, provider_config):
        """Test that reranker uses the configured reranker model."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {"content": '{"scores": [0.8, 0.5]}'}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            query = "Test"
            passages = ["Test passage 1", "Test passage 2"]

            await reranker.rank(query, passages)

            # Check that the reranker model was used
            mock_acompletion.assert_called_once()
            call_args = mock_acompletion.call_args
            assert call_args[1]["model"] == provider_config.reranker_model
