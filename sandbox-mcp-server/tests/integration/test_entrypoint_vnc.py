"""
Integration tests for entrypoint.sh VNC server integration.

Tests verify TigerVNC integration with fallback to x11vnc.
Following strict TDD methodology: RED (tests fail) → GREEN (implementation) → REFACTOR.

Test Structure:
- Phase 1: Test TigerVNC is preferred over x11vnc
- Phase 2: Test TigerVNC starts correctly
- Phase 3: Test fallback to x11vnc when TigerVNC unavailable
- Phase 4: Test VNC port responsiveness
"""
import subprocess
import time
import pytest
import os
import signal
from typing import List


class TestEntrypointVNC:
    """Test suite for VNC server integration in entrypoint.sh"""

    @pytest.fixture
    def docker_image(self) -> str:
        """Docker image name for testing"""
        return os.getenv("SANDBOX_DOCKER_IMAGE", "sandbox-mcp-server:latest")

    @pytest.fixture
    def container_name(self) -> str:
        """Generate unique container name for each test"""
        import uuid
        return f"test-vnc-{uuid.uuid4().hex[:8]}"

    def _run_container(self, image: str, name: str, env_vars: dict = None) -> subprocess.Popen:
        """Start a Docker container in detached mode"""
        cmd = ["docker", "run", "--name", name, "-d"]

        # Add environment variables
        if env_vars:
            for key, value in env_vars.items():
                cmd.extend(["-e", f"{key}={value}"])

        # Add ports
        cmd.extend(["-p", "5901:5901"])  # VNC
        cmd.extend(["-p", "6080:6080"])  # noVNC
        cmd.extend(["-p", "8765:8765"])  # MCP

        cmd.append(image)

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start container: {result.stderr}")

        return result.stdout.strip()

    def _stop_container(self, name: str):
        """Stop and remove a container"""
        subprocess.run(["docker", "stop", name], capture_output=True)
        subprocess.run(["docker", "rm", name], capture_output=True)

    def _container_logs(self, name: str) -> str:
        """Get container logs"""
        result = subprocess.run(
            ["docker", "logs", name],
            capture_output=True,
            text=True
        )
        return result.stdout

    def _wait_for_service(self, container_name: str, timeout: int = 30) -> bool:
        """Wait for VNC service to be ready"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            logs = self._container_logs(container_name)
            if "VNC server started on port 5901" in logs:
                return True
            time.sleep(1)
        return False

    @pytest.mark.integration
    def test_entrypoint_starts_tigervnc_not_x11vnc(
        self, docker_image: str, container_name: str
    ):
        """
        TEST: Verify entrypoint.sh prefers TigerVNC over x11vnc.

        Expected Behavior:
        - Container starts with TigerVNC (vncserver command)
        - Logs show "Starting VNC server (TigerVNC)..." or similar
        - No x11vnc process is running
        - vncserver process is running

        Current State (RED Phase):
        - entrypoint.sh uses x11vnc (line 160)
        - Logs show "Starting VNC server (x11vnc)..."
        - x11vnc process is running
        - This test will FAIL until implementation is complete

        TDD Phase: RED ❌
        """
        # Start container
        container_id = self._run_container(docker_image, container_name)

        try:
            # Wait for VNC to start
            ready = self._wait_for_service(container_name, timeout=45)
            assert ready, "VNC service did not start within timeout"

            # Check logs for TigerVNC usage
            logs = self._container_logs(container_name)

            # Test 1: Should NOT find x11vnc startup message
            assert "Starting VNC server (x11vnc)" not in logs, \
                "Found x11vnc startup message - entrypoint.sh still uses x11vnc"

            # Test 2: Should find TigerVNC startup message
            assert (
                "Starting VNC server (TigerVNC)" in logs or
                "Starting VNC server (vncserver)" in logs
            ), "TigerVNC startup message not found in logs"

            # Test 3: Check running processes
            result = subprocess.run(
                ["docker", "exec", container_name, "ps", "aux"],
                capture_output=True,
                text=True
            )
            processes = result.stdout

            # Test 3a: Should NOT find x11vnc process
            assert "x11vnc" not in processes, \
                "x11vnc process is running - should be using TigerVNC"

            # Test 3b: Should find vncserver/Xvnc process
            assert (
                "vncserver" in processes or
                "Xvnc" in processes
            ), "TigerVNC (vncserver/Xvnc) process not found"

        finally:
            self._stop_container(container_name)

    @pytest.mark.integration
    def test_vnc_port_responsive(self, docker_image: str, container_name: str):
        """
        TEST: Verify VNC port 5901 is responsive.

        Expected Behavior:
        - Port 5901 is listening
        - netstat shows :5901 bound
        - VNC handshake possible

        Current State (RED Phase):
        - Port 5901 should be responsive with current x11vnc
        - This test may PASS with x11vnc, but we verify TigerVNC behavior

        TDD Phase: RED ❌ (may pass with x11vnc, but we need TigerVNC)
        """
        container_id = self._run_container(docker_image, container_name)

        try:
            # Wait for VNC to start
            ready = self._wait_for_service(container_name, timeout=45)
            assert ready, "VNC service did not start within timeout"

            # Check if port 5901 is listening
            result = subprocess.run(
                ["docker", "exec", container_name, "netstat", "-tln"],
                capture_output=True,
                text=True
            )

            assert ":5901 " in result.stdout, \
                "Port 5901 is not listening"

            # Additional check: verify it's TigerVNC, not x11vnc
            ps_result = subprocess.run(
                ["docker", "exec", container_name, "ps", "aux"],
                capture_output=True,
                text=True
            )

            assert "x11vnc" not in ps_result.stdout, \
                "Port 5901 is served by x11vnc - should be TigerVNC"

        finally:
            self._stop_container(container_name)

    @pytest.mark.integration
    def test_tigervnc_fallback_to_x11vnc(self, docker_image: str, container_name: str):
        """
        TEST: Verify fallback to x11vnc when TigerVNC is unavailable.

        Expected Behavior:
        - If TigerVNC binary not found, fallback to x11vnc
        - Logs show fallback message
        - x11vnc starts successfully
        - Port 5901 is responsive

        Test Method:
        - Set VNC_SERVER_TYPE=x11vnc to force fallback
        - Verify x11vnc starts
        - Verify logs indicate fallback

        Current State (RED Phase):
        - Fallback mechanism doesn't exist
        - Logs won't show fallback message
        - This test will FAIL until implementation

        TDD Phase: RED ❌
        """
        # Force x11vnc by setting environment variable
        env_vars = {"VNC_SERVER_TYPE": "x11vnc"}
        container_id = self._run_container(docker_image, container_name, env_vars)

        try:
            # Wait for VNC to start
            ready = self._wait_for_service(container_name, timeout=45)
            assert ready, "VNC service did not start within timeout"

            # Check logs for fallback message
            logs = self._container_logs(container_name)

            # Should show fallback indication
            assert (
                "Falling back to x11vnc" in logs or
                "Using x11vnc (forced)" in logs or
                "Starting VNC server (x11vnc)" in logs
            ), "Fallback message not found in logs"

            # Should have x11vnc process running
            result = subprocess.run(
                ["docker", "exec", container_name, "ps", "aux"],
                capture_output=True,
                text=True
            )

            assert "x11vnc" in result.stdout, \
                "x11vnc process not found - fallback failed"

            # Port should still be responsive
            netstat_result = subprocess.run(
                ["docker", "exec", container_name, "netstat", "-tln"],
                capture_output=True,
                text=True
            )

            assert ":5901 " in netstat_result.stdout, \
                "Port 5901 not listening with x11vnc fallback"

        finally:
            self._stop_container(container_name)

    @pytest.mark.integration
    def test_tigervnc_configuration_file(self, docker_image: str, container_name: str):
        """
        TEST: Verify TigerVNC configuration is used.

        Expected Behavior:
        - /home/sandbox/.vnc/config exists (TigerVNC config)
        - Configuration has proper parameters
        - xstartup file is executed

        Current State (RED Phase):
        - entrypoint.sh doesn't create TigerVNC config
        - Only xstartup template exists
        - This test will FAIL until implementation

        TDD Phase: RED ❌
        """
        container_id = self._run_container(docker_image, container_name)

        try:
            # Wait for VNC to start
            ready = self._wait_for_service(container_name, timeout=45)
            assert ready, "VNC service did not start within timeout"

            # Check for TigerVNC config file
            result = subprocess.run(
                ["docker", "exec", container_name, "cat", "/home/sandbox/.vnc/config"],
                capture_output=True,
                text=True
            )

            assert result.returncode == 0, \
                "TigerVNC config file does not exist"

            # Verify config has expected parameters
            config_content = result.stdout
            expected_params = [
                "geometry=1280x720",
                "depth=24",
                "localhost=no",
            ]

            for param in expected_params:
                assert param in config_content, \
                    f"TigerVNC config missing parameter: {param}"

        finally:
            self._stop_container(container_name)

    @pytest.mark.integration
    def test_tigervnc_log_file(self, docker_image: str, container_name: str):
        """
        TEST: Verify TigerVNC creates log file.

        Expected Behavior:
        - /tmp/tigervnc.log exists (or /home/sandbox/.vnc/*.log)
        - Log contains startup information
        - No critical errors in log

        Current State (RED Phase):
        - entrypoint.sh creates /tmp/x11vnc.log (line 167)
        - No TigerVNC log file created
        - This test will FAIL until implementation

        TDD Phase: RED ❌
        """
        container_id = self._run_container(docker_image, container_name)

        try:
            # Wait for VNC to start
            ready = self._wait_for_service(container_name, timeout=45)
            assert ready, "VNC service did not start within timeout"

            # Check for TigerVNC log file
            result = subprocess.run(
                ["docker", "exec", container_name, "ls", "-la", "/tmp/tigervnc.log"],
                capture_output=True,
                text=True
            )

            # TigerVNC log should exist
            assert result.returncode == 0, \
                "TigerVNC log file (/tmp/tigervnc.log) does not exist"

            # Verify log has content
            result = subprocess.run(
                ["docker", "exec", container_name, "cat", "/tmp/tigervnc.log"],
                capture_output=True,
                text=True
            )

            log_content = result.stdout
            assert len(log_content) > 0, \
                "TigerVNC log file is empty"

            # Should not contain critical errors
            assert "error" not in log_content.lower() or \
                   "warning" in log_content.lower(), \
                "TigerVNC log contains critical errors"

        finally:
            self._stop_container(container_name)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
