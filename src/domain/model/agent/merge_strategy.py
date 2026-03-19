"""Merge strategy enum for session fork/merge semantics."""

from __future__ import annotations

from enum import Enum


class MergeStrategy(str, Enum):
    """Strategy for merging SubAgent session results back to parent.

    RESULT_ONLY: merge only the final frozen result text (default).
    FULL_HISTORY: merge the complete child conversation history.
    SUMMARY: merge an LLM-generated summary of the child session.
    """

    RESULT_ONLY = "result_only"
    FULL_HISTORY = "full_history"
    SUMMARY = "summary"
