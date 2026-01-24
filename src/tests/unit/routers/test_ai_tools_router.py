"""Unit tests for ai_tools router."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import status


@pytest.mark.unit
class TestAIToolsRouter:
    """Test cases for ai_tools router endpoints."""

    @pytest.mark.asyncio
    async def test_optimize_content_success(self, client, mock_graphiti_client):
        """Test successful content optimization."""
        # Mock LLM client
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(
            return_value="Optimized content with improved clarity."
        )
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request
        response = client.post(
            "/api/v1/ai/optimize",
            json={
                "content": "original content",
                "instruction": "Improve clarity",
            },
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "content" in data
        assert data["content"] == "Optimized content with improved clarity."

    @pytest.mark.asyncio
    async def test_optimize_content_default_instruction(self, client, mock_graphiti_client):
        """Test content optimization with default instruction."""
        # Mock LLM client
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(return_value="Improved content")
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request without instruction
        response = client.post(
            "/api/v1/ai/optimize",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        mock_llm_client.generate_response.assert_called_once()
        # Verify prompt contains default instruction
        call_args = mock_llm_client.generate_response.call_args
        # messages is passed as keyword argument
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else [])
        assert "Improve clarity, fix grammar" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_optimize_content_llm_not_available(self, client, mock_graphiti_client):
        """Test content optimization when LLM is not available."""
        # Mock no LLM client
        mock_graphiti_client.llm_client = None
        mock_graphiti_client.client = Mock()
        mock_graphiti_client.client.llm_client = None

        # Make request
        response = client.post(
            "/api/v1/ai/optimize",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
        assert "not available" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_optimize_content_llm_failure(self, client, mock_graphiti_client):
        """Test content optimization when LLM call fails."""
        # Mock LLM failure
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(side_effect=Exception("LLM error"))
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request
        response = client.post(
            "/api/v1/ai/optimize",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.asyncio
    async def test_generate_title_success(self, client, mock_graphiti_client):
        """Test successful title generation."""
        # Mock LLM client
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(return_value="Generated Title")
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": "This is a long content that needs a title..."},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "title" in data
        assert data["title"] == "Generated Title"

    @pytest.mark.asyncio
    async def test_generate_title_truncates_content(self, client, mock_graphiti_client):
        """Test that long content is truncated for title generation."""
        # Mock LLM client
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(return_value="Title")
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request with long content (>1000 chars)
        long_content = "x" * 2000
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": long_content},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        # Verify content was truncated
        call_args = mock_llm_client.generate_response.call_args
        # messages is passed as keyword argument
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else [])
        assert len(messages[0]["content"]) < 2000  # Should be truncated

    @pytest.mark.asyncio
    async def test_generate_title_removes_quotes(self, client, mock_graphiti_client):
        """Test that quotes are removed from generated title."""
        # Mock LLM client returning title with quotes
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(return_value='"Generated Title"')
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Quotes should be stripped
        assert data["title"] == "Generated Title"
        assert not data["title"].startswith('"')
        assert not data["title"].endswith('"')

    @pytest.mark.asyncio
    async def test_generate_title_llm_not_available(self, client, mock_graphiti_client):
        """Test title generation when LLM is not available."""
        # Mock no LLM client
        mock_graphiti_client.llm_client = None
        mock_graphiti_client.client = None

        # Make request
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_generate_title_llm_failure(self, client, mock_graphiti_client):
        """Test title generation when LLM call fails."""
        # Mock LLM failure
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(side_effect=Exception("API error"))
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.unit
class TestAIToolsEdgeCases:
    """Test edge cases for AI tools router."""

    @pytest.mark.asyncio
    async def test_optimize_empty_content(self, client, mock_graphiti_client):
        """Test optimizing empty content."""
        # Mock LLM client
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(return_value="")
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request with empty content
        response = client.post(
            "/api/v1/ai/optimize",
            json={"content": "", "instruction": "Fix it"},
        )

        # Assert - Should still process even if empty
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_generate_title_empty_content(self, client, mock_graphiti_client):
        """Test generating title for empty content."""
        # Mock LLM client
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(return_value="Untitled")
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request with empty content
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": ""},
        )

        # Assert - Should still process
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_optimize_custom_instruction(self, client, mock_graphiti_client):
        """Test content optimization with custom instruction."""
        # Mock LLM client
        mock_llm_client = Mock()
        mock_llm_client.generate_response = AsyncMock(return_value="Simplified content")
        mock_graphiti_client.llm_client = mock_llm_client

        # Make request with custom instruction
        response = client.post(
            "/api/v1/ai/optimize",
            json={
                "content": "Complex content here",
                "instruction": "Simplify for a 5-year-old",
            },
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        # Verify instruction was passed to LLM
        call_args = mock_llm_client.generate_response.call_args
        # messages is passed as keyword argument
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else [])
        assert "Simplify for a 5-year-old" in messages[0]["content"]
