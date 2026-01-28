"""
Simple integration test to verify current state (x11vnc usage).
This test should PASS with current code, confirming RED phase baseline.
"""
import subprocess
import time
import pytest


@pytest.mark.integration
def test_current_uses_x11vnc():
    """
    TEST: Verify current implementation uses x11vnc (baseline for RED phase).

    This test SHOULD PASS with current code.
    After we implement TigerVNC, this test will fail (confirming change).
    """
    # Start container
    result = subprocess.run(
        [
            "docker", "run", "-d", "--name", "test-x11vnc-check",
            "-p", "5901:5901", "-p", "6080:6080", "-p", "8765:8765",
            "sandbox-mcp-server:latest"
        ],
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:
        pytest.skip(f"Failed to start container: {result.stderr}")

    container_id = result.stdout.strip()

    try:
        # Wait for services to start
        time.sleep(40)

        # Get logs
        logs_result = subprocess.run(
            ["docker", "logs", container_id],
            capture_output=True,
            text=True,
            timeout=10
        )

        logs = logs_result.stdout

        # Check for x11vnc usage (current state)
        assert "Starting VNC server (x11vnc)" in logs, \
            "Expected x11vnc startup message not found - code may have changed"

        # Check that x11vnc process is running
        ps_result = subprocess.run(
            ["docker", "exec", container_id, "ps", "aux"],
            capture_output=True,
            text=True,
            timeout=10
        )

        assert "x11vnc" in ps_result.stdout, \
            "x11vnc process not found - unexpected state"

        print("\n✅ RED PHASE CONFIRMED: Current code uses x11vnc")
        print("   This is expected. Next step: Implement TigerVNC.")

    finally:
        # Cleanup
        subprocess.run(
            ["docker", "stop", container_id],
            capture_output=True,
            timeout=30
        )
        subprocess.run(
            ["docker", "rm", container_id],
            capture_output=True,
            timeout=10
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
