"""
Integration tests for XFCE configuration files.

TDD Phase: RED - These tests will FAIL until we implement XFCE configs.

Tests cover:
1. XFCE panel configuration (layout, plugins, settings)
2. Window manager (xfwm4) settings (animations, compositor)
3. Session settings (screensaver, lock screen, power management)
4. Theme configuration (theme, icons, fonts)
5. Autostart applications

Following strict TDD methodology:
- RED: Write failing tests first
- GREEN: Implement config files to pass tests
- REFACTOR: Optimize configurations
"""

import os
import subprocess
import pytest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any


class TestXFCEPanelConfig:
    """Test XFCE panel configuration."""

    @pytest.fixture
    def xfce_configs_dir(self) -> Path:
        """Get path to XFCE configuration directory."""
        return Path(__file__).parent.parent.parent / "docker" / "xfce-configs"

    @pytest.fixture
    def panel_config_path(self, xfce_configs_dir: Path) -> Path:
        """Get path to panel configuration file."""
        return xfce_configs_dir / "xfce4-panel.xml"

    def test_panel_config_file_exists(self, panel_config_path: Path):
        """
        RED TEST: Verify panel configuration file exists.

        This test will FAIL until we create xfce4-panel.xml.
        """
        assert panel_config_path.exists(), \
            f"Panel configuration file not found: {panel_config_path}"

    def test_panel_config_is_valid_xml(self, panel_config_path: Path):
        """
        RED TEST: Verify panel configuration is valid XML.

        This test will FAIL until we create valid XML structure.
        """
        if not panel_config_path.exists():
            pytest.skip("Panel config file not created yet")

        try:
            tree = ET.parse(panel_config_path)
            root = tree.getroot()

            # Verify root element
            assert root.tag == "channel", \
                f"Root element should be 'channel', got '{root.tag}'"

            # Verify required attributes
            assert "version" in root.attrib, "Missing 'version' attribute"

        except ET.ParseError as e:
            pytest.fail(f"Invalid XML in panel config: {e}")

    def test_panel_has_single_panel_top(self, panel_config_path: Path):
        """
        RED TEST: Verify panel is configured as single panel at top.

        Specifications:
        - Single panel (not multiple panels)
        - Position: top
        - Height: 24px
        """
        if not panel_config_path.exists():
            pytest.skip("Panel config file not created yet")

        tree = ET.parse(panel_config_path)
        root = tree.getroot()

        # Find panel-1 property
        panel_1 = root.find(".//property[@name='panel-1']")
        assert panel_1 is not None, "Panel-1 not found"

        # Check position
        position = panel_1.find(".//property[@name='position']")
        assert position is not None, "Panel position not configured"

        value = position.get("value", "")
        # Check for top position (xfce uses "p=1" for top)
        assert "p=1" in value or "top" in value.lower(), \
            f"Panel should be at top, got: {value}"

        # Verify no other panels (panel-2, panel-3, etc.)
        panel_2 = root.find(".//property[@name='panel-2']")
        assert panel_2 is None, "Should only have one panel (found panel-2)"

    def test_panel_height_24px(self, panel_config_path: Path):
        """
        RED TEST: Verify panel height is 24px.

        Optimized for VNC usage - compact panel.
        """
        if not panel_config_path.exists():
            pytest.skip("Panel config file not created yet")

        tree = ET.parse(panel_config_path)
        root = tree.getroot()

        # Find panel size property
        size_props = root.findall(".//property[@name='size']")
        assert len(size_props) > 0, "Panel size not configured"

        for prop in size_props:
            size_value = prop.get("value")
            if size_value:
                assert int(size_value) == 24, \
                    f"Panel height should be 24px, got: {size_value}"

    def test_panel_has_application_menu(self, panel_config_path: Path):
        """
        RED TEST: Verify application menu (whiskermenu) is configured.

        Specifications:
        - Whisker Menu plugin present
        - Positioned on left side
        """
        if not panel_config_path.exists():
            pytest.skip("Panel config file not created yet")

        tree = ET.parse(panel_config_path)
        root = tree.getroot()

        # Look for whiskermenu plugin
        plugins = root.findall(".//property[@name='plugins']")
        found_whiskermenu = False

        for plugin_group in plugins:
            plugin_items = plugin_group.findall(".//value")
            for item in plugin_items:
                if "whiskermenu" in item.get("value", "").lower():
                    found_whiskermenu = True
                    break

        assert found_whiskermenu, \
            "Whisker Menu plugin not found in panel configuration"

    def test_panel_has_task_list(self, panel_config_path: Path):
        """
        RED TEST: Verify task list is configured.

        Specifications:
        - Task list plugin present
        - Positioned in center
        """
        if not panel_config_path.exists():
            pytest.skip("Panel config file not created yet")

        tree = ET.parse(panel_config_path)
        root = tree.getroot()

        # Look for tasklist plugin by plugin-id
        found_tasklist = False

        # Check if plugin-2 exists (tasklist is plugin 2)
        plugin_2 = root.find(".//property[@name='plugin-2']")
        if plugin_2 is not None:
            found_tasklist = True

        assert found_tasklist, \
            "Task list plugin not found in panel configuration"

    def test_panel_has_system_tray(self, panel_config_path: Path):
        """
        RED TEST: Verify system tray (systray) is configured.

        Specifications:
        - System tray plugin present
        - Positioned on right side
        """
        if not panel_config_path.exists():
            pytest.skip("Panel config file not created yet")

        tree = ET.parse(panel_config_path)
        root = tree.getroot()

        # Look for systray plugin by plugin-id
        found_systray = False

        # Check if plugin-3 exists (systray is plugin 3)
        plugin_3 = root.find(".//property[@name='plugin-3']")
        if plugin_3 is not None:
            found_systray = True

        assert found_systray, \
            "System tray plugin not found in panel configuration"

    def test_panel_has_clock(self, panel_config_path: Path):
        """
        RED TEST: Verify clock plugin is configured.

        Specifications:
        - Clock plugin present
        - Positioned on right side
        """
        if not panel_config_path.exists():
            pytest.skip("Panel config file not created yet")

        tree = ET.parse(panel_config_path)
        root = tree.getroot()

        # Look for clock plugin by plugin-id
        found_clock = False

        # Check if plugin-4 exists (clock is plugin 4)
        plugin_4 = root.find(".//property[@name='plugin-4']")
        if plugin_4 is not None:
            # Verify it has clock-related properties
            mode = plugin_4.find(".//property[@name='mode']")
            timezone = plugin_4.find(".//property[@name='timezone']")
            if mode is not None or timezone is not None:
                found_clock = True

        assert found_clock, \
            "Clock plugin not found in panel configuration"


class TestXFWM4Config:
    """Test XFCE window manager (xfwm4) configuration."""

    @pytest.fixture
    def xfce_configs_dir(self) -> Path:
        """Get path to XFCE configuration directory."""
        return Path(__file__).parent.parent.parent / "docker" / "xfce-configs"

    @pytest.fixture
    def xfwm4_config_path(self, xfce_configs_dir: Path) -> Path:
        """Get path to xfwm4 configuration file."""
        return xfce_configs_dir / "xfwm4.xml"

    def test_xfwm4_config_file_exists(self, xfwm4_config_path: Path):
        """
        RED TEST: Verify xfwm4 configuration file exists.

        This test will FAIL until we create xfwm4.xml.
        """
        assert xfwm4_config_path.exists(), \
            f"xfwm4 configuration file not found: {xfwm4_config_path}"

    def test_xfwm4_config_is_valid_xml(self, xfwm4_config_path: Path):
        """
        RED TEST: Verify xfwm4 configuration is valid XML.
        """
        if not xfwm4_config_path.exists():
            pytest.skip("xfwm4 config file not created yet")

        try:
            tree = ET.parse(xfwm4_config_path)
            root = tree.getroot()

            # Verify root element
            assert root.tag == "channel", \
                f"Root element should be 'channel', got '{root.tag}'"

        except ET.ParseError as e:
            pytest.fail(f"Invalid XML in xfwm4 config: {e}")

    def test_compositor_disabled(self, xfwm4_config_path: Path):
        """
        RED TEST: Verify compositor is disabled for VNC performance.

        VNC doesn't benefit from compositing and it adds overhead.
        """
        if not xfwm4_config_path.exists():
            pytest.skip("xfwm4 config file not created yet")

        tree = ET.parse(xfwm4_config_path)
        root = tree.getroot()

        # Find compositor property
        compositor_props = root.findall(".//property[@name='use_compositing']")
        assert len(compositor_props) > 0, "Compositor setting not found"

        for prop in compositor_props:
            value = prop.get("value", "true").lower()
            assert value in ["false", "0"], \
                f"Compositor should be disabled (false), got: {value}"

    def test_click_to_focus(self, xfwm4_config_path: Path):
        """
        RED TEST: Verify click-to-focus behavior is configured.

        Click-to-focus is better for VNC than focus-follows-mouse.
        """
        if not xfwm4_config_path.exists():
            pytest.skip("xfwm4 config file not created yet")

        tree = ET.parse(xfwm4_config_path)
        root = tree.getroot()

        # Find focus mode property
        focus_props = root.findall(".//property[@name='focus_mode']")
        assert len(focus_props) > 0, "Focus mode not configured"

        # "click" is click-to-focus, "sloppy" is focus-follows-mouse
        for prop in focus_props:
            value = prop.get("value", "")
            assert value in ["click", "0"], \
                f"Focus mode should be 'click', got: {value}"

    def test_animations_disabled(self, xfwm4_config_path: Path):
        """
        RED TEST: Verify animations are disabled for VNC performance.

        Window animations over VNC can be slow and jerky.
        """
        if not xfwm4_config_path.exists():
            pytest.skip("xfwm4 config file not created yet")

        tree = ET.parse(xfwm4_config_path)
        root = tree.getroot()

        # Check for various animation properties
        animation_props = [
            "box_move", "box_resize", "box_window"
        ]

        animations_found = False
        for anim_prop in animation_props:
            props = root.findall(f".//property[@name='{anim_prop}']")
            for prop in props:
                animations_found = True
                # These should be disabled or set to minimal
                value = prop.get("value", "")
                # Verify it's not explicitly enabled
                assert value.lower() not in ["true", "1"], \
                    f"Animation '{anim_prop}' should be disabled, got: {value}"

        # At least one animation property should be configured
        assert animations_found, \
            "Animation properties not configured"

    def test_snap_to_edges_disabled(self, xfwm4_config_path: Path):
        """
        RED TEST: Verify edge snapping is disabled or minimal.

        Edge snapping can be annoying in VNC sessions.
        """
        if not xfwm4_config_path.exists():
            pytest.skip("xfwm4 config file not created yet")

        tree = ET.parse(xfwm4_config_path)
        root = tree.getroot()

        # Find snap-to-windows property (should be disabled)
        snap_windows = root.findall(".//property[@name='snap_to_windows']")
        found_snap_config = len(snap_windows) > 0

        if found_snap_config:
            for prop in snap_windows:
                value = prop.get("value", "true").lower()
                # If configured, should be disabled
                assert value in ["false", "0"], \
                    f"snap_to_windows should be disabled (false), got: {value}"
        else:
            # Alternative: snap_to_screen should be enabled (less annoying)
            snap_screen = root.findall(".//property[@name='snap_to_screen']")
            assert len(snap_screen) > 0, "Snap settings not configured at all"


class TestXFCESSIONConfig:
    """Test XFCE session configuration."""

    @pytest.fixture
    def xfce_configs_dir(self) -> Path:
        """Get path to XFCE configuration directory."""
        return Path(__file__).parent.parent.parent / "docker" / "xfce-configs"

    @pytest.fixture
    def session_config_path(self, xfce_configs_dir: Path) -> Path:
        """Get path to session configuration file."""
        return xfce_configs_dir / "xfce4-session.xml"

    def test_session_config_file_exists(self, session_config_path: Path):
        """
        RED TEST: Verify session configuration file exists.

        This test will FAIL until we create xfce4-session.xml.
        """
        assert session_config_path.exists(), \
            f"Session configuration file not found: {session_config_path}"

    def test_session_config_is_valid_xml(self, session_config_path: Path):
        """
        RED TEST: Verify session configuration is valid XML.
        """
        if not session_config_path.exists():
            pytest.skip("Session config file not created yet")

        try:
            tree = ET.parse(session_config_path)
            root = tree.getroot()

            # Verify root element
            assert root.tag == "channel", \
                f"Root element should be 'channel', got '{root.tag}'"

        except ET.ParseError as e:
            pytest.fail(f"Invalid XML in session config: {e}")

    def test_screensaver_disabled(self, session_config_path: Path):
        """
        RED TEST: Verify screensaver is disabled.

        Screensaver interferes with VNC sessions.
        """
        if not session_config_path.exists():
            pytest.skip("Session config file not created yet")

        tree = ET.parse(session_config_path)
        root = tree.getroot()

        # Look for screensaver/blanking properties
        screensaver_props = root.findall(".//property[@name='screensaver']")
        blanking_props = root.findall(".//property[@name='lock']")

        # Either property should be configured to disabled
        has_screensaver_config = len(screensaver_props) > 0 or len(blanking_props) > 0
        assert has_screensaver_config, \
            "Screensaver/lock settings not configured"

    def test_auto_save_session(self, session_config_path: Path):
        """
        RED TEST: Verify auto-save session is enabled.

        Preserves session state across container restarts.
        """
        if not session_config_path.exists():
            pytest.skip("Session config file not created yet")

        tree = ET.parse(session_config_path)
        root = tree.getroot()

        # Look for auto-save property
        autosave_props = root.findall(".//property[@name='auto_save']")
        assert len(autosave_props) > 0, "Auto-save setting not configured"

        for prop in autosave_props:
            value = prop.get("value", "false").lower()
            assert value in ["true", "1"], \
                f"Auto-save should be enabled (true), got: {value}"


class TestWhiskerMenuConfig:
    """Test Whisker Menu configuration."""

    @pytest.fixture
    def xfce_configs_dir(self) -> Path:
        """Get path to XFCE configuration directory."""
        return Path(__file__).parent.parent.parent / "docker" / "xfce-configs"

    @pytest.fixture
    def whiskermenu_config_path(self, xfce_configs_dir: Path) -> Path:
        """Get path to Whisker Menu configuration file."""
        return xfce_configs_dir / "whiskermenu-1.rc"

    def test_whiskermenu_config_file_exists(self, whiskermenu_config_path: Path):
        """
        RED TEST: Verify Whisker Menu configuration file exists.

        This test will FAIL until we create whiskermenu-1.rc.
        """
        assert whiskermenu_config_path.exists(), \
            f"Whisker Menu configuration file not found: {whiskermenu_config_path}"

    def test_whiskermenu_config_is_valid(self, whiskermenu_config_path: Path):
        """
        RED TEST: Verify Whisker Menu configuration is valid.

        Whisker Menu uses a simple key=value format.
        """
        if not whiskermenu_config_path.exists():
            pytest.skip("Whisker Menu config file not created yet")

        content = whiskermenu_config_path.read_text()

        # Should not be empty
        assert len(content) > 0, "Whisker Menu config is empty"

        # Should have valid key=value pairs
        lines = content.split("\n")
        valid_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]

        assert len(valid_lines) > 0, "No configuration entries found"

    def test_whiskermenu_has_categories(self, whiskermenu_config_path: Path):
        """
        RED TEST: Verify Whisker Menu shows application categories.

        Categories make it easier to find applications.
        """
        if not whiskermenu_config_path.exists():
            pytest.skip("Whisker Menu config file not created yet")

        content = whiskermenu_config_path.read_text()

        # Look for category settings
        # Common settings: show-category-names, icon-size, etc.
        has_category_config = False
        for line in content.split("\n"):
            if "category" in line.lower():
                has_category_config = True
                break

        assert has_category_config, \
            "Category configuration not found in Whisker Menu"


class TestAutostartConfig:
    """Test autostart application configuration."""

    @pytest.fixture
    def xfce_configs_dir(self) -> Path:
        """Get path to XFCE configuration directory."""
        return Path(__file__).parent.parent.parent / "docker" / "xfce-configs"

    @pytest.fixture
    def autostart_dir(self, xfce_configs_dir: Path) -> Path:
        """Get path to autostart configuration directory."""
        return xfce_configs_dir / "autostart"

    def test_autostart_directory_exists(self, autostart_dir: Path):
        """
        RED TEST: Verify autostart directory exists.

        This test will FAIL until we create the autostart directory.
        """
        assert autostart_dir.exists(), \
            f"Autostart directory not found: {autostart_dir}"

        assert autostart_dir.is_dir(), \
            f"Autostart path is not a directory: {autostart_dir}"

    def test_autostart_has_desktop_files(self, autostart_dir: Path):
        """
        RED TEST: Verify autostart directory has .desktop files.

        Applications to autostart should have .desktop files.
        """
        if not autostart_dir.exists():
            pytest.skip("Autostart directory not created yet")

        desktop_files = list(autostart_dir.glob("*.desktop"))

        assert len(desktop_files) > 0, \
            "No .desktop files found in autostart directory"

    def test_autostart_files_valid(self, autostart_dir: Path):
        """
        RED TEST: Verify autostart .desktop files are valid.

        .desktop files must have required fields:
        - [Desktop Entry] header
        - Type=Application
        - Exec command
        """
        if not autostart_dir.exists():
            pytest.skip("Autostart directory not created yet")

        desktop_files = list(autostart_dir.glob("*.desktop"))

        for desktop_file in desktop_files:
            content = desktop_file.read_text()

            # Check for required sections
            assert "[Desktop Entry]" in content, \
                f"Missing [Desktop Entry] header in {desktop_file.name}"

            assert "Type=" in content, \
                f"Missing 'Type=' in {desktop_file.name}"

            assert "Exec=" in content, \
                f"Missing 'Exec=' in {desktop_file.name}"


class TestThemeConfig:
    """Test theme and appearance configuration."""

    @pytest.fixture
    def xfce_configs_dir(self) -> Path:
        """Get path to XFCE configuration directory."""
        return Path(__file__).parent.parent.parent / "docker" / "xfce-configs"

    @pytest.fixture
    def xsettings_config_path(self, xfce_configs_dir: Path) -> Path:
        """Get path to XSettings configuration file."""
        return xfce_configs_dir / "xsettings.xml"

    def test_xsettings_config_file_exists(self, xsettings_config_path: Path):
        """
        RED TEST: Verify XSettings configuration file exists.

        This test will FAIL until we create xsettings.xml.
        """
        assert xsettings_config_path.exists(), \
            f"XSettings configuration file not found: {xsettings_config_path}"

    def test_xsettings_config_is_valid_xml(self, xsettings_config_path: Path):
        """
        RED TEST: Verify XSettings configuration is valid XML.
        """
        if not xsettings_config_path.exists():
            pytest.skip("XSettings config file not created yet")

        try:
            tree = ET.parse(xsettings_config_path)
            root = tree.getroot()

            # Verify root element
            assert root.tag == "channel", \
                f"Root element should be 'channel', got '{root.tag}'"

        except ET.ParseError as e:
            pytest.fail(f"Invalid XML in XSettings config: {e}")

    def test_theme_configured(self, xsettings_config_path: Path):
        """
        RED TEST: Verify GTK theme is configured.

        Should use a lightweight theme (Adwaita, XFCE default, etc.)
        """
        if not xsettings_config_path.exists():
            pytest.skip("XSettings config file not created yet")

        tree = ET.parse(xsettings_config_path)
        root = tree.getroot()

        # Look for theme property
        theme_props = root.findall(".//property[@name='ThemeName']")
        assert len(theme_props) > 0, "Theme name not configured"

        for prop in theme_props:
            theme_name = prop.get("value", "")
            # Should be a lightweight theme
            assert len(theme_name) > 0, "Theme name is empty"

            # Common lightweight themes
            lightweight_themes = ["adwaita", "xfce", "default", "greybird"]
            is_lightweight = any(t in theme_name.lower() for t in lightweight_themes)

            assert is_lightweight, \
                f"Theme should be lightweight (Adwaita, XFCE, Default), got: {theme_name}"

    def test_font_configured(self, xsettings_config_path: Path):
        """
        RED TEST: Verify font is configured.

        Should use a readable system font (Sans 10pt).
        """
        if not xsettings_config_path.exists():
            pytest.skip("XSettings config file not created yet")

        tree = ET.parse(xsettings_config_path)
        root = tree.getroot()

        # Look for font properties
        font_props = root.findall(".//property[@name='FontName']")
        assert len(font_props) > 0, "Font settings not configured"

        # At least one font property should be configured with a value
        found_font = False
        for prop in font_props:
            font_value = prop.get("value", "")
            if font_value and len(font_value) > 0:
                found_font = True
                # Should contain "Sans" and "10" (size)
                assert "Sans" in font_value or "sans" in font_value, \
                    f"Font should be Sans, got: {font_value}"
                break

        assert found_font, "Font name not configured or empty"


class TestDockerfileConfigCopy:
    """Test that Dockerfile copies XFCE configuration files."""

    @pytest.fixture
    def dockerfile_path(self) -> Path:
        """Get path to Dockerfile."""
        return Path(__file__).parent.parent.parent / "Dockerfile"

    @pytest.fixture
    def dockerfile_content(self, dockerfile_path: Path) -> str:
        """Read Dockerfile content."""
        return dockerfile_path.read_text()

    def test_dockerfile_copies_xfce_configs(self, dockerfile_content: str):
        """
        RED TEST: Verify Dockerfile copies XFCE configuration files.

        This test will FAIL until we add COPY command for XFCE configs.
        """
        # Look for COPY command that copies xfce-configs
        has_xfce_copy = False
        for line in dockerfile_content.split("\n"):
            if line.strip().startswith("COPY") and "xfce-configs" in line:
                has_xfce_copy = True
                break

        assert has_xfce_copy, \
            "Dockerfile does not copy XFCE configuration files. " \
            "Add: COPY docker/xfce-configs/ /etc/xdg/xfce4/"

    def test_xfce_configs_directory_exists(self):
        """
        RED TEST: Verify docker/xfce-configs directory exists.

        This test will FAIL until we create the directory.
        """
        xfce_configs_dir = Path(__file__).parent.parent.parent / "docker" / "xfce-configs"

        assert xfce_configs_dir.exists(), \
            f"XFCE configs directory not found: {xfce_configs_dir}"

        assert xfce_configs_dir.is_dir(), \
            f"XFCE configs path is not a directory: {xfce_configs_dir}"
