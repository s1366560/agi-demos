"""
Pytest configuration and fixtures for integration tests.
"""
import pytest
import subprocess
import time


def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires Docker)"
    )


def pytest_collection_modifyitems(config, items):
    """Add markers to tests automatically"""
    for item in items:
        # Mark all tests in integration/ as integration tests
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def docker_available():
    """Check if Docker is available and running"""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            timeout=5
        )
        if result.returncode != 0:
            pytest.skip("Docker not available")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("Docker not installed or not running")


@pytest.fixture(scope="session")
def docker_image_built(docker_available):
    """Check if Docker image exists, skip if not"""
    try:
        result = subprocess.run(
            ["docker", "images", "sandbox-mcp-server"],
            capture_output=True,
            timeout=5
        )
        if "sandbox-mcp-server" not in result.stdout.decode():
            pytest.skip(
                "Docker image 'sandbox-mcp-server' not found. "
                "Run 'make docker-build' first."
            )
        return True
    except subprocess.TimeoutExpired:
        pytest.skip("Docker command timed out")
