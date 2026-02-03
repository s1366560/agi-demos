"""
Plan Mode Detection and Work Plan Generation Components.

This module provides:
1. Hybrid detection strategy for determining when to trigger Plan Mode
2. Work plan generation for ReAct agent execution transparency

Detection Layers:
1. Layer 1: FastHeuristicDetector - Fast heuristic filter
2. Layer 2: LLMClassifier - LLM-based classification for ambiguous cases
3. Layer 3: LLMResponseCache - Cache for LLM results
4. HybridPlanModeDetector - Coordinates all layers

Work Plan Generation:
- WorkPlanGenerator - Generate execution plans based on queries and tools
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
from src.infrastructure.agent.planning.work_plan_generator import (
    WorkPlanGenerator,
    WorkPlan,
    PlanStep,
    QueryAnalysis,
    classify_tool_by_description,
    get_work_plan_generator,
    set_work_plan_generator,
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
    # Work Plan Generator
    "WorkPlanGenerator",
    "WorkPlan",
    "PlanStep",
    "QueryAnalysis",
    "classify_tool_by_description",
    "get_work_plan_generator",
    "set_work_plan_generator",
]
