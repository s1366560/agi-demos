"""
Plan Mode Detection Components.

This module provides a hybrid detection strategy for determining when
to trigger Plan Mode based on query complexity.

Detection Layers:
1. Layer 1: FastHeuristicDetector - Fast heuristic filter
2. Layer 2: LLMClassifier - LLM-based classification for ambiguous cases
3. Layer 3: LLMResponseCache - Cache for LLM results
4. HybridPlanModeDetector - Coordinates all layers
"""

from src.infrastructure.agent.planning.fast_heuristic_detector import (
    FastHeuristicDetector,
    DetectionResult as HeuristicDetectionResult,
)
from src.infrastructure.agent.planning.llm_classifier import (
    LLMClassifier,
    ClassificationResult,
    ClassificationError,
)
from src.infrastructure.agent.planning.llm_cache import (
    LLMResponseCache,
    CacheEntry,
)
from src.infrastructure.agent.planning.hybrid_plan_mode_detector import (
    HybridPlanModeDetector,
    DetectionResult,
)

__all__ = [
    # Fast Heuristic Detector
    "FastHeuristicDetector",
    "HeuristicDetectionResult",
    # LLM Classifier
    "LLMClassifier",
    "ClassificationResult",
    "ClassificationError",
    # Cache
    "LLMResponseCache",
    "CacheEntry",
    # Hybrid Detector
    "HybridPlanModeDetector",
    "DetectionResult",
]
