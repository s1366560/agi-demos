"""Opt-in native acceptance restricted to a disposable app built from NativeFixture.

This performs input only in that application's own PID and windows. It never
requests OS permission, records audio, sends messages, or changes lock state.
"""

import json
import os
import re
import select
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from fixture_bundle import build_fixture

ROOT = Path(__file__).resolve().parents[1]
OWNER = {
    field: "fixture-" + field
    for field in (
        "user_id",
        "tenant_id",
        "project_id",
        "conversation_id",
        "run_id",
        "device_id",
    )
}


class Channel:
    def __init__(self):
        self.process = subprocess.Popen(
            [
                os.environ.get("MEMSTACK_CUA_NATIVE_TEST_HELPER", str(ROOT / "bin/cua-helper")),
                "--stdio",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.counter = 0
        self.notifications = []
        self.request(
            "initialize",
            {
                "client_api_version": "MemstackComputerUseIPC-2",
                "secret": "native-fixture-not-a-secret-000000000000",
                "nonce": "native-fixture-nonce-000000000000",
                "native_status_notifications": True,
            },
            request_id=0,
        )

    def send(self, method, params, request_id=None):
        self.counter += 1
        if "session_id" in params:
            params = {**OWNER, **params}
        value = {
            "jsonrpc": "2.0",
            "id": self.counter if request_id is None else request_id,
            "method": method,
            "params": params,
        }
        data = json.dumps(value).encode()
        self.process.stdin.write(struct.pack("<I", len(data)) + data)
        self.process.stdin.flush()
        return value["id"]

    def read(self):
        assert select.select([self.process.stdout], [], [], 15)[0], "helper response timeout"
        header = self.process.stdout.read(4)
        assert len(header) == 4, "helper exited"
        (length,) = struct.unpack("<I", header)
        assert 0 < length <= 8_388_608
        result = json.loads(self.process.stdout.read(length))
        if "id" not in result:
            assert result["method"] == "native_status", result
            self.notifications.append(result["params"])
            return self.read()
        return result

    def request(self, method, params, request_id=None):
        sent = self.send(method, params, request_id)
        result = self.read()
        assert result["id"] == sent
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=5)
        else:
            self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()


def jpeg_dimensions(path):
    data = path.read_bytes()
    assert data[:2] == b"\xff\xd8"
    offset = 2
    while offset < len(data):
        assert data[offset] == 0xFF
        marker = data[offset + 1]
        offset += 2
        if marker in (0xD8, 0xD9):
            continue
        length = int.from_bytes(data[offset : offset + 2], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return width, height
        offset += length
    raise AssertionError("JPEG dimensions absent")


# Keep foreground input, pause/stop, and crash recovery in one ordered fixture lifecycle.
def main():  # noqa: C901, PLR0915
    if "--allow-own-fixture-input" not in os.sys.argv:
        raise SystemExit("Pass --allow-own-fixture-input after reserving a foreground test window")
    channel = Channel()
    fixture = None
    try:
        caps = channel.request("capabilities", {})["result"]["capabilities"]
        assert caps["app_state"]["state"] == "available", (
            "Accessibility permission required; no prompt issued"
        )
        assert caps["screenshots"]["state"] == "available", (
            "Screen Recording permission required; no prompt issued"
        )
        with tempfile.TemporaryDirectory(
            prefix="memstack-cua-native-", dir=os.environ.get("TMPDIR")
        ) as temp:
            bundle = Path(temp) / "ComputerUseFixture.app"
            binary = build_fixture(bundle)
            event_log = Path(temp) / "fixture-events.log"
            event_log.touch()
            fixture = subprocess.Popen(
                [str(binary), "--background"],
                env={
                    **os.environ,
                    "CUA_FIXTURE_EVENT_LOG": str(event_log),
                },
            )
            base = {"session_id": "native-fixture"}
            root = Path(channel.request("begin_session", base)["result"]["artifact_root"])
            for _ in range(50):
                resolved = channel.request(
                    "resolve_app", {**base, "app": "pid:" + str(fixture.pid)}
                )
                if "result" in resolved:
                    break
                time.sleep(0.1)
            app = resolved["result"]
            target = {
                **base,
                "app": "pid:" + str(fixture.pid),
                "expected_identity_digest": app["identity_digest"],
            }
            for _ in range(50):
                windows = channel.request("list_windows", target)["result"]["windows"]
                if len(windows) == 2:
                    break
                time.sleep(0.05)
            assert len(windows) == 2, windows
            windows.sort(key=lambda value: value["title"])
            assert windows[0]["window_id"] != windows[1]["window_id"]

            def observe(window):
                response = channel.request(
                    "get_app_state",
                    {**target, "window_id": window["window_id"], "disable_diff": True},
                )
                assert "result" in response, response
                value = response["result"]
                assert value["window_id"] == window["window_id"]
                assert window["title"] in value["text"]
                image = value["screenshot"]
                assert image and image["width"] > 0 and image["height"] > 0, value
                path = Path(unquote(urlparse(image["url"]).path))
                assert path.is_relative_to(root) and not path.is_symlink()
                assert jpeg_dimensions(path) == (image["width"], image["height"])
                assert value["target"]["process_id"] == fixture.pid
                assert value["target"]["identity_digest"] == app["identity_digest"]
                assert value["target"]["window_id"] == window["window_id"]
                icon = value["app_icon"]
                icon_path = Path(unquote(urlparse(icon["url"]).path))
                png = icon_path.read_bytes()
                assert png.startswith(b"\x89PNG\r\n\x1a\n")
                assert struct.unpack(">II", png[16:24]) == (64, 64)
                assert icon_path.parent == root and icon_path.stat().st_mode & 0o777 == 0o600
                assert "base64" not in json.dumps(value)
                return value

            def activate(window):
                result = channel.request(
                    "activate_app", {**target, "window_id": window["window_id"]}
                )
                assert "result" in result, result

            def observe_until(window, expected):
                deadline = time.monotonic() + 2
                while True:
                    current = observe(window)
                    if expected in current["text"]:
                        return current
                    if time.monotonic() >= deadline:
                        raise AssertionError(current["text"] + "\nEVENTS: " + event_log.read_text())
                    time.sleep(0.05)

            def action(state, payload):
                result = channel.request(
                    "perform_action",
                    {
                        **target,
                        "snapshot_id": state["snapshot_id"],
                        "window_id": state["window_id"],
                        "request_id": "action-" + str(channel.counter),
                        "action": payload,
                    },
                )
                if "error" in result:
                    print("FIXTURE_ACTION_ERROR:", payload["kind"], result, flush=True)
                return result

            first = observe(windows[0])
            observe(windows[1])
            paused_image = Path(unquote(urlparse(first["screenshot"]["url"]).path))
            channel.request("pause_session", base)
            assert channel.notifications[-1]["phase"] == "paused"
            assert channel.notifications[-1]["context"] == {**OWNER, **base}
            assert not paused_image.exists()
            assert (
                channel.request("list_apps", base)["error"]["data"]["kind"]
                == "user_stopped_session"
            )
            assert channel.request("resume_session", base)["result"]["requires_observation"]
            rejected = action(first, {"kind": "type_text", "text": "must not be typed"})
            assert rejected["error"]["data"]["kind"] == "stale_element", rejected
            assert channel.request("audio_status", base)["result"]["recording"] is False
            # Resume invalidates observations, while the same live window can
            # immediately be observed again without retargeting the task.
            observe(windows[0])
            previous_ids = {window["window_id"] for window in windows}
            windows = channel.request("list_windows", target)["result"]["windows"]
            assert len(windows) == 2
            assert {window["window_id"] for window in windows} == previous_ids
            windows.sort(key=lambda value: value["title"])
            activate(windows[1])
            first = observe(windows[0])
            rejected = action(first, {"kind": "type_text", "text": "must not be typed"})
            assert rejected["error"]["data"]["kind"] == "target_not_focused", rejected
            activate(windows[0])
            first = observe(windows[0])
            text_index = int(re.search(r"\[(\d+)\] AXTextField", first["text"])[1])
            assert "result" in action(first, {"kind": "click", "element_index": text_index})
            current = observe(windows[0])
            assert "result" in action(current, {"kind": "press_key", "key": "super+a"})
            current = observe(windows[0])
            assert "result" in action(current, {"kind": "type_text", "text": "原生中文输入验收"})
            current = observe(windows[0])
            assert "原生中文输入验收" in current["text"], (
                current["text"] + "\nEVENTS: " + event_log.read_text()
            )
            # Verify a held modifier changes actual subsequent key events,
            # then removing it clears their flags. No aggregate HID inference.
            flags_after_keys = []
            for down, expected_flag in ((True, 131072), (False, 0)):
                if down:
                    assert "result" in action(
                        observe(windows[0]), {"kind": "key_down", "key": "shift"}
                    )
                    observe_until(windows[0], "Shift held: true")
                else:
                    assert "result" in action(
                        observe(windows[0]), {"kind": "key_up", "key": "shift"}
                    )
                    observe_until(windows[0], "Shift held: false")
                prior = len(event_log.read_text().splitlines())
                assert "result" in action(observe(windows[0]), {"kind": "key_down", "key": "a"})
                result = action(observe(windows[0]), {"kind": "key_up", "key": "a"})
                assert "result" in result, str(result) + "\nEVENTS: " + event_log.read_text()
                events = event_log.read_text().splitlines()[prior:]
                key_event = next(event for event in events if event.startswith("type=10 "))
                flags = int(re.search(r"flags=(\d+)", key_event)[1])
                assert flags & 131072 == expected_flag, key_event
                flags_after_keys.append(flags)

            assert "result" in action(observe(windows[0]), {"kind": "key_down", "key": "shift"})
            assert "result" in action(observe(windows[0]), {"kind": "key_down", "key": "a"})
            # Releasing a modifier while the ordinary key remains down must
            # clear the modifier on actual subsequently delivered keys.
            assert "result" in action(observe(windows[0]), {"kind": "key_up", "key": "shift"})
            observe_until(windows[0], "Shift held: false")
            prior = len(event_log.read_text().splitlines())
            assert "result" in action(observe(windows[0]), {"kind": "key_down", "key": "b"})
            assert "result" in action(observe(windows[0]), {"kind": "key_up", "key": "b"})
            key_event = next(
                event
                for event in event_log.read_text().splitlines()[prior:]
                if event.startswith("type=10 ")
            )
            assert int(re.search(r"flags=(\d+)", key_event)[1]) & 131072 == 0, key_event
            assert "result" in action(observe(windows[0]), {"kind": "key_up", "key": "a"})

            simulator = Path(temp) / "foreign-input-simulation"
            subprocess.run(
                [
                    "swiftc",
                    str(ROOT / "Sources/DesktopInputLease.swift"),
                    str(ROOT / "tests/ForeignInputSimulation.swift"),
                    "-o",
                    str(simulator),
                ],
                check=True,
            )
            subprocess.run(["codesign", "--force", "--sign", "-", str(simulator)], check=True)
            assert "result" in action(observe(windows[0]), {"kind": "key_down", "key": "shift"})
            observe_until(windows[0], "Shift held: true")
            simulated = subprocess.Popen(
                [str(simulator), str(fixture.pid)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                assert simulated.stdout.readline() == b"simulated-foreign-shift-held\n"
                assert "result" in action(observe(windows[0]), {"kind": "key_up", "key": "shift"})
                assert "Shift held: true" in observe(windows[0])["text"], (
                    "foreign simulated hold was released"
                )
                channel.request("stop_session", base)
                channel.request("end_session", base)
                base = {"session_id": "native-fixture-after-foreign"}
                root = Path(channel.request("begin_session", base)["result"]["artifact_root"])
                target = {
                    **base,
                    "app": "pid:" + str(fixture.pid),
                    "expected_identity_digest": app["identity_digest"],
                }
                windows = channel.request("list_windows", target)["result"]["windows"]
                windows.sort(key=lambda window: window["title"])
                assert "Shift held: true" in observe(windows[0])["text"]
                probe = subprocess.run(
                    [str(simulator), "lease-probe"], capture_output=True, timeout=5
                )
                assert probe.returncode == 3 and probe.stdout.strip() == b"device_busy"
            finally:
                simulated.stdin.close()
                simulated.wait(timeout=6)
                simulated.stdout.close()
                simulated.stderr.close()
            observe_until(windows[0], "Shift held: false")
            stale = action(first, {"kind": "type_text", "text": "stale input"})
            assert stale["error"]["data"]["kind"] == "stale_element", stale
            current = observe(windows[0])
            started = channel.send(
                "perform_action",
                {
                    **target,
                    "snapshot_id": current["snapshot_id"],
                    "window_id": current["window_id"],
                    "request_id": "cancel-held-shift",
                    "action": {"kind": "press_key", "key": "shift", "duration": 5.0},
                },
            )
            time.sleep(0.2)
            stopped = channel.send("stop_session", base)
            began = time.monotonic()
            responses = {result["id"]: result for result in (channel.read(), channel.read())}
            assert time.monotonic() - began < 2, responses
            assert responses[started]["error"]["data"]["kind"] == "user_stopped_session", responses
            assert "result" in responses[stopped]
            channel.request("end_session", base)
            base = {"session_id": "native-fixture-after-stop"}
            root = Path(channel.request("begin_session", base)["result"]["artifact_root"])
            target = {
                **base,
                "app": "pid:" + str(fixture.pid),
                "expected_identity_digest": app["identity_digest"],
            }
            windows = channel.request("list_windows", target)["result"]["windows"]
            first_window = next(window for window in windows if window["title"].endswith("1"))
            current = observe_until(first_window, "Shift held: false")
            channel.request("end_session", base)
            assert not root.exists()
            # SIGKILL does not run finally blocks, EOF handlers or signal
            # handlers in the native worker. Its independent watchdog must.
            for kind, payload, expected in (
                ("key", {"kind": "key_down", "key": "shift"}, "Shift held"),
                (
                    "drag",
                    {"kind": "drag_step", "phase": "begin", "x": 50.0, "y": 110.0},
                    "Left button held",
                ),
            ):
                channel.close()
                channel = Channel()
                base = {"session_id": "native-fixture-crash-" + kind}
                root = Path(channel.request("begin_session", base)["result"]["artifact_root"])
                target = {
                    **base,
                    "app": "pid:" + str(fixture.pid),
                    "expected_identity_digest": app["identity_digest"],
                }
                windows = channel.request("list_windows", target)["result"]["windows"]
                first_window = next(window for window in windows if window["title"].endswith("1"))
                activate(first_window)
                current = observe(first_window)
                assert expected + ": false" in current["text"]
                result = action(current, payload)
                assert "result" in result, result
                current = observe_until(first_window, expected + ": true")
                channel.process.kill()
                channel.process.wait(timeout=5)
                channel.close()
                channel = Channel()
                base = {"session_id": "native-fixture-probe-" + kind}
                crashed_root = root
                root = Path(channel.request("begin_session", base)["result"]["artifact_root"])
                target = {
                    **base,
                    "app": "pid:" + str(fixture.pid),
                    "expected_identity_digest": app["identity_digest"],
                }
                windows = channel.request("list_windows", target)["result"]["windows"]
                first_window = next(window for window in windows if window["title"].endswith("1"))
                observe_until(first_window, expected + ": false")
                assert not crashed_root.exists(), "crashed worker's private artifacts remain"
                channel.request("end_session", base)
                assert not root.exists()
            print(
                "CUA_NATIVE_FIXTURE_OK: two windows, real JPEG dimensions, focus/stale rejection, Chinese input, held modifier flags, foreign HID-source takeover simulation, stop and SIGKILL key/drag receiver recovery, crash artifact cleanup"
            )
    finally:
        if fixture is not None:
            fixture.terminate()
            fixture.wait(timeout=5)
        channel.close()


if __name__ == "__main__":
    main()
