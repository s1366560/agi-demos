import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
ENTRYPOINT = (ROOT / "scripts" / "entrypoint.sh").read_text()
XSTARTUP = (ROOT / "docker" / "kasmvnc-configs" / "xstartup").read_text()
XFCE_CONFIG_DIR = ROOT / "docker" / "xfce-configs"
XFCE_PANEL = (XFCE_CONFIG_DIR / "xfce4-panel.xml").read_text()
XFCE_DESKTOP = (XFCE_CONFIG_DIR / "xfce4-desktop.xml").read_text()
XFCE_WINDOW_MANAGER = (XFCE_CONFIG_DIR / "xfwm4.xml").read_text()
COMPOSE = (ROOT / "docker-compose.yml").read_text()
SECCOMP_PROFILE = json.loads((ROOT / "docker" / "seccomp-profile.json").read_text())


def final_image_stage() -> str:
    return DOCKERFILE.rsplit("\nFROM ubuntu:24.04\n", maxsplit=1)[1]


def main_body() -> str:
    return ENTRYPOINT.split("main() {", maxsplit=1)[1].split('main "$@"', maxsplit=1)[0]


def test_build_inputs_are_pinned_and_multi_arch() -> None:
    for contract in [
        "ARG RUST_VERSION=1.97.1",
        "ENV RUSTUP_TOOLCHAIN=${RUST_VERSION}",
        'rustc --version | grep -F "rustc ${RUST_VERSION} "',
        "ARG PLAYWRIGHT_VERSION=1.57.0",
        "ARG PNPM_VERSION=11.15.1",
        "ARG KASMVNC_VERSION=1.4.0",
        "ARG TTYD_VERSION=1.7.7",
        "ARG SKY_CUA_COMMIT=9e4d9f0baa04b001631f9c8dd73dab439988524a",
        "resources/chrome-extension/codex/1.2.27221.15725_0",
        "amd64)",
        "arm64)",
    ]:
        assert contract in DOCKERFILE

    assert DOCKERFILE.count("FROM ") >= 6
    assert "cargo build --locked --release" in DOCKERFILE
    assert "-p sky-cua-client" in DOCKERFILE
    assert "-p sky-cua-service" in DOCKERFILE
    assert "-p sky-cua-chrome-host" in DOCKERFILE


def test_pinned_downloads_use_complete_sha256_values() -> None:
    checksum_values = [
        line.split("TTYD_SHA256=", maxsplit=1)[1].split()[0]
        for line in DOCKERFILE.splitlines()
        if "TTYD_SHA256=" in line
    ]

    assert len(checksum_values) == 2
    for checksum in checksum_values:
        assert len(checksum) == 64
        assert all(character in "0123456789abcdef" for character in checksum)


def test_chromium_suid_sandbox_is_restored_after_recursive_permissions() -> None:
    final_stage = final_image_stage()

    recursive_permissions = final_stage.index("chmod -R a+rX")
    suid_permissions = final_stage.rindex('chmod 4755 "${sandbox_path}"')

    assert recursive_permissions < suid_permissions


def test_final_image_contains_only_runtime_payloads() -> None:
    final_stage = final_image_stage().lower()
    for removed in [
        "build-essential",
        "cargo ",
        "firefox",
        "golang-go",
        "kde-plasma",
        "libreoffice",
        "openbox",
        "openjdk",
        "pandoc",
        "puppeteer",
        "rustc",
    ]:
        assert removed not in final_stage

    assert "copy --from=sky-cua-builder /out/ /opt/sky-cua/" in final_stage
    assert "copy --from=python-runtime /opt/sandbox-mcp-venv" in final_stage
    assert "copy . /app" not in final_stage
    assert "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" in final_stage
    assert "user sandbox" in final_stage


def test_chromium_and_desktop_runtime_dependencies_are_explicit() -> None:
    for dependency in [
        "at-spi2-core",
        "dbus-x11",
        "gstreamer1.0-plugins-base",
        "gstreamer1.0-plugins-good",
        "gstreamer1.0-tools",
        "gstreamer1.0-x",
        "adwaita-icon-theme",
        "greybird-gtk-theme",
        "thunar",
        "xfce4-panel",
        "xfce4-session",
        "xfce4-settings",
        "xfce4-terminal",
        "xfdesktop4",
        "xfwm4",
        "x11-utils",
        "x11-xserver-utils",
        "xauth",
        "xdotool",
        "wmctrl",
    ]:
        assert dependency in final_image_stage()

    assert 'playwright@${PLAYWRIGHT_VERSION}" install chromium' in DOCKERFILE
    assert "install chromium firefox" not in DOCKERFILE
    assert "install chromium webkit" not in DOCKERFILE
    assert "--disable-dev-shm-usage" not in DOCKERFILE
    assert "--disable-dev-shm-usage" not in ENTRYPOINT
    assert "shm_size: ${SANDBOX_SHM_SIZE:-1g}" in COMPOSE


def test_compose_exposes_authenticated_gui_and_persists_browser_state() -> None:
    assert '"${SANDBOX_DESKTOP_BIND_ADDRESS:-127.0.0.1}:' in COMPOSE
    assert '${SANDBOX_DESKTOP_PORT:-6080}:6080"' in COMPOSE
    assert '"${SANDBOX_TERMINAL_BIND_ADDRESS:-127.0.0.1}:' in COMPOSE
    assert '${SANDBOX_TERMINAL_PORT:-7681}:7681"' in COMPOSE
    assert "SANDBOX_SERVICE_AUTH_TOKEN: ${SANDBOX_SERVICE_AUTH_TOKEN:?" in COMPOSE
    assert "MCP_STATIC_TOKEN: ${SANDBOX_SERVICE_AUTH_TOKEN:?" in COMPOSE
    assert "cap_drop:" in COMPOSE
    assert "- ALL" in COMPOSE
    assert "sandbox-chromium:/home/sandbox/.config/chromium" in COMPOSE
    assert "sandbox-chromium:" in COMPOSE
    assert "healthcheck:" not in COMPOSE
    assert "--start-period=60s" in DOCKERFILE


def test_shared_graphical_environment_is_baked_into_the_image() -> None:
    for assignment in [
        "HOME=/home/sandbox",
        "DISPLAY=:1",
        "XAUTHORITY=/home/sandbox/.Xauthority",
        "XDG_SESSION_TYPE=x11",
        "XDG_CURRENT_DESKTOP=XFCE",
        "DESKTOP_SESSION=xfce",
        "XDG_RUNTIME_DIR=/run/user/10001",
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/10001/bus",
        "SKY_CUA_SERVICE_PATH=/opt/sky-cua/bin/sky-cua-service",
        "SKY_CUA_SURFACES=desktop,browser",
        "SKY_CUA_BROWSER=chromium",
        "SKY_CUA_INPUT_BACKEND=x11",
        "SKY_CUA_ISOLATED_DESKTOP=0",
        "SKY_CUA_PHONE=0",
        "SKY_CUA_AGENT_CURSOR=0",
        "SKY_CUA_SCREENSHOT_CURSOR=0",
    ]:
        assert assignment in DOCKERFILE


def test_entrypoint_orders_the_session_before_mcp_and_terminal() -> None:
    body = main_body()
    ordered_calls = [
        "prepare_session_directories",
        "start_session_dbus",
        "activate_at_spi",
        "start_kasmvnc",
        "wait_for_x11_session",
        "install_chromium_native_host",
        "start_chromium",
        "start_mcp_server",
        "start_ttyd",
    ]
    positions = [body.index(call) for call in ordered_calls]
    assert positions == sorted(positions)

    assert "org.a11y.Bus.GetAddress" in ENTRYPOINT
    assert "XTEST" in ENTRYPOINT
    assert "MIT-SHM" in ENTRYPOINT
    assert "_NET_SUPPORTING_WM_CHECK" in ENTRYPOINT
    assert "Name: Xfwm4" in ENTRYPOINT
    assert "pgrep -x xfce4-panel" in ENTRYPOINT
    assert "pgrep -x xfdesktop" in ENTRYPOINT
    assert "extension-*.sock" in ENTRYPOINT


def test_entrypoint_enables_toolkit_accessibility_before_chromium() -> None:
    accessibility_setting = "gsettings set org.gnome.desktop.interface toolkit-accessibility true"

    assert accessibility_setting in ENTRYPOINT
    assert ENTRYPOINT.index(accessibility_setting) < ENTRYPOINT.index("start_chromium()")


def test_kasmvnc_keeps_basic_auth_enabled() -> None:
    assert "vncpasswd \\" in ENTRYPOINT
    assert '-u "${SERVICE_AUTH_USERNAME}"' in ENTRYPOINT
    assert '-KasmPasswordFile "${HOME}/.kasmpasswd"' in ENTRYPOINT
    assert "-DisableBasicAuth" not in ENTRYPOINT
    assert "-disableBasicAuth" not in ENTRYPOINT


def test_container_runtime_allows_chromium_user_namespaces() -> None:
    assert "seccomp=./docker/seccomp-profile.json" in COMPOSE
    assert SECCOMP_PROFILE["defaultAction"] == "SCMP_ACT_ERRNO"
    assert {"SCMP_ARCH_X86_64", "SCMP_ARCH_AARCH64"} <= set(SECCOMP_PROFILE["architectures"])
    allowed = {
        name
        for rule in SECCOMP_PROFILE["syscalls"]
        if rule["action"] == "SCMP_ACT_ALLOW"
        for name in rule["names"]
    }
    assert {"clone", "setns", "unshare"} <= allowed


def test_container_runtime_allows_x11_mit_shm_capture() -> None:
    allowed = {
        name
        for rule in SECCOMP_PROFILE["syscalls"]
        if rule["action"] == "SCMP_ACT_ALLOW"
        for name in rule["names"]
    }

    assert {"shmget", "shmat", "shmctl", "shmdt"} <= allowed


def test_chromium_uses_the_fixed_extension_and_native_host() -> None:
    for contract in [
        "hehggadaopoacecdllhhajmbjkdcmajg",
        "com.openai.codexextension",
        "/opt/sky-cua/browser/native-host/sky-cua-chrome-host",
        "--user-data-dir=",
        "--ozone-platform=x11",
        "--force-renderer-accessibility",
        "--disable-extensions-except=",
        "--load-extension=",
        "--remote-debugging-port=0",
        "--silent-debugger-extension-api",
        "--no-first-run",
        "--no-default-browser-check",
    ]:
        assert contract in ENTRYPOINT


def test_chromium_window_is_restored_from_persisted_minimized_state() -> None:
    start_body = ENTRYPOINT.split("start_chromium() {", maxsplit=1)[1].split(
        "start_mcp_server() {", maxsplit=1
    )[0]

    assert 'restore_chromium_window "${chromium_window_id}"' in start_body
    assert 'wmctrl -i -R "${window_id}"' in ENTRYPOINT
    assert 'wmctrl -i -r "${window_id}" -b add,maximized_vert,maximized_horz' in ENTRYPOINT
    assert "Map State: IsViewable" in ENTRYPOINT
    assert start_body.index("restore_chromium_window") < start_body.index("extension-*.sock")


def test_entrypoint_recovers_only_chromium_profile_lock_artifacts() -> None:
    body = main_body()

    assert "clear_stale_chromium_profile_locks" in body
    assert body.index("clear_stale_chromium_profile_locks") < body.index("start_chromium")
    for lock_name in ["SingletonCookie", "SingletonLock", "SingletonSocket"]:
        assert lock_name in ENTRYPOINT
    assert 'rm -f -- "${lock_path}"' in ENTRYPOINT


def test_xstartup_runs_a_minimal_xfce_session_on_the_shared_bus() -> None:
    assert "exec startxfce4" in XSTARTUP
    assert "XDG_CURRENT_DESKTOP=XFCE" in XSTARTUP
    assert "DESKTOP_SESSION=xfce" in XSTARTUP
    assert "dbus-launch" not in XSTARTUP
    assert "dbus-daemon" not in XSTARTUP
    assert "openbox" not in XSTARTUP.lower()
    assert "plasmashell" not in XSTARTUP
    assert "/workspace/Downloads" in XSTARTUP


def test_xfce_configuration_is_minimal_and_baked_into_the_image() -> None:
    assert "COPY docker/xfce-configs/" in DOCKERFILE
    assert "/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/" in DOCKERFILE
    assert ".config/xfce4/xfconf/xfce-perchannel-xml" in ENTRYPOINT

    for plugin in ["applicationsmenu", "tasklist", "separator", "systray", "clock"]:
        assert f'value="{plugin}"' in XFCE_PANEL
    for unavailable_plugin in ["pulseaudio", "power-manager-plugin", "notification-plugin"]:
        assert unavailable_plugin not in XFCE_PANEL

    assert "show-home" in XFCE_DESKTOP
    assert "show-filesystem" in XFCE_DESKTOP
    assert "use_compositing" in XFCE_WINDOW_MANAGER
    assert 'value="false"' in XFCE_WINDOW_MANAGER


def test_no_portal_systemd_or_host_x11_mount_is_introduced() -> None:
    combined = "\n".join([DOCKERFILE, ENTRYPOINT, XSTARTUP])
    assert "xdg-desktop-portal" not in combined
    assert "systemctl" not in combined
    assert "-v /tmp/.X11-unix" not in combined
