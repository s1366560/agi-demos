"""Unit tests for ai_tools router."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.ai_tool_application_authority_v2 import (
    ai_tool_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import ai_tools as ai_tools_router
from src.infrastructure.plugins.v2.ai_tool_services import AiToolApplicationServicesV2


@pytest.fixture
def ai_tools_llm():
    """Return a tenant-bound mock LLM client and its V2 factory."""
    mock_llm_client = Mock()
    mock_llm_client.generate = AsyncMock(return_value={"content": "Test response"})
    mock_create_llm_client = AsyncMock(return_value=mock_llm_client)
    return mock_llm_client, mock_create_llm_client


@pytest.fixture
def client(ai_tools_llm) -> TestClient:
    """Exercise handlers through the real V2 application service seam."""
    _, mock_create_llm_client = ai_tools_llm
    app = FastAPI()
    app.include_router(ai_tools_router.router)
    persistence = SimpleNamespace(resolve_tenant_id=AsyncMock(return_value="tenant-a"))

    async def override_ai_tool_application():
        yield SimpleNamespace(
            user_id="user-a",
            tenant_id=None,
            services=AiToolApplicationServicesV2(
                persistence=persistence,
                client_factory=mock_create_llm_client,
            ),
        )

    app.dependency_overrides[ai_tool_application_authority_dependency_v2] = (
        override_ai_tool_application
    )
    return TestClient(app)


@pytest.mark.unit
class TestAIToolsRouter:
    """Test cases for ai_tools router endpoints."""

    @pytest.mark.asyncio
    async def test_optimize_content_success(self, client, ai_tools_llm):
        """Test successful content optimization."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.return_value = {
            "content": "Optimized content with improved clarity."
        }

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
    async def test_optimize_content_default_instruction(self, client, ai_tools_llm):
        """Test content optimization with default instruction."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.return_value = {"content": "Improved content"}

        # Make request without instruction
        response = client.post(
            "/api/v1/ai/optimize",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        mock_llm_client.generate.assert_called_once()
        # Verify prompt contains default instruction
        call_args = mock_llm_client.generate.call_args
        # messages is passed as keyword argument
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else [])
        assert "Improve clarity, fix grammar" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_optimize_content_llm_not_available(self, client, ai_tools_llm):
        """Test content optimization when LLM is not available."""
        _, mock_create_llm_client = ai_tools_llm
        mock_create_llm_client.return_value = None

        # Make request
        response = client.post(
            "/api/v1/ai/optimize",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
        assert "not available" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_optimize_content_llm_failure(self, client, ai_tools_llm):
        """Test content optimization when LLM call fails."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.side_effect = Exception("LLM error")

        # Make request
        response = client.post(
            "/api/v1/ai/optimize",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to optimize content"
        assert "LLM error" not in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_generate_title_success(self, client, ai_tools_llm):
        """Test successful title generation."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.return_value = {"content": "Generated Title"}

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
    async def test_generate_title_truncates_content(self, client, ai_tools_llm):
        """Test that long content is truncated for title generation."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.return_value = {"content": "Title"}

        # Make request with long content (>1000 chars)
        long_content = "x" * 2000
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": long_content},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        # Verify content was truncated
        call_args = mock_llm_client.generate.call_args
        # messages is passed as keyword argument
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else [])
        assert len(messages[0]["content"]) < 2000  # Should be truncated

    @pytest.mark.asyncio
    async def test_generate_title_removes_quotes(self, client, ai_tools_llm):
        """Test that quotes are removed from generated title."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.return_value = {"content": '"Generated Title"'}

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
    async def test_generate_title_llm_not_available(self, client, ai_tools_llm):
        """Test title generation when LLM is not available."""
        _, mock_create_llm_client = ai_tools_llm
        mock_create_llm_client.return_value = None

        # Make request
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_generate_title_llm_failure(self, client, ai_tools_llm):
        """Test title generation when LLM call fails."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.side_effect = Exception("API error")

        # Make request
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": "test content"},
        )

        # Assert
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to generate title"
        assert "API error" not in response.json()["detail"]


@pytest.mark.unit
class TestAIToolsEdgeCases:
    """Test edge cases for AI tools router."""

    @pytest.mark.asyncio
    async def test_optimize_empty_content(self, client, ai_tools_llm):
        """Test optimizing empty content."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.return_value = {"content": ""}

        # Make request with empty content
        response = client.post(
            "/api/v1/ai/optimize",
            json={"content": "", "instruction": "Fix it"},
        )

        # Assert - Should still process even if empty
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_generate_title_empty_content(self, client, ai_tools_llm):
        """Test generating title for empty content."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.return_value = {"content": "Untitled"}

        # Make request with empty content
        response = client.post(
            "/api/v1/ai/generate-title",
            json={"content": ""},
        )

        # Assert - Should still process
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_optimize_custom_instruction(self, client, ai_tools_llm):
        """Test content optimization with custom instruction."""
        mock_llm_client, _ = ai_tools_llm
        mock_llm_client.generate.return_value = {"content": "Simplified content"}

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
        call_args = mock_llm_client.generate.call_args
        # messages is passed as keyword argument
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else [])
        assert "Simplify for a 5-year-old" in messages[0]["content"]
