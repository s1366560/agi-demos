"""Unit tests for SummaryTool."""

from unittest.mock import AsyncMock, Mock

import pytest
from src.infrastructure.agent.tools.summary import SummaryTool


class TestSummaryToolInit:
    """Test SummaryTool initialization."""

    def test_init_sets_correct_name(self, mock_llm):
        """Test tool initializes with correct name."""
        tool = SummaryTool(mock_llm)
        assert tool.name == "summary"

    def test_init_sets_description(self, mock_llm):
        """Test tool initializes with meaningful description."""
        tool = SummaryTool(mock_llm)
        assert "summary" in tool.description.lower() or "summarize" in tool.description.lower()


class TestSummaryToolValidation:
    """Test SummaryTool argument validation."""

    def test_validate_args_with_valid_text(self, mock_llm):
        """Test validation passes with valid text."""
        tool = SummaryTool(mock_llm)
        assert tool.validate_args(text="This is some text to summarize") is True

    def test_validate_args_with_empty_text(self, mock_llm):
        """Test validation fails with empty text."""
        tool = SummaryTool(mock_llm)
        assert tool.validate_args(text="") is False

    def test_validate_args_with_whitespace_only(self, mock_llm):
        """Test validation fails with whitespace-only text."""
        tool = SummaryTool(mock_llm)
        assert tool.validate_args(text="   ") is False
        assert tool.validate_args(text="\t\n") is False

    def test_validate_args_missing_text(self, mock_llm):
        """Test validation fails when text is missing."""
        tool = SummaryTool(mock_llm)
        assert tool.validate_args() is False
        assert tool.validate_args(max_length=100) is False

    def test_validate_args_non_string_text(self, mock_llm):
        """Test validation fails with non-string text."""
        tool = SummaryTool(mock_llm)
        assert tool.validate_args(text=123) is False
        assert tool.validate_args(text=None) is False
        assert tool.validate_args(text=["list"]) is False


class TestSummaryToolExecute:
    """Test SummaryTool execute method."""

    @pytest.mark.asyncio
    async def test_execute_generates_summary(self, mock_llm):
        """Test execute generates summary from LLM."""
        mock_response = Mock()
        mock_response.content = "This is a concise summary of the provided text."
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        result = await tool.execute(text="Long text that needs to be summarized...")

        assert "Summary" in result
        assert "concise summary" in result

    @pytest.mark.asyncio
    async def test_execute_calls_llm_ainvoke(self, mock_llm):
        """Test execute calls LLM ainvoke method."""
        mock_response = Mock()
        mock_response.content = "Summary content"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        await tool.execute(text="Text to summarize")

        mock_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_custom_max_length(self, mock_llm):
        """Test execute uses custom max_length in prompt."""
        mock_response = Mock()
        mock_response.content = "Short summary"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        await tool.execute(text="Text to summarize", max_length=50)

        call_args = mock_llm.ainvoke.call_args
        prompt = call_args[0][0]
        assert "50" in prompt

    @pytest.mark.asyncio
    async def test_execute_default_max_length_is_100(self, mock_llm):
        """Test execute uses default max_length of 100."""
        mock_response = Mock()
        mock_response.content = "Default summary"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        await tool.execute(text="Text to summarize")

        call_args = mock_llm.ainvoke.call_args
        prompt = call_args[0][0]
        assert "100" in prompt

    @pytest.mark.asyncio
    async def test_execute_returns_word_count(self, mock_llm):
        """Test execute includes word count in response."""
        mock_response = Mock()
        mock_response.content = "This is a five word summary"  # 6 words
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        result = await tool.execute(text="Text to summarize")

        assert "Summary (" in result
        assert "words)" in result

    @pytest.mark.asyncio
    async def test_execute_missing_text_returns_error(self, mock_llm):
        """Test execute returns error when text is missing."""
        tool = SummaryTool(mock_llm)
        result = await tool.execute()

        assert "Error" in result
        assert "text parameter is required" in result

    @pytest.mark.asyncio
    async def test_execute_includes_text_in_prompt(self, mock_llm):
        """Test execute includes the text in LLM prompt."""
        mock_response = Mock()
        mock_response.content = "Summary"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        await tool.execute(text="The quick brown fox jumps over the lazy dog")

        call_args = mock_llm.ainvoke.call_args
        prompt = call_args[0][0]
        assert "quick brown fox" in prompt

    @pytest.mark.asyncio
    async def test_execute_strips_response_content(self, mock_llm):
        """Test execute strips whitespace from LLM response."""
        mock_response = Mock()
        mock_response.content = "  Summary with whitespace  \n"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        result = await tool.execute(text="Text to summarize")

        assert "Summary with whitespace" in result
        # Should not have leading/trailing whitespace in the summary part


class TestSummaryToolErrorHandling:
    """Test SummaryTool error handling."""

    @pytest.mark.asyncio
    async def test_execute_handles_llm_error(self, mock_llm):
        """Test execute handles LLM errors gracefully."""
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM service unavailable"))

        tool = SummaryTool(mock_llm)
        result = await tool.execute(text="Text to summarize")

        assert "Error generating summary" in result
        assert "LLM service unavailable" in result

    @pytest.mark.asyncio
    async def test_execute_handles_timeout(self, mock_llm):
        """Test execute handles timeout errors."""
        mock_llm.ainvoke = AsyncMock(side_effect=TimeoutError("Request timed out"))

        tool = SummaryTool(mock_llm)
        result = await tool.execute(text="Text to summarize")

        assert "Error generating summary" in result

    @pytest.mark.asyncio
    async def test_execute_handles_rate_limit(self, mock_llm):
        """Test execute handles rate limit errors."""
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("Rate limit exceeded"))

        tool = SummaryTool(mock_llm)
        result = await tool.execute(text="Text to summarize")

        assert "Error generating summary" in result
        assert "Rate limit" in result


class TestSummaryToolPromptConstruction:
    """Test SummaryTool prompt construction."""

    @pytest.mark.asyncio
    async def test_prompt_requests_concise_summary(self, mock_llm):
        """Test prompt requests a concise summary."""
        mock_response = Mock()
        mock_response.content = "Summary"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        await tool.execute(text="Text")

        call_args = mock_llm.ainvoke.call_args
        prompt = call_args[0][0]
        assert "concise" in prompt.lower() or "summary" in prompt.lower()

    @pytest.mark.asyncio
    async def test_prompt_specifies_target_length(self, mock_llm):
        """Test prompt specifies target word length."""
        mock_response = Mock()
        mock_response.content = "Summary"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        await tool.execute(text="Text", max_length=75)

        call_args = mock_llm.ainvoke.call_args
        prompt = call_args[0][0]
        assert "75" in prompt
        assert "words" in prompt.lower()

    @pytest.mark.asyncio
    async def test_prompt_requests_no_preamble(self, mock_llm):
        """Test prompt requests no additional commentary."""
        mock_response = Mock()
        mock_response.content = "Summary"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        await tool.execute(text="Text")

        call_args = mock_llm.ainvoke.call_args
        prompt = call_args[0][0]
        # Should request only the summary without preamble
        assert "only" in prompt.lower() or "without" in prompt.lower()


class TestSummaryToolWordCount:
    """Test SummaryTool word count calculation."""

    @pytest.mark.asyncio
    async def test_word_count_single_word(self, mock_llm):
        """Test word count for single word summary."""
        mock_response = Mock()
        mock_response.content = "Done"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        result = await tool.execute(text="Text")

        assert "(1 words)" in result

    @pytest.mark.asyncio
    async def test_word_count_multiple_words(self, mock_llm):
        """Test word count for multi-word summary."""
        mock_response = Mock()
        mock_response.content = "This is a ten word summary for testing purposes here"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        result = await tool.execute(text="Text")

        assert "(10 words)" in result

    @pytest.mark.asyncio
    async def test_word_count_handles_extra_whitespace(self, mock_llm):
        """Test word count handles extra whitespace correctly."""
        mock_response = Mock()
        mock_response.content = "Word   count    with    spaces"  # 4 words
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        tool = SummaryTool(mock_llm)
        result = await tool.execute(text="Text")

        assert "(4 words)" in result
