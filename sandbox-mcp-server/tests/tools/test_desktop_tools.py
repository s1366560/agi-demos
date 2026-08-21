"""Unit tests for desktop management MCP tools."""

from types import SimpleNamespace

import pytest

import src.tools.desktop_tools as desktop_tools


def _reset_desktop_managers() -> None:
    """Reset desktop manager globals across legacy and new implementations."""
    if hasattr(desktop_tools, "_desktop_managers"):
        desktop_tools._desktop_managers.clear()
    if hasattr(desktop_tools, "_desktop_manager"):
        desktop_tools._desktop_manager = None


@pytest.fixture(autouse=True)
def _reset_desktop_state():
    """Reset global desktop tool state between tests."""
    _reset_desktop_managers()
    yield
    _reset_desktop_managers()


class TestDesktopTools:
    """Regression tests for desktop tool UX."""

    def test_get_desktop_manager_is_scoped_per_workspace(self):
        """Each workspace should receive its own desktop manager instance."""
        manager_one = desktop_tools.get_desktop_manager("/workspace-one")
        manager_two = desktop_tools.get_desktop_manager("/workspace-two")

        assert manager_one is not manager_two
        assert manager_one.workspace_dir == "/workspace-one"
        assert manager_two.workspace_dir == "/workspace-two"

    @pytest.mark.asyncio
    async def test_start_desktop_reports_existing_running_configuration(self, monkeypatch):
        """Already-running sessions should report the current live configuration."""

        class DummyManager:
            display = ":5"
            resolution = "1280x720"
            port = 6090

            def is_running(self) -> bool:
                return True

            async def start(self) -> None:
                raise AssertionError("start() should not be called when already running")

            def get_status(self):
                return SimpleNamespace(
                    running=True,
                    display=":5",
                    resolution="1280x720",
                    port=6090,
                    kasmvnc_pid=4321,
                    audio_enabled=False,
                    dynamic_resize=True,
                    encoding="webp",
                )

            def get_web_url(self) -> str:
                return "http://localhost:6090"

        dummy = DummyManager()
        monkeypatch.setattr(
            desktop_tools, "get_desktop_manager", lambda _workspace_dir="/workspace": dummy
        )

        result = await desktop_tools.start_desktop(
            _workspace_dir="/workspace-two",
            display=":1",
            resolution="1920x1080",
            port=6080,
        )

        assert result["success"] is True
        assert "already running" in result["message"].lower()
        assert "http://localhost:6090" in result["message"]
        assert result["display"] == ":5"
        assert result["resolution"] == "1280x720"
        assert result["port"] == 6090
        assert result["url"] == "http://localhost:6090"
        assert result["features"] == {
            "dynamic_resize": True,
            "clipboard": True,
            "file_transfer": False,
            "audio": False,
            "encoding": "webp",
        }
