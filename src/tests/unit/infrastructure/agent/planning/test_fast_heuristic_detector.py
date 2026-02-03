"""
Unit tests for FastHeuristicDetector.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.

Test Cases:
- test_very_short_query_returns_low_score
- test_long_query_returns_higher_score
- test_query_with_complexity_keywords_increases_score
- test_query_with_dependency_patterns_increases_score
- test_multi_sentence_query_increases_score
- test_get_complexity_score_clamps_to_1_0
- test_get_complexity_score_empty_query_returns_0
- test_detect_returns_detection_result_with_method
- test_detect_with_high_score_exceeds_threshold
- test_detect_with_low_score_below_threshold
"""


from src.infrastructure.agent.planning.fast_heuristic_detector import FastHeuristicDetector


class TestGetLengthScore:
    """Tests for length-based scoring."""

    def test_very_short_query_returns_low_score(self) -> None:
        """Test that very short queries (< 30 chars) return low score."""
        detector = FastHeuristicDetector()

        score = detector.get_length_score("hi")

        # Very short queries should get minimal length score
        assert score < 0.1

    def test_long_query_returns_higher_score(self) -> None:
        """Test that longer queries get higher length scores."""
        detector = FastHeuristicDetector()

        short_score = detector.get_length_score("hello")
        long_score = detector.get_length_score(
            "I need to implement a comprehensive user authentication system "
            "with OAuth2, JWT tokens, and session management"
        )

        assert long_score > short_score

    def test_max_length_scores_maximum(self) -> None:
        """Test that queries >= 200 chars get max length score."""
        detector = FastHeuristicDetector()

        # Create a 300 char query
        long_query = "This is a very long query. " * 20  # ~380 chars

        score = detector.get_length_score(long_query)

        assert score >= 0.25  # Max length score is 0.3 (30% weight)


class TestGetKeywordScore:
    """Tests for keyword-based scoring."""

    def test_query_with_complexity_keywords_increases_score(self) -> None:
        """Test that complexity keywords increase the score."""
        detector = FastHeuristicDetector()

        # Without complexity keywords
        simple_query = "search for files"
        simple_score = detector.get_keyword_score(simple_query)

        # With complexity keywords
        complex_query = "implement a feature that requires multiple steps"
        complex_score = detector.get_keyword_score(complex_query)

        assert complex_score > simple_score

    def test_multiple_complexity_keywords_accumulate(self) -> None:
        """Test that multiple complexity keywords accumulate score."""
        detector = FastHeuristicDetector()

        single_keyword = detector.get_keyword_score("create a file")
        multiple_keywords = detector.get_keyword_score(
            "analyze the system and implement a feature with multiple steps"
        )

        assert multiple_keywords > single_keyword

    def test_max_keyword_score_clamped(self) -> None:
        """Test that keyword score is clamped at 0.4 (40% weight)."""
        detector = FastHeuristicDetector()

        # Create query with many complexity keywords
        query = (
            "implement analyze design create develop build test deploy "
            "refactor optimize document review verify validate feature system "
            "application architecture"
        )

        score = detector.get_keyword_score(query)

        assert score <= 0.4


class TestGetStructuralScore:
    """Tests for structural-based scoring."""

    def test_multi_sentence_query_increases_score(self) -> None:
        """Test that multi-sentence queries get higher scores."""
        detector = FastHeuristicDetector()

        single_sentence = "Create a user authentication system"
        multi_sentence = (
            "First, I need to analyze the requirements. "
            "Then, I'll design the database schema. "
            "Finally, I'll implement the authentication logic."
        )

        single_score = detector.get_structural_score(single_sentence)
        multi_score = detector.get_structural_score(multi_sentence)

        assert multi_score > single_score

    def test_query_with_dependency_patterns_increases_score(self) -> None:
        """Test that dependency patterns increase the score."""
        detector = FastHeuristicDetector()

        no_dependency = "Create a user model"
        with_dependency = (
            "After creating the user model, "
            "I need to update the authentication service to use it"
        )

        no_dep_score = detector.get_structural_score(no_dependency)
        with_dep_score = detector.get_structural_score(with_dependency)

        assert with_dep_score > no_dep_score

    def test_query_with_numbered_steps_increases_score(self) -> None:
        """Test that numbered steps increase the score."""
        detector = FastHeuristicDetector()

        no_steps = "Implement authentication"
        with_steps = (
            "1. Create user model. "
            "2. Implement login endpoint. "
            "3. Add JWT token generation."
        )

        no_steps_score = detector.get_structural_score(no_steps)
        with_steps_score = detector.get_structural_score(with_steps)

        assert with_steps_score > no_steps_score

    def test_max_structural_score_clamped(self) -> None:
        """Test that structural score is clamped at 0.3 (30% weight)."""
        detector = FastHeuristicDetector()

        # Create query with many structural indicators
        query = (
            "First, create the database schema. "
            "Second, implement the API endpoints. "
            "Third, add authentication middleware. "
            "After that, write unit tests. "
            "Finally, deploy to production. "
            "Then, monitor the application. "
            "Next, gather user feedback. "
            "Last, iterate on improvements."
        )

        score = detector.get_structural_score(query)

        assert score <= 0.3


class TestGetComplexityScore:
    """Tests for overall complexity scoring."""

    def test_get_complexity_score_combines_all_scores(self) -> None:
        """Test that complexity score combines length, keyword, and structural."""
        detector = FastHeuristicDetector()

        # A query with all three aspects
        query = (
            "I need to implement a comprehensive authentication system. "
            "First, I'll create the user model with password hashing. "
            "Then, I'll design the JWT token generation logic. "
            "After that, I'll implement the login and logout endpoints. "
            "Finally, I'll add the authentication middleware to protect routes."
        )

        score = detector.get_complexity_score(query)

        # Should have contributions from all three components
        assert 0 < score <= 1.0

    def test_get_complexity_score_clamps_to_1_0(self) -> None:
        """Test that complexity score is clamped at 1.0."""
        detector = FastHeuristicDetector()

        # Create a maximally complex query
        max_query = (
            "First, analyze and design the system architecture. "
            "Then, implement the feature with multiple components. "
            "After that, create comprehensive unit tests. "
            "Finally, deploy and monitor the production system. "
            "Next, gather feedback and iterate on improvements. "
            "Last, optimize performance and refactor code. " * 10
        )

        score = detector.get_complexity_score(max_query)

        assert score <= 1.0

    def test_get_complexity_score_empty_query_returns_0(self) -> None:
        """Test that empty queries return 0."""
        detector = FastHeuristicDetector()

        score = detector.get_complexity_score("")

        assert score == 0

    def test_get_complexity_score_whitespace_only_returns_0(self) -> None:
        """Test that whitespace-only queries return 0."""
        detector = FastHeuristicDetector()

        score = detector.get_complexity_score("   \n\t  ")

        assert score == 0


class TestDetect:
    """Tests for the detect method."""

    def test_detect_returns_detection_result(self) -> None:
        """Test that detect returns a DetectionResult."""
        detector = FastHeuristicDetector(
            high_threshold=0.8,
            low_threshold=0.2,
        )

        result = detector.detect("simple query")

        assert result is not None
        assert hasattr(result, "should_trigger")
        assert hasattr(result, "confidence")
        assert hasattr(result, "method")

    def test_detect_with_high_score_exceeds_threshold(self) -> None:
        """Test that high scores (> high_threshold) trigger plan mode."""
        detector = FastHeuristicDetector(
            high_threshold=0.5,  # Lower for testing
            low_threshold=0.2,
        )

        # Complex query should exceed threshold
        query = (
            "I need to implement a comprehensive authentication system. "
            "First, I'll create the user model with secure password hashing. "
            "Then, I'll design and implement JWT token generation and validation. "
            "After that, I'll create the login and logout API endpoints. "
            "Finally, I'll add authentication middleware to protect sensitive routes."
        )

        result = detector.detect(query)

        assert result.should_trigger is True
        assert result.confidence >= 0.5
        assert result.method == "heuristic"

    def test_detect_with_low_score_below_threshold(self) -> None:
        """Test that low scores (< low_threshold) do not trigger plan mode."""
        detector = FastHeuristicDetector(
            high_threshold=0.8,
            low_threshold=0.5,  # Higher for testing
        )

        result = detector.detect("simple search")

        assert result.should_trigger is False
        assert result.method == "heuristic"

    def test_detect_with_mid_score_returns_uncertain(self) -> None:
        """Test that mid scores return uncertain result."""
        detector = FastHeuristicDetector(
            high_threshold=0.8,
            low_threshold=0.2,
        )

        # Query that should score in the middle
        query = "Implement user authentication with login"

        result = detector.detect(query)

        # Mid-range scores should still return a result
        # but should_trigger depends on actual score
        assert result is not None
        assert result.method == "heuristic"

    def test_detect_returns_confidence_score(self) -> None:
        """Test that detect includes confidence score."""
        detector = FastHeuristicDetector()

        result = detector.detect("test query")

        assert 0 <= result.confidence <= 1.0


class TestDetectionResult:
    """Tests for DetectionResult dataclass."""

    def test_detection_result_attributes(self) -> None:
        """Test DetectionResult has correct attributes."""
        from src.infrastructure.agent.planning.fast_heuristic_detector import (
            DetectionResult,
        )

        result = DetectionResult(
            should_trigger=True,
            confidence=0.85,
            method="heuristic",
        )

        assert result.should_trigger is True
        assert result.confidence == 0.85
        assert result.method == "heuristic"

    def test_detection_result_equality(self) -> None:
        """Test DetectionResult equality."""
        from src.infrastructure.agent.planning.fast_heuristic_detector import (
            DetectionResult,
        )

        result1 = DetectionResult(
            should_trigger=True,
            confidence=0.85,
            method="heuristic",
        )
        result2 = DetectionResult(
            should_trigger=True,
            confidence=0.85,
            method="heuristic",
        )

        assert result1 == result2


class TestEdgeCases:
    """Tests for edge cases."""

    def test_none_query_returns_zero_score(self) -> None:
        """Test that None query returns zero score."""
        detector = FastHeuristicDetector()

        score = detector.get_complexity_score(None)  # type: ignore

        assert score == 0

    def test_very_long_query_does_not_crash(self) -> None:
        """Test that very long queries are handled gracefully."""
        detector = FastHeuristicDetector()

        # 10,000 character query
        long_query = "a" * 10000

        score = detector.get_complexity_score(long_query)

        assert 0 <= score <= 1.0

    def test_unicode_query_handled(self) -> None:
        """Test that unicode queries are handled."""
        detector = FastHeuristicDetector()

        query = "实现用户认证系统，包括登录和注册功能"

        score = detector.get_complexity_score(query)

        assert 0 <= score <= 1.0

    def test_special_characters_handled(self) -> None:
        """Test that special characters are handled."""
        detector = FastHeuristicDetector()

        query = "Fix bug: @#$%^&*() in the code!"

        score = detector.get_complexity_score(query)

        # Should not crash and return valid score
        assert 0 <= score <= 1.0


class TestCustomThresholds:
    """Tests for custom threshold configuration."""

    def test_custom_high_threshold(self) -> None:
        """Test detector with custom high threshold."""
        detector = FastHeuristicDetector(
            high_threshold=0.95,
            low_threshold=0.1,
        )

        # Query that would normally trigger
        query = "Implement user authentication"

        result = detector.detect(query)

        # With high threshold, should not trigger
        assert result.should_trigger is False

    def test_custom_low_threshold(self) -> None:
        """Test detector with custom low threshold."""
        detector = FastHeuristicDetector(
            high_threshold=0.8,
            low_threshold=0.01,  # Very low
        )

        result = detector.detect("hi")

        # With very low threshold, even simple queries might trigger
        # But "hi" is still very short, so likely won't
        assert result is not None

    def test_default_thresholds(self) -> None:
        """Test that default thresholds are sensible."""
        detector = FastHeuristicDetector()  # Use defaults

        # Check defaults are set
        assert detector.high_threshold == 0.8
        assert detector.low_threshold == 0.2
        assert detector.min_length == 30
