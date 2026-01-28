"""
Integration tests for XFCE Dockerfile migration.

TDD Phase: RED - These tests will fail until we implement XFCE changes.

Tests cover:
1. Dockerfile package verification (XFCE present, GNOME absent)
2. Docker build success
3. Image size reduction
4. XFCE startup functionality
"""

import os
import subprocess
import pytest
from pathlib import Path


class TestXFCEPackages:
    """Test that XFCE packages are correctly specified in Dockerfile."""

    @pytest.fixture
    def dockerfile_path(self) -> Path:
        """Get path to Dockerfile."""
        return Path(__file__).parent.parent.parent / "Dockerfile"

    @pytest.fixture
    def dockerfile_content(self, dockerfile_path: Path) -> str:
        """Read Dockerfile content."""
        return dockerfile_path.read_text()

    def test_xfce_core_packages_present(self, dockerfile_content: str):
        """
        RED TEST: Verify core XFCE packages are in Dockerfile.

        This test will FAIL until we add XFCE packages.
        """
        required_xfce_packages = [
            "xfce4",
            "xfce4-goodies",
            "xfce4-terminal",
            "xfce4-taskmanager",
            "thunar",
        ]

        missing_packages = []
        for package in required_xfce_packages:
            if package not in dockerfile_content:
                missing_packages.append(package)

        assert not missing_packages, \
            f"Missing required XFCE packages: {', '.join(missing_packages)}"

    def test_gnome_packages_removed(self, dockerfile_content: str):
        """
        RED TEST: Verify GNOME packages are NOT in Dockerfile.

        This test will FAIL until we remove GNOME packages.
        """
        gnome_packages_to_remove = [
            "gnome-session",
            "gnome-shell",
            "gnome-terminal",
            "nautilus",
            "gnome-control-center",
            "gnome-system-monitor",
            "gnome-shell-extensions",
            "gnome-settings-daemon",
        ]

        found_gnome_packages = []
        for package in gnome_packages_to_remove:
            if package in dockerfile_content:
                found_gnome_packages.append(package)

        assert not found_gnome_packages, \
            f"Found GNOME packages that should be removed: {', '.join(found_gnome_packages)}"

    def test_xvfb_present(self, dockerfile_content: str):
        """
        RED TEST: Verify Xvfb is present for X11 framebuffer.

        This test will FAIL if we accidentally remove Xvfb.
        """
        assert "xvfb" in dockerfile_content, \
            "Xvfb (X Virtual Frame Buffer) is required for headless operation"

    def test_x11vnc_present(self, dockerfile_content: str):
        """
        RED TEST: Verify x11vnc is present for VNC server.

        This test will FAIL if we accidentally remove x11vnc.
        """
        assert "x11vnc" in dockerfile_content, \
            "x11vnc is required for VNC server functionality"

    def test_novnc_present(self, dockerfile_content: str):
        """
        RED TEST: Verify noVNC is present for web-based VNC client.

        This test will FAIL if we accidentally remove noVNC.
        """
        assert "noVNC" in dockerfile_content, \
            "noVNC is required for web-based VNC client"


class TestDockerBuild:
    """Test Docker image build process."""

    @pytest.fixture
    def docker_image_name(self) -> str:
        """Docker image name for testing."""
        return "sandbox-mcp-server:xfce-test"

    def test_docker_build_succeeds(self, docker_image_name: str):
        """
        RED TEST: Verify Docker image builds successfully with XFCE.

        This test will FAIL until XFCE Dockerfile is correctly configured.
        """
        try:
            result = subprocess.run(
                ["docker", "build", "-t", docker_image_name, "."],
                cwd=Path(__file__).parent.parent.parent,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes
            )

            assert result.returncode == 0, \
                f"Docker build failed: {result.stderr}"

        except subprocess.TimeoutExpired:
            pytest.fail("Docker build timed out after 10 minutes")
        except FileNotFoundError:
            pytest.skip("Docker not installed")

    def test_docker_image_size_reduced(self, docker_image_name: str):
        """
        RED TEST: Verify Docker image size is reduced by >1GB.

        This test will FAIL until we successfully remove GNOME packages.

        Reference: Current GNOME image is ~3GB
        Target: <2GB (1GB+ reduction)
        """
        try:
            # Get image size
            result = subprocess.run(
                ["docker", "images", docker_image_name, "--format", "{{.Size}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                pytest.skip("Docker image not built yet")

            size_str = result.stdout.strip()
            # Parse size (e.g., "2.5GB", "1500MB")
            if "GB" in size_str:
                size_gb = float(size_str.replace("GB", ""))
                assert size_gb < 2.0, \
                    f"Image size {size_gb}GB exceeds target of <2GB"
            elif "MB" in size_str:
                size_mb = float(size_str.replace("MB", ""))
                assert size_mb < 2000, \
                    f"Image size {size_mb}MB exceeds target of <2000MB"

        except FileNotFoundError:
            pytest.skip("Docker not installed")


class TestXFCEStartup:
    """Test XFCE desktop startup in container."""

    @pytest.fixture
    def docker_image_name(self) -> str:
        """Docker image name for testing."""
        return "sandbox-mcp-server:xfce-test"

    @pytest.fixture
    def container_name(self) -> str:
        """Container name for testing."""
        return "xfce-test-container"

    def test_xfce_session_starts(self, docker_image_name: str, container_name: str):
        """
        RED TEST: Verify XFCE session starts correctly.

        This test will FAIL until XFCE is properly configured.

        Test strategy:
        1. Start container in background
        2. Wait for XFCE to initialize
        3. Check for XFCE processes
        4. Clean up container
        """
        try:
            # Start container
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", container_name,
                    "-e", "DESKTOP_ENABLED=true",
                    "-p", "6080:6080",
                    docker_image_name,
                    "/usr/local/bin/sandbox-entrypoint.sh"
                ],
                capture_output=True,
                timeout=30,
            )

            # Wait for XFCE to start
            import time
            time.sleep(10)

            # Check for XFCE processes
            result = subprocess.run(
                ["docker", "exec", container_name, "pgrep", "-f", "xfce4-session"],
                capture_output=True,
                timeout=10,
            )

            assert result.returncode == 0, \
                "XFCE session process not found - desktop may not have started"

            # Check for xfwm4 (window manager)
            result = subprocess.run(
                ["docker", "exec", container_name, "pgrep", "-f", "xfwm4"],
                capture_output=True,
                timeout=10,
            )

            assert result.returncode == 0, \
                "XFWM4 window manager not found"

        except subprocess.TimeoutExpired:
            pytest.fail("Container startup timed out")
        except FileNotFoundError:
            pytest.skip("Docker not installed")
        finally:
            # Clean up container
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
            )

    def test_vnc_server_accessible(self, docker_image_name: str, container_name: str):
        """
        RED TEST: Verify VNC server is accessible.

        This test will FAIL until VNC is properly configured with XFCE.
        """
        try:
            # Start container
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", container_name,
                    "-e", "DESKTOP_ENABLED=true",
                    "-p", "6080:6080",
                    docker_image_name
                ],
                capture_output=True,
                timeout=30,
            )

            # Wait for services to start
            import time
            time.sleep(10)

            # Check if VNC port is listening
            result = subprocess.run(
                ["docker", "exec", container_name, "netstat", "-tlnp"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            # Check for port 6080 (noVNC) or 5900 (VNC)
            assert "6080" in result.stdout or "5900" in result.stdout, \
                "VNC server port not listening"

        except subprocess.TimeoutExpired:
            pytest.fail("Container startup timed out")
        except FileNotFoundError:
            pytest.skip("Docker not installed")
        finally:
            # Clean up container
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
            )


class TestXFCEConfiguration:
    """Test XFCE configuration files."""

    @pytest.fixture
    def docker_image_name(self) -> str:
        """Docker image name for testing."""
        return "sandbox-mcp-server:xfce-test"

    @pytest.fixture
    def container_name(self) -> str:
        """Container name for testing."""
        return "xfce-test-container"

    def test_xfce_config_directory_exists(self, docker_image_name: str, container_name: str):
        """
        RED TEST: Verify XFCE configuration directory exists.

        This test will FAIL until we create XFCE configuration.
        """
        try:
            # Start container
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", container_name,
                    docker_image_name,
                    "sleep", "30"
                ],
                capture_output=True,
                timeout=30,
            )

            # Check for XFCE config directory
            result = subprocess.run(
                ["docker", "exec", container_name, "test", "-d", "/etc/xdg/xfce4"],
                capture_output=True,
                timeout=10,
            )

            assert result.returncode == 0, \
                "XFCE configuration directory /etc/xdg/xfce4 does not exist"

        except subprocess.TimeoutExpired:
            pytest.fail("Container startup timed out")
        except FileNotFoundError:
            pytest.skip("Docker not installed")
        finally:
            # Clean up container
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
            )

    def test_xfce_autostart_configured(self, docker_image_name: str, container_name: str):
        """
        RED TEST: Verify XFCE autostart applications are configured.

        This test will FAIL until we configure XFCE autostart.
        """
        try:
            # Start container
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", container_name,
                    docker_image_name,
                    "sleep", "30"
                ],
                capture_output=True,
                timeout=30,
            )

            # Check for autostart directory
            result = subprocess.run(
                ["docker", "exec", container_name, "test", "-d",
                 "/etc/xdg/autostart"],
                capture_output=True,
                timeout=10,
            )

            # Autostart may be in /etc/xdg/autostart or /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/
            result2 = subprocess.run(
                ["docker", "exec", container_name, "ls", "/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/"],
                capture_output=True,
                timeout=10,
            )

            assert result.returncode == 0 or result2.returncode == 0, \
                "XFCE autostart configuration not found"

        except subprocess.TimeoutExpired:
            pytest.fail("Container startup timed out")
        except FileNotFoundError:
            pytest.skip("Docker not installed")
        finally:
            # Clean up container
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
            )
