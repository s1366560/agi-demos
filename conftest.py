"""
Global pytest configuration and fixtures.
"""

import os
import sys
from pathlib import Path

import pytest

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def test_config():
    """Provide test configuration."""
    return {
        "neo4j_uri": os.getenv("TEST_NEO4J_URI", "bolt://localhost:7687"),
        "neo4j_user": os.getenv("TEST_NEO4J_USER", "neo4j"),
        "neo4j_password": os.getenv("TEST_NEO4J_PASSWORD", "testpassword"),
        "redis_url": os.getenv("TEST_REDIS_URL", "redis://localhost:6379"),
        "postgres_url": os.getenv("TEST_POSTGRES_URL", "postgresql://localhost/memstack_test"),
        "secret_key": "test-secret-key-for-testing-only",
    }


@pytest.fixture
def mock_env(monkeypatch, test_config):
    """Set up mock environment variables for testing."""
    monkeypatch.setenv("NEO4J_URI", test_config["neo4j_uri"])
    monkeypatch.setenv("NEO4J_USER", test_config["neo4j_user"])
    monkeypatch.setenv("NEO4J_PASSWORD", test_config["neo4j_password"])
    monkeypatch.setenv("REDIS_URL", test_config["redis_url"])
    monkeypatch.setenv("SECRET_KEY", test_config["secret_key"])
    monkeypatch.setenv("ENVIRONMENT", "test")
