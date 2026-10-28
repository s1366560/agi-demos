#!/usr/bin/env python3
"""Exercise the real helper against an isolated GTK/Xvfb desktop, never the host display.

Requirements: Xvfb, openbox, dbus-run-session, python3-gi, python3-dbus,
at-spi2-core, xdotool, x11-utils, GStreamer base/good plugins.
Run: python3 tests/linux_native_smoke.py /path/to/memstack-cua-native-helper
"""

import hashlib
import hmac
import json
import os
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse


# Keep GTK setup and its callbacks together so the fixture's native lifetimes are explicit.
def fixture():  # noqa: PLR0915
    import dbus
    import dbus.mainloop.glib
    import dbus.service
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    name = dbus.service.BusName("org.freedesktop.ScreenSaver", bus)

    class Lock(dbus.service.Object):
        active = False

        @dbus.service.method("org.freedesktop.ScreenSaver", out_signature="b")
        def GetActive(self):
            return self.active

        @dbus.service.method("org.freedesktop.ScreenSaver", in_signature="b")
        def SetActive(self, value):
            self.active = value

    lock = Lock(name, "/org/freedesktop/ScreenSaver")
    GLib.set_prgname("memstack-native-fixture")
    window = Gtk.Window(title="Memstack isolated native fixture")
    native_icon = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 64, 64)
    native_icon.fill(0x1850D2FF)
    window.set_icon(native_icon)
    window.set_default_size(420, 140)
    window.set_position(Gtk.WindowPosition.CENTER)
    entry = Gtk.Entry()
    entry.get_accessible().set_name("MemstackFixtureEntry")
    entry.connect("changed", lambda value: Path(sys.argv[2]).write_text(value.get_text()))
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clipboard.set_text("ORIGINAL_NATIVE_中文🙂", -1)
    command = Path(sys.argv[2]).parent / "clipboard-command.json"
    reply = Path(sys.argv[2]).parent / "clipboard-reply.json"

    modal = None

    def clipboard_command():
        nonlocal modal
        if command.exists():
            params = json.loads(command.read_text())
            command.unlink()
            if params["kind"] == "show_modal":
                modal = Gtk.Dialog(title="Native fixture modal", transient_for=window, modal=True)
                modal.add_button("Close fixture", Gtk.ResponseType.CLOSE)
                modal.show_all()
                result = {"ok": True}
            elif params["kind"] == "hide_modal":
                modal.destroy()
                modal = None
                result = {"ok": True}
            elif params["kind"] == "set":
                clipboard.set_text(params["text"], -1)
                result = {"ok": True}
            elif params["kind"] == "clear":
                clipboard.clear()
                result = {"ok": True}
            else:
                target = Gdk.Atom.intern(params.get("mime", "UTF8_STRING"), False)
                content = clipboard.wait_for_contents(target)
                result = {"text": bytes(content.get_data()).decode() if content else None}
            temporary = reply.with_suffix(".tmp")
            temporary.write_text(json.dumps({"id": params["id"], **result}))
            temporary.replace(reply)
        return True

    GLib.timeout_add(10, clipboard_command)
    password = Gtk.Entry()
    password.set_visibility(False)
    password.set_text("SECRET_FIXTURE_SHOULD_NOT_TRANSCRIPT")
    password.get_accessible().set_name("NativeProtectedValue")
    layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    layout.pack_start(entry, True, True, 0)
    layout.pack_start(password, True, True, 0)
    window.add(layout)
    window.show_all()
    entry.grab_focus()
    window.connect("destroy", Gtk.main_quit)
    Gtk.main()
    del lock


def occluder():
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk

    window = Gtk.Window(title="Memstack isolated capture occluder")
    area = Gtk.DrawingArea()
    style = Gtk.CssProvider()
    style.load_from_data(b"* { background-color: #ff0000; }")
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    window.add(area)
    window.set_keep_above(True)
    window.fullscreen()
    window.show_all()
    Gtk.main()


class Client:
    def __init__(self, executable, environment=None):
        self.process = subprocess.Popen(
            [executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=environment
        )
        self.index = 0
        self.context = dict.fromkeys(
            (
                "device_id",
                "user_id",
                "tenant_id",
                "project_id",
                "conversation_id",
                "run_id",
                "session_id",
            ),
            "native-fixture",
        )
        self.context["input_mode"] = "foreground"
        self.input_generation = None
        secret = "native-fixture-channel-secret-00000000"
        nonce = "native-fixture-nonce-0000"
        initialized = self.call(
            "initialize",
            {"client_api_version": "MemstackComputerUseIPC-3", "secret": secret, "nonce": nonce},
            bound=False,
        )
        assert (
            initialized["proof"]
            == hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
        )
        assert initialized["server_api_version"] == "MemstackComputerUseIPC-3"
        self.root = Path(self.call("begin_session", {})["artifact_root"])
        assert self.input_generation
        support = self.call("capabilities", {}, bound=False)["input_support"]
        assert support["background"] == {
            "supported": False,
            "reason": "background_input_unsupported",
        }
        assert isinstance(support["foreground"]["supported"], bool)

    def receive(self, count):
        result = bytearray()
        deadline = time.monotonic() + 20
        while len(result) < count:
            ready, _, _ = select.select(
                [self.process.stdout], [], [], max(0, deadline - time.monotonic())
            )
            if not ready:
                raise TimeoutError("native helper response deadline exceeded")
            chunk = os.read(self.process.stdout.fileno(), count - len(result))
            if not chunk:
                raise RuntimeError("native helper exited before response")
            result.extend(chunk)
        return bytes(result)

    def call(self, method, params, *, bound=True, expected_error=None):
        if bound:
            params = {**params, **self.context}
            if method != "begin_session":
                assert self.input_generation
                params["input_generation"] = self.input_generation
        request_id = self.index
        self.index += 1
        body = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        ).encode()
        self.process.stdin.write(struct.pack("<I", len(body)) + body)
        self.process.stdin.flush()
        (length,) = struct.unpack("<I", self.receive(4))
        assert length <= 8 * 1024 * 1024
        response = json.loads(self.receive(length))
        assert response["id"] == request_id
        if expected_error:
            assert response["error"]["data"]["kind"] == expected_error, response
            return response
        assert "error" not in response, response
        result = response["result"]
        if bound and "input_generation" in result:
            assert result["input_mode"] == self.context["input_mode"]
            assert isinstance(result["input_generation"], str) and result["input_generation"]
            self.input_generation = result["input_generation"]
        return result

    def close(self):
        try:
            self.call("end_session", {})
        finally:
            self.process.stdin.close()
            self.process.wait(timeout=10)
            assert self.root.name.startswith("memstack-cua-owned-")
            for _ in range(100):
                if not self.root.exists():
                    break
                time.sleep(0.01)
            assert not self.root.exists(), "guardian did not remove its private artifact root"
        shutil.rmtree(self.root, ignore_errors=True)


# This native acceptance sequence deliberately retains one live session across ordered checks.
def exercise(executable, no_composite=False):  # noqa: C901, PLR0915
    with tempfile.TemporaryDirectory(prefix="memstack-native-fixture-") as directory:
        value = Path(directory) / "entry.txt"
        app = subprocess.Popen([sys.executable, __file__, "--fixture", str(value)])
        installed = Path(directory) / "xdg-data" / "applications"
        installed.mkdir(parents=True)
        launched_value = Path(directory) / "launched-entry.txt"
        desktop = installed / "memstack-native-launch-fixture.desktop"
        desktop.write_text(
            "[Desktop Entry]\nType=Application\nName=Memstack native launch fixture\n"
            f"Exec={sys.executable} {__file__} --fixture {launched_value}\nTerminal=false\n"
        )
        environment = {
            **os.environ,
            "XDG_DATA_HOME": str(installed.parent),
            "XDG_DATA_DIRS": "/nonexistent",
        }
        client = None
        launched_pid = None
        command_index = 0

        def clipboard_command(kind, **params):
            nonlocal command_index
            command_index += 1
            command = Path(directory) / "clipboard-command.json"
            temporary = command.with_suffix(".tmp")
            temporary.write_text(json.dumps({"id": command_index, "kind": kind, **params}))
            temporary.replace(command)
            reply = Path(directory) / "clipboard-reply.json"
            for _ in range(200):
                if reply.exists():
                    output = json.loads(reply.read_text())
                    if output["id"] == command_index:
                        return output
                time.sleep(0.01)
            raise TimeoutError("GTK native clipboard command deadline exceeded")

        try:
            client = Client(executable, environment)
            target = None
            for _ in range(40):
                apps = client.call("list_apps", {})["apps"]
                target = next(
                    (candidate for candidate in apps if candidate["process_id"] == app.pid), None
                )
                if target:
                    break
                time.sleep(0.1)
            assert target is not None, apps
            windows = client.call("list_windows", {"app": f"pid:{app.pid}"})["windows"]
            assert len(windows) == 1, windows
            assert windows[0]["modal"] is False and windows[0]["window_type"] == "atspi:Frame", (
                windows
            )
            assert (
                target["is_running"]
                and target["windows"][0]["window_id"] == windows[0]["window_id"]
            )
            params = {
                "app": f"pid:{app.pid}",
                "window_id": windows[0]["window_id"],
                "expected_identity_digest": target["identity_digest"],
            }
            client.call("activate_app", params)
            state = client.call("get_app_state", params)
            icon = state.get("app_icon")
            assert icon and icon["kind"] == "app_icon" and icon["mime_type"] == "image/png", state
            icon_path = Path(unquote(urlparse(icon["url"]).path))
            assert icon_path.parent == client.root and struct.unpack(
                ">II", icon_path.read_bytes()[16:24]
            ) == (64, 64)
            resolved_icon = client.call("resolve_app", {"app": f"pid:{app.pid}"})["app_icon"]
            assert resolved_icon["width"] == 64 and resolved_icon["height"] == 64
            assert "NativeProtectedValue" in state["text"]
            assert "SECRET_FIXTURE_SHOULD_NOT_TRANSCRIPT" not in state["text"]
            tree = state["ax_tree"]
            assert (
                tree["snapshot_id"] == state["snapshot_id"]
                and tree["window_id"] == state["window_id"]
            )
            assert tree["version"] == 1 and tree["source"] == "at_spi"
            assert not tree["truncated"] and 0 < len(tree["nodes"]) <= 4096
            depths = []
            for ordinal, node in enumerate(tree["nodes"]):
                assert node["element_index"] == ordinal and "backend_ref" not in node
                parent = node["parent_index"]
                assert (ordinal == 0 and parent is None) or (
                    parent is not None and parent < ordinal
                )
                depths.append(0 if parent is None else depths[parent] + 1)
                assert depths[-1] <= 64
            typed_entry = next(
                node for node in tree["nodes"] if node["name"] == "MemstackFixtureEntry"
            )
            protected = next(
                node for node in tree["nodes"] if node["name"] == "NativeProtectedValue"
            )
            assert typed_entry["parent_index"] is not None
            assert protected["value_redacted"] and protected["value"] is None
            assert "/org/a11y" not in json.dumps(tree["nodes"]), "private node reference leaked"
            assert "SECRET_FIXTURE_SHOULD_NOT_TRANSCRIPT" not in json.dumps(tree), (
                "protected native value leaked"
            )
            if no_composite:
                capabilities = client.call("capabilities", {}, bound=False)["capabilities"]
                assert capabilities["screenshots"]["state"] == "unavailable"
                assert state["screenshot"] is None
                assert "screenshot unavailable: capture_unavailable" in state["text"]
                print(
                    json.dumps(
                        {
                            "status": "passed",
                            "platform": "isolated_linux_x11",
                            "check": "no_Composite_no_root_capture_fallback",
                        }
                    )
                )
                return
            path = Path(unquote(urlparse(state["screenshot"]["url"]).path))
            assert path.is_file() and path.parent == client.root
            png = path.read_bytes()
            assert png[:8] == b"\x89PNG\r\n\x1a\n"
            width, height = struct.unpack(">II", png[16:24])
            assert (width, height) == (state["screenshot"]["width"], state["screenshot"]["height"])
            assert width > 0 and height > 0
            assert state["screenshot"]["capture_scope"] == "exact_window"
            import gi

            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk, GdkPixbuf

            def center_pixel(image):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(image))
                offset = (height // 2) * pixbuf.get_rowstride() + (
                    width // 2
                ) * pixbuf.get_n_channels()
                return bytes(pixbuf.get_pixels()[offset : offset + 3])

            baseline = center_pixel(path)
            covering = subprocess.Popen([sys.executable, __file__, "--occluder"])
            try:
                time.sleep(0.5)
                bounds = state["window_bounds"]
                screen = Gdk.pixbuf_get_from_window(
                    Gdk.get_default_root_window(),
                    int(bounds["x"] + bounds["width"] // 2),
                    int(bounds["y"] + bounds["height"] // 2),
                    1,
                    1,
                )
                assert bytes(screen.get_pixels()[:3]) == b"\xff\x00\x00"
                hidden = client.call("get_app_state", params)
                hidden_path = Path(unquote(urlparse(hidden["screenshot"]["url"]).path))
                assert center_pixel(hidden_path) == baseline
                assert (
                    hidden["screenshot"]["native_window_id"]
                    == state["screenshot"]["native_window_id"]
                )
            finally:
                covering.terminate()
                covering.wait(timeout=5)
            client.call("activate_app", params)
            lines = state["text"].splitlines()
            entry = next(line for line in lines if "MemstackFixtureEntry" in line)
            index = int(entry[1 : entry.index("]")])

            def act(action):
                observed = client.call("get_app_state", params)
                return client.call(
                    "perform_action",
                    {**params, "snapshot_id": observed["snapshot_id"], "action": action},
                )

            act({"kind": "set_value", "element_index": index, "value": "native 中🙂"})
            for _ in range(20):
                if value.exists() and value.read_text() == "native 中🙂":
                    break
                time.sleep(0.05)
            assert value.read_text() == "native 中🙂"
            act({"kind": "press_key", "key": "Ctrl+A"})
            act({"kind": "type_text", "text": "FULL_TYPE_123中文🙂"})
            assert value.read_text() == "FULL_TYPE_123中文🙂"
            act({"kind": "key_down", "key": "Shift"})
            act({"kind": "key_up", "key": "Shift"})
            act({"kind": "drag_step", "phase": "begin", "x": 100, "y": 80})
            act({"kind": "drag_step", "phase": "move", "x": 180, "y": 80})
            act({"kind": "drag_step", "phase": "end", "x": 180, "y": 80})
            client.call(
                "perform_action",
                {
                    **params,
                    "snapshot_id": state["snapshot_id"],
                    "action": {"kind": "click", "x": 5, "y": 5},
                },
                expected_error="stale_element",
            )
            permissions = client.call("permissions_status", {}, bound=False)
            assert len(permissions) == 8
            assert permissions["accessibility"]["state"] == "granted"
            assert permissions["screen_capture"]["state"] == "granted"
            assert permissions["microphone"]["state"] != "granted"
            client.call("audio_status", {})
            recovery = client.call("capabilities", {}, bound=False)["capabilities"][
                "clipboard_crash_recovery"
            ]
            assert (
                recovery["state"] == "available"
                and recovery["backend"] == "xfixes_exact_writer_close"
            ), recovery
            saved = client.call("clipboard_read", {})
            assert saved["text"] == "ORIGINAL_NATIVE_中文🙂", saved
            client.call("clipboard_write", {"text": "<b>NATIVE_HTML_中文🙂</b>", "format": "html"})
            assert (
                clipboard_command("read", mime="text/html")["text"] == "<b>NATIVE_HTML_中文🙂</b>"
            )
            assert client.call("clipboard_release", {"handle": saved["handle"]})["restored"]
            assert clipboard_command("read")["text"] == "ORIGINAL_NATIVE_中文🙂"
            large = "NATIVE_INCR_中文🙂" * 10000
            saved = client.call("clipboard_read", {})
            client.call("clipboard_write", {"text": large, "format": "text"})
            assert clipboard_command("read")["text"] == large
            assert client.call("clipboard_release", {"handle": saved["handle"]})["restored"]
            saved = client.call("clipboard_read", {})
            client.call("clipboard_write", {"text": "OWNED_NATIVE", "format": "text"})
            clipboard_command("set", text="USER_REPLACED_NATIVE")
            assert not client.call("clipboard_release", {"handle": saved["handle"]})["restored"]
            assert clipboard_command("read")["text"] == "USER_REPLACED_NATIVE"
            clipboard_command("clear")
            saved = client.call("clipboard_read", {})
            assert saved["text"] is None, saved
            client.call("clipboard_write", {"text": "OWNED_AFTER_EMPTY", "format": "text"})
            assert client.call("clipboard_release", {"handle": saved["handle"]})["restored"]
            assert clipboard_command("read")["text"] is None
            # Native query confirms pause releases held input before its response; no actual recording starts.
            from linux_watchdog_smoke import State

            native_state = State()
            clipboard_command("set", text="PAUSE_NATIVE_BASELINE")
            client.call("clipboard_read", {})
            client.call("clipboard_write", {"text": "PAUSE_NATIVE_OWNED", "format": "text"})
            act({"kind": "key_down", "key": "Shift"})
            act({"kind": "drag_step", "phase": "begin", "x": 100, "y": 80})
            assert native_state.held() == (True, True)
            before_pause = client.call("get_app_state", params)
            assert list(client.root.iterdir())
            assert client.call("pause_session", {})["phase"] == "paused"
            assert native_state.held() == (False, False)
            assert clipboard_command("read")["text"] == "PAUSE_NATIVE_BASELINE"
            assert not list(client.root.iterdir())
            assert client.call("audio_status", {})["state"] == "idle"
            client.call("get_app_state", params, expected_error="session_paused")
            client.call("reset_session", {}, expected_error="session_paused")
            resumed = client.call("resume_session", {})
            assert resumed["requires_observation"] and resumed["phase"] == "idle"
            client.call(
                "perform_action",
                {
                    **params,
                    "snapshot_id": before_pause["snapshot_id"],
                    "action": {"kind": "click", "x": 5, "y": 5},
                },
                expected_error="stale_element",
            )
            act({"kind": "press_key", "key": "Ctrl+A"})
            clipboard_command("show_modal")
            modal_windows = client.call("list_windows", {"app": f"pid:{app.pid}"})["windows"]
            assert len(modal_windows) == 2 and any(
                window["modal"] is True and window["window_type"] == "atspi:Dialog"
                for window in modal_windows
            ), modal_windows
            clipboard_command("hide_modal")
            client.call("activate_app", params)
            installed_id = "desktop:memstack-native-launch-fixture.desktop"
            declared = client.call("resolve_app", {"app": installed_id})
            assert not declared["is_running"] and declared["installed_id"] == installed_id, declared
            client.call(
                "launch_app", {"app": "/tmp/arbitrary-executable"}, expected_error="app_not_found"
            )
            launch = client.call(
                "launch_app",
                {"app": installed_id, "expected_identity_digest": declared["identity_digest"]},
            )
            launched_pid = launch["process_id"]
            assert launched_pid != app.pid and launch["fresh_observation_required"], launch
            activated = client.call("resolve_app", {"app": f"pid:{launched_pid}"})
            assert activated["process_id"] == launched_pid and activated["is_running"], activated
            new_params = {
                "app": f"pid:{launched_pid}",
                "expected_identity_digest": activated["identity_digest"],
            }
            new_windows = client.call("list_windows", new_params)["windows"]
            assert len(new_windows) == 1
            new_params["window_id"] = new_windows[0]["window_id"]
            client.call("activate_app", new_params)
            assert "MemstackFixtureEntry" in client.call("get_app_state", new_params)["text"]
            client.call("cancel", {})
            client.call("reset_session", {})
            assert client.call("get_app_state", new_params)["ax_tree"]["nodes"]
            client.call("stop_session", {})
            client.call("reset_session", {}, expected_error="user_stopped_session")
            client.call("resume_session", {}, expected_error="user_stopped_session")
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "platform": "linux_x11",
                        "native_entry": value.read_text(),
                        "png_dimensions": [width, height],
                        "checks": [
                            "IPC2_HMAC",
                            "AT_SPI",
                            "exact_pid_window",
                            "PNG_capture",
                            "set_value_unicode",
                            "full_type",
                            "key_hold_release",
                            "phased_drag",
                            "snapshot_replay_rejected",
                            "actual_permissions",
                            "clipboard_native_formats",
                            "clipboard_INCR",
                            "clipboard_restore",
                            "clipboard_external_owner",
                            "clipboard_empty_restore",
                            "installed_XDG_launch",
                            "launch_exact_new_pid",
                            "launch_fresh_native_observation",
                            "arbitrary_launch_rejected",
                            "native_password_role_suppressed",
                            "XComposite_exact_window",
                            "covered_window_does_not_capture_other_app",
                            "native_app_icon",
                            "apps_exact_window_aggregation",
                            "native_modal_window_type",
                            "pause_releases_held_input_clipboard_temp",
                            "resume_requires_fresh_observation",
                            "public_native_AX_tree_parentage_password_redaction",
                            "cancel_recoverable_stop_terminal_reset_boundary",
                        ],
                    }
                )
            )
        finally:
            if client:
                client.close()
            app.terminate()
            app.wait(timeout=5)
            if launched_pid:
                os.kill(launched_pid, 15)


if __name__ == "__main__":
    if sys.argv[1] == "--fixture":
        fixture()
    elif sys.argv[1] == "--occluder":
        occluder()
    elif sys.argv[1] in ("--inside", "--inside-no-composite"):
        manager = subprocess.Popen(
            ["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            exercise(sys.argv[2], sys.argv[1] == "--inside-no-composite")
        finally:
            manager.terminate()
            manager.wait(timeout=5)
    else:
        if sys.argv[1] == "--without-composite":
            subprocess.run(
                [
                    "xvfb-run",
                    "-a",
                    "-s",
                    "-screen 0 1024x768x24 -extension Composite",
                    "dbus-run-session",
                    sys.executable,
                    __file__,
                    "--inside-no-composite",
                    os.path.abspath(sys.argv[2]),
                ],
                check=True,
            )
            sys.exit(0)
        subprocess.run(
            [
                "xvfb-run",
                "-a",
                "-s",
                "-screen 0 1024x768x24",
                "dbus-run-session",
                sys.executable,
                __file__,
                "--inside",
                os.path.abspath(sys.argv[1]),
            ],
            check=True,
        )
