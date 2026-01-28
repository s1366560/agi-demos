"""
Unit tests for HybridPlanModeDetector.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.

Test Cases:
- test_very_short_query_fast_reject
- test_high_score_query_fast_accept
- test_low_score_query_fast_reject
- test_mid_score_query_uses_llm
- test_cache_hit_returns_cached_result
- test_llm_classification_returns_result
- test_disabled_detector_returns_false
- test_returns_detection_method_and_confidence
- test_llm_failure_falls_back_to_heuristic
- test_detector_uses_cache_when_enabled
"""

from unittest.mock import AsyncMock, Mock
from typing import Any, Dict

import pytest

from src.infrastructure.agent.planning.hybrid_plan_mode_detector import (
    HybridPlanModeDetector,
    DetectionResult,
)
from src.infrastructure.agent.planning.fast_heuristic_detector import (
    FastHeuristicDetector,
)
from src.infrastructure.agent.planning.llm_classifier import (
    LLMClassifier,
    ClassificationResult,
)
from src.infrastructure.agent.planning.llm_cache import (
    LLMResponseCache,
)


class TestHybridPlanModeDetectorInit:
    """Tests for HybridPlanModeDetector initialization."""

    def test_init_with_required_dependencies(self) -> None:
        """Test creating detector with all dependencies."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)
        mock_cache = Mock(spec=LLMResponseCache)

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
            cache=mock_cache,
        )

        assert detector.heuristic_detector == mock_heuristic
        assert detector.llm_classifier == mock_llm
        assert detector.cache == mock_cache
        assert detector.enabled is True

    def test_init_with_cache_disabled(self) -> None:
        """Test creating detector with cache disabled."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
            cache=None,
        )

        assert detector.cache is None

    def test_init_disabled(self) -> None:
        """Test creating disabled detector."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
            enabled=False,
        )

        assert detector.enabled is False


class TestLayer1FastReject:
    """Tests for Layer 1: Very short query fast reject."""

    @pytest.mark.asyncio
    async def test_very_short_query_fast_reject(self) -> None:
        """Test that very short queries are rejected without LLM."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        # Mock heuristic to return low score
        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.05,
                method="heuristic",
            )
        )

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
        )

        result = await detector.detect("hi")

        assert result.should_trigger is False
        assert result.method == "heuristic"
        assert result.confidence == 0.05
        # LLM should not be called for low scores
        assert not mock_llm.classify.called


class TestLayer2HeuristicFastPath:
    """Tests for Layer 2: Heuristic fast path (accept/reject)."""

    @pytest.mark.asyncio
    async def test_high_score_query_fast_accept(self) -> None:
        """Test that high scores (> threshold) auto-accept without LLM."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        # Mock heuristic to return high score
        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=True,
                confidence=0.9,
                method="heuristic",
            )
        )

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
        )

        result = await detector.detect(
            "Implement a comprehensive authentication system with multiple components"
        )

        assert result.should_trigger is True
        assert result.method == "heuristic"
        assert result.confidence == 0.9
        # LLM should not be called for high scores
        assert not mock_llm.classify.called

    @pytest.mark.asyncio
    async def test_low_score_query_fast_reject(self) -> None:
        """Test that low scores (< threshold) auto-reject without LLM."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        # Mock heuristic to return low score
        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.1,
                method="heuristic",
            )
        )

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
        )

        result = await detector.detect("simple search")

        assert result.should_trigger is False
        assert result.method == "heuristic"
        # LLM should not be called for low scores
        assert not mock_llm.classify.called


class TestLayer3LLMClassification:
    """Tests for Layer 3: LLM classification for ambiguous scores."""

    @pytest.mark.asyncio
    async def test_mid_score_query_uses_llm(self) -> None:
        """Test that mid-range scores use LLM classification."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        # Mock heuristic to return mid-range score
        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=False,  # Low but not below threshold
                confidence=0.5,  # In ambiguous range
                method="heuristic",
            )
        )

        # Mock LLM to return true
        mock_llm.classify = AsyncMock(
            return_value=ClassificationResult(
                should_trigger=True,
                confidence=0.8,
                reasoning="Complex multi-step query",
            )
        )

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
        )

        result = await detector.detect("Implement user authentication")

        assert result.should_trigger is True
        assert result.method == "llm"
        assert result.confidence == 0.8
        # LLM should be called for mid-range scores
        assert mock_llm.classify.called

    @pytest.mark.asyncio
    async def test_llm_classification_returns_result(self) -> None:
        """Test that LLM classification result is returned correctly."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.5,
                method="heuristic",
            )
        )

        mock_llm.classify = AsyncMock(
            return_value=ClassificationResult(
                should_trigger=False,
                confidence=0.3,
                reasoning="Simple query",
            )
        )

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
        )

        result = await detector.detect("test query")

        assert result.should_trigger is False
        assert result.method == "llm"
        assert result.confidence == 0.3


class TestCacheLayer:
    """Tests for cache layer in LLM classification."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self) -> None:
        """Test that cache hit returns cached result without LLM call."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)
        mock_cache = Mock(spec=LLMResponseCache)

        # Mock heuristic to return mid-range score
        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.5,
                method="heuristic",
            )
        )

        # Mock cache hit
        mock_cache.get = Mock(return_value='{"should_trigger": true}')

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
            cache=mock_cache,
        )

        result = await detector.detect("cached query")

        assert result.should_trigger is True
        assert result.method == "cache"
        # LLM should not be called on cache hit
        assert not mock_llm.classify.called

    @pytest.mark.asyncio
    async def test_cache_miss_calls_llm(self) -> None:
        """Test that cache miss calls LLM."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)
        mock_cache = Mock(spec=LLMResponseCache)

        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.5,
                method="heuristic",
            )
        )

        # Mock cache miss
        mock_cache.get = Mock(return_value=None)

        mock_llm.classify = AsyncMock(
            return_value=ClassificationResult(
                should_trigger=True,
                confidence=0.8,
                reasoning="Needs planning",
            )
        )

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
            cache=mock_cache,
        )

        result = await detector.detect("uncached query")

        assert result.should_trigger is True
        assert result.method == "llm"
        # LLM should be called on cache miss
        assert mock_llm.classify.called

    @pytest.mark.asyncio
    async def test_detector_uses_cache_when_enabled(self) -> None:
        """Test that detector uses cache when enabled."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)
        mock_cache = Mock(spec=LLMResponseCache)

        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.5,
                method="heuristic",
            )
        )

        mock_cache.get = Mock(return_value=None)

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
            cache=mock_cache,
        )

        await detector.detect("test")

        # Cache get should be called
        assert mock_cache.get.called


class TestDisabledDetector:
    """Tests for disabled detector."""

    @pytest.mark.asyncio
    async def test_disabled_detector_returns_false(self) -> None:
        """Test that disabled detector always returns False."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
            enabled=False,
        )

        result = await detector.detect("any query")

        assert result.should_trigger is False
        assert result.method == "disabled"
        # Heuristic and LLM should not be called when disabled
        assert not mock_heuristic.detect.called
        assert not mock_llm.classify.called


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_heuristic(self) -> None:
        """Test that LLM failure falls back to heuristic result."""
        from src.infrastructure.agent.planning.llm_classifier import ClassificationError

        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.5,
                method="heuristic",
            )
        )

        # Mock LLM to raise error
        mock_llm.classify = AsyncMock(
            side_effect=ClassificationError("LLM unavailable")
        )

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
        )

        result = await detector.detect("test query")

        # Should fall back to heuristic result
        assert result.method == "heuristic"
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_returns_detection_method_and_confidence(self) -> None:
        """Test that result includes method and confidence."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)

        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=True,
                confidence=0.85,
                method="heuristic",
            )
        )

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
        )

        result = await detector.detect("test")

        assert hasattr(result, "method")
        assert hasattr(result, "confidence")
        assert result.method == "heuristic"
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_detect_with_conversation_context(self) -> None:
        """Test detection with conversation context."""
        mock_heuristic = Mock(spec=FastHeuristicDetector)
        mock_llm = Mock(spec=LLMClassifier)
        mock_cache = Mock(spec=LLMResponseCache)

        mock_heuristic.detect = Mock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.5,
                method="heuristic",
            )
        )

        mock_cache.get = Mock(return_value=None)

        mock_llm.classify = AsyncMock(
            return_value=ClassificationResult(
                should_trigger=True,
                confidence=0.8,
                reasoning="Context-aware",
            )
        )

        detector = HybridPlanModeDetector(
            heuristic_detector=mock_heuristic,
            llm_classifier=mock_llm,
            cache=mock_cache,
        )

        context = [{"role": "user", "content": "previous"}]

        result = await detector.detect("test", conversation_context=context)

        assert result.should_trigger is True

        # Verify context was passed to cache and LLM
        mock_cache.get.assert_called_once()
        mock_llm.classify.assert_called_once()

        # Check that context was included in the calls
        # (passed as positional argument in implementation)
        classify_args = mock_llm.classify.call_args[0]
        assert len(classify_args) >= 2  # query and context


class TestDetectionResult:
    """Tests for DetectionResult."""

    def test_detection_result_to_dict(self) -> None:
        """Test DetectionResult serialization."""
        result = DetectionResult(
            should_trigger=True,
            confidence=0.8,
            method="llm",
        )

        data = result.to_dict()

        assert data["should_trigger"] is True
        assert data["confidence"] == 0.8
        assert data["method"] == "llm"
