"""Test helper for LLM wrapper testing - patches abstract classes."""

from src.domain.llm_providers.llm_types import LLMClient


def _generate_response_noop(self, *args, **kwargs):
    """No-op implementation of abstract _generate_response method."""
    return {"content": "test response"}


# Patch the abstract method at module import time
LLMClient._generate_response = _generate_response_noop
LLMClient.__abstractmethods__ = set()
