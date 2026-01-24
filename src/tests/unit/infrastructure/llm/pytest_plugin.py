"""Pytest plugin to patch abstract base classes for LLM wrapper tests."""

import pytest


@pytest.fixture(autouse=True, scope="session")
def patch_llm_abstract_classes():
    """Patch LLM abstract base classes before any tests run."""
    from src.domain.llm_providers.llm_types import LLMClient

    # Remove abstract method requirements for testing
    LLMClient.__abstractmethods__ = set()

    yield


def pytest_configure(config):
    """Configure pytest at startup."""
    # Patch abstract classes before test collection
    from src.domain.llm_providers.llm_types import LLMClient

    LLMClient.__abstractmethods__ = set()
