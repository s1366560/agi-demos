"""
Pytest configuration and fixtures for integration tests.
"""
import os
import subprocess

import pytest

RED_PHASE_TEST_FILES = {
    "test_e2e_desktop_workflows.py",
    "test_entrypoint_vnc.py",
    "test_entrypoint_vnc_simple.py",
    "test_tigervnc.py",
    "test_vnc_performance.py",
    "test_xfce_config.py",
    "test_xfce_dockerfile.py",
}


def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires Docker)"
    )


def pytest_collection_modifyitems(config, items):
    """Add markers to tests automatically"""
    run_red_tests = os.getenv("RUN_SANDBOX_RED_TESTS") == "1"
    red_skip = pytest.mark.skip(
        reason="sandbox RED-phase desktop tests require RUN_SANDBOX_RED_TESTS=1"
    )

    for item in items:
        # Mark all tests in integration/ as integration tests
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        if not run_red_tests and item.fspath.basename in RED_PHASE_TEST_FILES:
            item.add_marker(red_skip)


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
