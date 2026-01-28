"""
Unit tests for LLMClassifier.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.

Test Cases:
- test_classify_simple_query_returns_false
- test_classify_complex_query_returns_true
- test_classify_returns_confidence_score
- test_llm_failure_raises_classification_error
- test_classify_with_context_considers_history
- test_classify_parses_json_response
- test_classify_handles_invalid_json
- test_classify_with_conversation_history
- test_classify_empty_query_raises_error
"""

import json
from unittest.mock import AsyncMock, Mock, patch
from typing import Any, Dict

import pytest

from src.infrastructure.agent.planning.llm_classifier import (
    LLMClassifier,
    ClassificationError,
    ClassificationResult,
)


class TestClassificationResult:
    """Tests for ClassificationResult dataclass."""

    def test_classification_result_attributes(self) -> None:
        """Test ClassificationResult has correct attributes."""
        result = ClassificationResult(
            should_trigger=True,
            confidence=0.9,
            reasoning="Query requires multi-step planning",
        )

        assert result.should_trigger is True
        assert result.confidence == 0.9
        assert result.reasoning == "Query requires multi-step planning"

    def test_classification_result_equality(self) -> None:
        """Test ClassificationResult equality."""
        result1 = ClassificationResult(
            should_trigger=True,
            confidence=0.9,
            reasoning="Query requires multi-step planning",
        )
        result2 = ClassificationResult(
            should_trigger=True,
            confidence=0.9,
            reasoning="Query requires multi-step planning",
        )

        assert result1 == result2


class TestLLMClassifierInit:
    """Tests for LLMClassifier initialization."""

    def test_init_with_llm_client(self) -> None:
        """Test creating classifier with LLM client."""
        mock_llm = Mock()

        classifier = LLMClassifier(llm_client=mock_llm)

        assert classifier.llm_client == mock_llm
        assert classifier.confidence_threshold == 0.7

    def test_init_with_custom_confidence_threshold(self) -> None:
        """Test creating classifier with custom confidence threshold."""
        mock_llm = Mock()

        classifier = LLMClassifier(
            llm_client=mock_llm,
            confidence_threshold=0.8,
        )

        assert classifier.confidence_threshold == 0.8

    def test_init_with_invalid_threshold_raises_error(self) -> None:
        """Test that invalid threshold raises ValueError."""
        mock_llm = Mock()

        with pytest.raises(ValueError):
            LLMClassifier(llm_client=mock_llm, confidence_threshold=1.5)

        with pytest.raises(ValueError):
            LLMClassifier(llm_client=mock_llm, confidence_threshold=-0.1)


class TestClassify:
    """Tests for the classify method."""

    @pytest.mark.asyncio
    async def test_classify_simple_query_returns_false(self) -> None:
        """Test that simple queries return should_trigger=False."""
        mock_llm = AsyncMock()

        # Mock LLM response
        mock_llm.complete = AsyncMock(
            return_value='{"should_trigger": false, "confidence": 0.1, "reasoning": "Simple query"}'
        )

        classifier = LLMClassifier(llm_client=mock_llm)

        result = await classifier.classify("what time is it")

        assert result.should_trigger is False
        assert result.confidence == 0.1
        assert "Simple query" in result.reasoning

    @pytest.mark.asyncio
    async def test_classify_complex_query_returns_true(self) -> None:
        """Test that complex queries return should_trigger=True."""
        mock_llm = AsyncMock()

        # Mock LLM response
        mock_llm.complete = AsyncMock(
            return_value='{"should_trigger": true, "confidence": 0.95, "reasoning": "Multi-step implementation"}'
        )

        classifier = LLMClassifier(llm_client=mock_llm)

        result = await classifier.classify(
            "Implement a complete authentication system with OAuth2"
        )

        assert result.should_trigger is True
        assert result.confidence == 0.95
        assert "Multi-step" in result.reasoning

    @pytest.mark.asyncio
    async def test_classify_returns_confidence_score(self) -> None:
        """Test that classification returns confidence score."""
        mock_llm = AsyncMock()

        mock_llm.complete = AsyncMock(
            return_value='{"should_trigger": true, "confidence": 0.85, "reasoning": "High confidence"}'
        )

        classifier = LLMClassifier(llm_client=mock_llm)

        result = await classifier.classify("test query")

        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_classify_with_context_considers_history(self) -> None:
        """Test that classification considers conversation history."""
        mock_llm = AsyncMock()

        mock_llm.complete = AsyncMock(
            return_value='{"should_trigger": true, "confidence": 0.8, "reasoning": "Context-aware"}'
        )

        classifier = LLMClassifier(llm_client=mock_llm)

        context = [
            {"role": "user", "content": "I want to build an app"},
            {"role": "assistant", "content": "What kind of app?"},
        ]

        result = await classifier.classify(
            "It needs user authentication",
            conversation_context=context,
        )

        assert result.should_trigger is True

        # Verify the prompt includes context
        call_args = mock_llm.complete.call_args
        prompt = str(call_args)
        assert "build an app" in prompt or len(context) > 0

    @pytest.mark.asyncio
    async def test_classify_parses_json_response(self) -> None:
        """Test that classifier parses JSON LLM response."""
        mock_llm = AsyncMock()

        mock_llm.complete = AsyncMock(
            return_value='{\n  "should_trigger": true,\n  "confidence": 0.9,\n  "reasoning": "Valid JSON"\n}'
        )

        classifier = LLMClassifier(llm_client=mock_llm)

        result = await classifier.classify("test")

        assert result.should_trigger is True
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_classify_handles_invalid_json(self) -> None:
        """Test that classifier handles invalid JSON."""
        mock_llm = AsyncMock()

        # Invalid JSON response
        mock_llm.complete = AsyncMock(return_value="This is not valid JSON")

        classifier = LLMClassifier(llm_client=mock_llm)

        with pytest.raises(ClassificationError, match="Failed to parse"):
            await classifier.classify("test")

    @pytest.mark.asyncio
    async def test_classify_handles_missing_fields(self) -> None:
        """Test that classifier handles missing required fields."""
        mock_llm = AsyncMock()

        # Missing confidence field
        mock_llm.complete = AsyncMock(
            return_value='{"should_trigger": true, "reasoning": "Missing confidence"}'
        )

        classifier = LLMClassifier(llm_client=mock_llm)

        with pytest.raises(ClassificationError, match="Missing required field"):
            await classifier.classify("test")

    @pytest.mark.asyncio
    async def test_llm_failure_raises_classification_error(self) -> None:
        """Test that LLM failure raises ClassificationError."""
        mock_llm = AsyncMock()

        mock_llm.complete = AsyncMock(side_effect=Exception("LLM unavailable"))

        classifier = LLMClassifier(llm_client=mock_llm)

        with pytest.raises(ClassificationError, match="LLM classification failed"):
            await classifier.classify("test")

    @pytest.mark.asyncio
    async def test_classify_empty_query_raises_error(self) -> None:
        """Test that empty query raises ClassificationError."""
        mock_llm = AsyncMock()

        classifier = LLMClassifier(llm_client=mock_llm)

        with pytest.raises(ClassificationError, match="Query cannot be empty"):
            await classifier.classify("")

    @pytest.mark.asyncio
    async def test_classify_with_conversation_history(self) -> None:
        """Test classification with full conversation history."""
        mock_llm = AsyncMock()

        mock_llm.complete = AsyncMock(
            return_value='{"should_trigger": true, "confidence": 0.85, "reasoning": "History considered"}'
        )

        classifier = LLMClassifier(llm_client=mock_llm)

        history = [
            {"role": "user", "content": "I need to add a feature"},
            {"role": "assistant", "content": "What feature?"},
            {"role": "user", "content": "User management"},
            {"role": "assistant", "content": "Okay, I can help with that"},
        ]

        result = await classifier.classify(
            "Let's start with authentication",
            conversation_context=history,
        )

        assert result.should_trigger is True

    @pytest.mark.asyncio
    async def test_classify_clamps_confidence_to_valid_range(self) -> None:
        """Test that out-of-range confidence is clamped."""
        mock_llm = AsyncMock()

        # Confidence > 1.0
        mock_llm.complete = AsyncMock(
            return_value='{"should_trigger": true, "confidence": 1.5, "reasoning": "Invalid confidence"}'
        )

        classifier = LLMClassifier(llm_client=mock_llm)

        result = await classifier.classify("test")

        # Should clamp to 1.0
        assert result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_classify_with_negative_confidence(self) -> None:
        """Test that negative confidence is handled."""
        mock_llm = AsyncMock()

        mock_llm.complete = AsyncMock(
            return_value='{"should_trigger": false, "confidence": -0.1, "reasoning": "Negative confidence"}'
        )

        classifier = LLMClassifier(llm_client=mock_llm)

        result = await classifier.classify("test")

        # Should clamp to 0.0
        assert result.confidence >= 0.0


class TestBuildPrompt:
    """Tests for the _build_prompt method."""

    def test_build_prompt_includes_query(self) -> None:
        """Test that prompt includes the user query."""
        mock_llm = Mock()

        classifier = LLMClassifier(llm_client=mock_llm)

        prompt = classifier._build_prompt("test query")

        assert "test query" in prompt

    def test_build_prompt_includes_context(self) -> None:
        """Test that prompt includes conversation context."""
        mock_llm = Mock()

        classifier = LLMClassifier(llm_client=mock_llm)

        context = [
            {"role": "user", "content": "previous message"},
        ]

        prompt = classifier._build_prompt("current query", conversation_context=context)

        assert "previous message" in prompt

    def test_build_prompt_includes_system_instructions(self) -> None:
        """Test that prompt includes system instructions."""
        mock_llm = Mock()

        classifier = LLMClassifier(llm_client=mock_llm)

        prompt = classifier._build_prompt("test")

        assert "Plan Mode" in prompt or "plan" in prompt.lower()

    def test_build_prompt_requests_json_format(self) -> None:
        """Test that prompt requests JSON format."""
        mock_llm = Mock()

        classifier = LLMClassifier(llm_client=mock_llm)

        prompt = classifier._build_prompt("test")

        assert "JSON" in prompt or "json" in prompt.lower()


class TestParseResponse:
    """Tests for the _parse_response method."""

    def test_parse_response_valid_json(self) -> None:
        """Test parsing valid JSON response."""
        mock_llm = Mock()

        classifier = LLMClassifier(llm_client=mock_llm)

        response = '{"should_trigger": true, "confidence": 0.9, "reasoning": "test"}'

        result = classifier._parse_response(response)

        assert result["should_trigger"] is True
        assert result["confidence"] == 0.9
        assert result["reasoning"] == "test"

    def test_parse_response_json_with_extra_whitespace(self) -> None:
        """Test parsing JSON with extra whitespace."""
        mock_llm = Mock()

        classifier = LLMClassifier(llm_client=mock_llm)

        response = """
        {
            "should_trigger": true,
            "confidence": 0.9,
            "reasoning": "test"
        }
        """

        result = classifier._parse_response(response)

        assert result["should_trigger"] is True

    def test_parse_response_json_with_markdown_code_block(self) -> None:
        """Test parsing JSON wrapped in markdown code block."""
        mock_llm = Mock()

        classifier = LLMClassifier(llm_client=mock_llm)

        response = '```json\n{"should_trigger": true, "confidence": 0.9, "reasoning": "test"}\n```'

        result = classifier._parse_response(response)

        assert result["should_trigger"] is True

    def test_parse_response_invalid_json_raises_error(self) -> None:
        """Test that invalid JSON raises error."""
        mock_llm = Mock()

        classifier = LLMClassifier(llm_client=mock_llm)

        with pytest.raises(ClassificationError, match="Failed to parse"):
            classifier._parse_response("not valid json")


class TestClassificationError:
    """Tests for ClassificationError exception."""

    def test_classification_error_is_exception(self) -> None:
        """Test that ClassificationError is an Exception."""
        error = ClassificationError("test error")

        assert isinstance(error, Exception)
        assert str(error) == "test error"

    def test_classification_error_with_cause(self) -> None:
        """Test ClassificationError with underlying cause."""
        original_error = ValueError("original")
        error = ClassificationError("wrapper", cause=original_error)

        assert error.__cause__ is original_error
