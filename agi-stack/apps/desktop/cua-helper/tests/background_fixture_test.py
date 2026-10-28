"""Opt-in real background input tests against two disposable, signed fixture apps.

Only the owned target receives agent input. The independent foreground guard and
5 ms system-state observer detect accidental focus, cursor, or modifier changes.
This automated test does not claim to exercise a physical keyboard or trackpad.
"""

import json
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from fixture_bundle import build_fixture
from native_fixture_test import Channel

ROOT = Path(__file__).resolve().parents[1]


def rows(path):
    return [
        json.loads(line)
        for line in path.read_text().splitlines(keepends=True)
        if line.endswith("\n") and line.strip()
    ]


def until(operation, predicate, *, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        value = operation()
        if predicate(value):
            return value
        assert time.monotonic() < deadline, value
        time.sleep(0.03)


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        process.wait(timeout=5)


class BackgroundFixture:
    def __init__(self, directory):
        self.directory = directory
        self.channel = Channel()
        self.processes = []
        self.logs = {}
        self.dom_logs = {}
        self.composition_logs = {}
        self.instruction_paths = {}
        self.monitor = None
        self.base = {"session_id": "background-fixture"}
        self.target = None
        self.windows = []
        self.guard_offset = 0
        self.system_offset = 0
        self.content = os.environ.get("CUA_FIXTURE_CONTENT", "appkit")
        self.expect_global_button_limit = "--expect-global-button-limit" in os.sys.argv

    def launch(self, name, identifier, *, background):
        bundle = self.directory / name / (name + ".app")
        log = self.directory / (name + ".jsonl")
        log.touch()
        self.logs[name] = log
        dom_log = self.directory / (name + "-dom.jsonl")
        dom_log.touch()
        self.dom_logs[name] = dom_log
        composition_log = self.directory / (name + "-composition.jsonl")
        composition_log.touch()
        self.composition_logs[name] = composition_log
        instruction_path = self.directory / (name + "-instructions.txt")
        instruction_path.touch()
        self.instruction_paths[name] = instruction_path
        environment = {
            **os.environ,
            "CUA_FIXTURE_JSON_LOG": str(log),
            "CUA_FIXTURE_TITLE": name,
            "CUA_FIXTURE_DOM_LOG": str(dom_log),
            "CUA_FIXTURE_COMPOSITION_LOG": str(composition_log),
            "CUA_FIXTURE_INSTRUCTION_FILE": str(instruction_path),
            "CUA_FIXTURE_MOVE_ACK": str(self.directory / (name + "-moved")),
        }
        if background and self.content == "electron":
            binary = ROOT.parent / "node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"
            environment["CUA_FIXTURE_ELECTRON_DATA"] = str(self.directory / "electron-profile")
            command = [str(binary), str(ROOT / "tests/ElectronFixture/main.cjs")]
        else:
            binary = build_fixture(bundle, identifier=identifier)
            command = [str(binary), *(["--background"] if background else [])]
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.processes.append(process)
        return process

    def setup(self):
        capabilities = self.channel.request("capabilities", {})["result"]["capabilities"]
        assert capabilities["app_state"]["state"] == "available", "Accessibility required"
        assert capabilities["screenshots"]["state"] == "available", "Screen Recording required"
        self.app = self.launch(
            "Background Target", "ai.memstack.cua.background-fixture", background=True
        )
        started = self.channel.request("begin_session", {**self.base, "input_mode": "background"})
        assert "result" in started, started
        resolved = until(
            lambda: self.channel.request(
                "resolve_app", {**self.base, "app": f"pid:{self.app.pid}"}
            ),
            lambda value: "result" in value,
        )["result"]
        self.target = {
            **self.base,
            "app": f"pid:{self.app.pid}",
            "expected_identity_digest": resolved["identity_digest"],
        }
        listed = until(
            lambda: self.channel.request("list_windows", self.target),
            lambda value: len(value.get("result", {}).get("windows", [])) == 2,
        )
        self.windows = sorted(listed["result"]["windows"], key=lambda window: window["title"])
        self.guard = self.launch(
            "Foreground Guard", "ai.memstack.cua.guard-fixture", background=False
        )
        self.monitor_binary = self.directory / "input-monitor"
        subprocess.run(
            [
                "swiftc",
                "-parse-as-library",
                str(ROOT / "tests/BackgroundInputMonitor.swift"),
                "-o",
                str(self.monitor_binary),
            ],
            check=True,
        )
        self.baseline = until(
            self.system_state, lambda value: value["frontmost_pid"] == self.guard.pid, timeout=10
        )
        self.system_log = self.directory / "system-state.jsonl"
        self.monitor_output = self.system_log.open("w")
        self.monitor = subprocess.Popen([str(self.monitor_binary)], stdout=self.monitor_output)
        until(lambda: rows(self.system_log), bool)

    def system_state(self):
        return json.loads(subprocess.check_output([str(self.monitor_binary), "--snapshot"]))

    def visible_cursors(self):
        windows = json.loads(
            subprocess.check_output(
                [str(self.monitor_binary), "--visible-windows", str(self.channel.process.pid)]
            )
        )
        return [
            window
            for window in windows
            if window["layer"] == 0 and window["width"] == 24 and window["height"] == 28
        ]

    def observe(self, index=0):
        response = self.channel.request(
            "get_app_state",
            {**self.target, "window_id": self.windows[index]["window_id"], "disable_diff": True},
        )
        assert "result" in response, response
        state = response["result"]
        assert state["input_generation"], state
        return state

    def action(self, payload, index=0, *, state=None, success=True):
        state = state or self.observe(index)
        response = self.channel.request(
            "perform_action",
            {
                **self.target,
                "snapshot_id": state["snapshot_id"],
                "window_id": state["window_id"],
                "input_generation": state["input_generation"],
                "request_id": f"background-action-{self.channel.counter}",
                "action": payload,
            },
        )
        if success:
            assert "result" in response, response
        return response

    def assert_isolated(self):
        assert self.system_state() == self.baseline, (self.baseline, self.system_state())
        observed = rows(self.system_log)[self.system_offset :]
        assert observed and all(value == self.baseline for value in observed), observed
        assert not rows(self.logs["Foreground Guard"])[self.guard_offset :], rows(
            self.logs["Foreground Guard"]
        )

    def other_application_input(self):
        """A separate process simulates external Shift while the guard owns focus."""
        self.assert_isolated()

        sender_binary = self.directory / "external-input"
        subprocess.run(
            [
                "swiftc",
                "-parse-as-library",
                str(ROOT / "tests/BackgroundInputSender.swift"),
                "-o",
                str(sender_binary),
            ],
            check=True,
        )
        sender = subprocess.Popen(
            [str(sender_binary), str(self.guard.pid)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert sender.stdout.readline() == "ready\n"
            until(
                lambda: rows(self.logs["Foreground Guard"]),
                lambda values: any(
                    value["type"] == 12 and value["flags"] & 131072 for value in values
                ),
            )
            held_state = self.system_state()
            hold_offset = len(rows(self.system_log))
            before = len(rows(self.logs["Background Target"]))
            self.action({"kind": "key_down", "key": "b"})
            self.action({"kind": "key_up", "key": "b"})
            target_events = until(
                lambda: rows(self.logs["Background Target"])[before:],
                lambda values: any(value["type"] == 10 for value in values),
            )
            assert all(not value["flags"] & 131072 for value in target_events), target_events
            self.action({"kind": "key_down", "key": "shift"})
            self.action({"kind": "key_up", "key": "shift"})
            assert self.system_state() == held_state, (held_state, self.system_state())
            while_held = rows(self.system_log)[hold_offset:]
            assert all(value == held_state for value in while_held), while_held
        finally:
            sender.communicate("release\n", timeout=5)
        until(self.system_state, lambda value: value == self.baseline)
        until(
            lambda: rows(self.logs["Foreground Guard"]),
            lambda values: any(
                value["type"] == 12 and not value["flags"] & 131072 for value in values
            ),
        )
        self.guard_offset = len(rows(self.logs["Foreground Guard"]))
        until(lambda: rows(self.system_log), lambda values: values[-1] == self.baseline)
        self.system_offset = len(rows(self.system_log)) - 1
        self.assert_isolated()

    def secure_input_limit(self):
        before = len(rows(self.logs["Background Target"]))
        sender = subprocess.Popen(
            [str(self.directory / "external-input"), str(self.guard.pid), "--secure"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert sender.stdout.readline() == "ready\n"
            rejected = self.action({"kind": "type_text", "text": "must not arrive"}, success=False)
            assert rejected.get("error", {}).get("data", {}).get("kind") == "secure_input_active", (
                rejected
            )
            assert len(rows(self.logs["Background Target"])) == before
        finally:
            sender.communicate("release\n", timeout=5)
        self.action({"kind": "move", "x": 2, "y": 2})
        self.assert_isolated()

    def text_input(self, *, verify_isolation=True):
        for index, expected in enumerate(("后台中文输入 😀", "second window text")):
            state = until(
                lambda: self.observe(index),
                lambda value: re.search(r"\[(\d+)\] AXTextField", value["text"]),
                timeout=10,
            )
            element = int(re.search(r"\[(\d+)\] AXTextField", state["text"])[1])
            field = next(line for line in state["text"].splitlines() if "AXTextField" in line)
            field_x, field_y, field_width, field_height = map(
                float,
                re.search(r"frame=\(([-\d.]+),([-\d.]+) ([-\d.]+)x([-\d.]+)\)", field).groups(),
            )
            before = len(rows(self.logs["Background Target"]))
            before_dom = len(rows(self.dom_logs["Background Target"]))
            self.action({"kind": "click", "element_index": element}, index, state=state)
            self.action({"kind": "press_key", "key": "super+a"}, index)
            self.action({"kind": "type_text", "text": expected}, index)
            until(
                lambda: self.observe(index),
                lambda value: any(
                    "AXTextField" in line and f'value="{expected}"' in line
                    for line in value["text"].splitlines()
                ),
            )
            events = rows(self.logs["Background Target"])[before:]
            clicks = [
                value for value in events if value["type"] == 1 and value.get("click_count", 0) >= 1
            ]
            keys = [value for value in events if value["type"] == 10]
            assert len(clicks) == 1 and keys, events
            if self.content == "webkit":
                dom_events = rows(self.dom_logs["Background Target"])[before_dom:]
                for event_type in ("mousedown", "click"):
                    received = [value for value in dom_events if value["event"] == event_type]
                    assert len(received) == 1, dom_events
                    assert received[0]["window_index"] == index + 1, dom_events
                    assert received[0]["trusted"], dom_events
            if self.content == "electron":
                assert len([value for value in events if value["dom_type"] == "click"]) == 1, events
            window_numbers = {value["window"] for value in clicks + keys}
            assert len(window_numbers) == 1 and 0 not in window_numbers, events
            if self.content != "electron":
                expected_x = field_x + field_width / 2 - state["bounds"]["x"]
                expected_y = state["bounds"]["height"] - (
                    field_y + field_height / 2 - state["bounds"]["y"]
                )
                assert all(
                    abs(value["x"] - expected_x) < 1 and abs(value["y"] - expected_y) < 1
                    for value in clicks
                ), (clicks, expected_x, expected_y)
                assert all(value["frontmost_pid"] == self.guard.pid for value in events), events
        assert any(
            "AXTextField" in line and 'value="后台中文输入 😀"' in line
            for line in self.observe(0)["text"].splitlines()
        )
        if verify_isolation:
            self.assert_isolated()

    def mouse_and_modifiers(self):
        self.action({"kind": "move", "x": 100, "y": 200})
        for button in ("left", "right", "middle"):
            self.action({"kind": "click", "x": 100, "y": 200, "mouse_button": button})
        self.action({"kind": "click", "x": 100, "y": 200, "click_count": 2})
        self.action({"kind": "scroll", "x": 100, "y": 340, "direction": "down", "pages": 1})
        dom_path = (
            self.logs["Background Target"]
            if self.content == "electron"
            else self.dom_logs["Background Target"]
        )
        drag_offset = len(rows(dom_path))
        for phase, x in (("begin", 100), ("move", 160), ("end", 190)):
            self.action({"kind": "drag_step", "phase": phase, "x": x, "y": 200})
        completed = "drag complete:90,0" in self.observe()["text"]
        if self.expect_global_button_limit:
            assert not completed, "the expected compatibility limitation no longer reproduces"
            dom = rows(dom_path)[drag_offset:]
            event_key = "dom_type" if self.content == "electron" else "event"
            window_key = "window" if self.content == "electron" else "window_index"
            downs = [i for i, value in enumerate(dom) if value.get(event_key) == "mousedown"]
            assert len(downs) == 1 and dom[downs[0]].get("trusted"), dom
            down = dom[downs[0]]
            released = next(
                (i for i in range(downs[0] + 1, len(dom)) if dom[i].get(event_key) == "mouseup"),
                len(dom),
            )
            moves = [
                value
                for value in dom[downs[0] + 1 : released]
                if value.get(event_key) == "mousemove"
            ]
            assert moves and all(
                value.get("trusted")
                and value.get("buttons") == 0
                and value.get(window_key) == down.get(window_key)
                and value["x"] > down["x"]
                for value in moves
            ), dom
            assert any(
                value["x"] - down["x"] == 60 and value["y"] == down["y"] for value in moves
            ), dom
        else:
            assert completed, "the target did not complete the background drag"
        self.action({"kind": "key_down", "key": "shift"})
        before = len(rows(self.logs["Background Target"]))
        self.action({"kind": "key_down", "key": "a"})
        self.action({"kind": "key_up", "key": "a"})
        self.action({"kind": "key_up", "key": "shift"})
        events = rows(self.logs["Background Target"])[before:]
        assert any(value["type"] == 10 and value["flags"] & 131072 for value in events), events
        event_types = {value["type"] for value in rows(self.logs["Background Target"])}
        expected = {1, 2, 3, 4, 22, 25, 26}
        if not self.expect_global_button_limit:
            expected.add(6)
        assert expected <= event_types, event_types
        self.assert_isolated()

    def context_menu(self):
        if self.content != "webkit":
            return
        # The blank web-page strip above the drag region retains WK's native
        # context menu. Its nested tracking consumes some NSEvents internally;
        # assert the actual open/close outcome, not NSApplication.sendEvent counts.
        self.action({"kind": "click", "x": 100, "y": 130, "mouse_button": "right"})
        opened = until(self.observe, lambda value: "AXMenu" in value["text"])
        self.action({"kind": "press_key", "key": "Escape"}, state=opened)
        until(self.observe, lambda value: "AXMenu" not in value["text"])
        self.assert_isolated()

    def pause_and_generation(self):
        self.action({"kind": "key_down", "key": "shift"})
        if not self.expect_global_button_limit:
            self.action({"kind": "drag_step", "phase": "begin", "x": 100, "y": 200})
        previous = self.observe()
        paused = self.channel.request("pause_session", self.base)
        assert "result" in paused, paused
        until(
            lambda: rows(self.logs["Background Target"]),
            lambda values: values
            and any(
                value["type"] == (12 if self.expect_global_button_limit else 2)
                for value in values[-5:]
            ),
        )
        resumed = self.channel.request("resume_session", self.base)
        assert resumed["result"]["requires_observation"], resumed
        rejected = self.action({"kind": "move", "x": 2, "y": 2}, state=previous, success=False)
        assert "error" in rejected, rejected
        current = self.observe()
        assert current["input_generation"] != previous["input_generation"]
        assert "Shift held: false" in current["text"]
        assert "Left button held: false" in current["text"]
        self.assert_isolated()

    def window_generation(self):
        previous = self.observe(0)
        next_window = self.observe(1)
        assert previous["input_generation"] != next_window["input_generation"]
        stale = self.action({"kind": "move", "x": 2, "y": 2}, 0, state=previous, success=False)
        assert stale.get("error", {}).get("data", {}).get("kind") == "stale_input_generation", stale
        self.action({"kind": "move", "x": 2, "y": 2}, 0)
        self.assert_isolated()

    def window_movement(self):
        self.action({"kind": "move", "x": 100, "y": 100})
        until(self.visible_cursors, lambda values: not values)
        previous = self.observe()
        before = len(rows(self.logs["Background Target"]))
        os.kill(self.app.pid, signal.SIGUSR2)
        until(lambda: (self.directory / "Background Target-moved").exists(), bool)
        rejected = self.action({"kind": "move", "x": 2, "y": 2}, state=previous, success=False)
        assert rejected.get("error", {}).get("data", {}).get("kind") == "stale_element", rejected
        assert len(rows(self.logs["Background Target"])) == before
        current = self.observe()
        assert current["bounds"] != previous["bounds"], (previous, current)
        self.action({"kind": "move", "x": 20, "y": 20}, state=current)
        visible = until(self.visible_cursors, bool)
        assert len(visible) == 1, visible
        assert abs(visible[0]["x"] - current["bounds"]["x"] - 17) < 1, (visible, current)
        assert abs(visible[0]["y"] - current["bounds"]["y"] - 17) < 1, (visible, current)
        # The second target window covers this point in the first window. The
        # software cursor must hide even when the occluding window has the same PID.
        self.action({"kind": "move", "x": 100, "y": 100})
        until(self.visible_cursors, lambda values: not values)
        self.assert_isolated()

    def crash_recovery(self):
        self.action({"kind": "key_down", "key": "shift"})
        if not self.expect_global_button_limit:
            self.action({"kind": "drag_step", "phase": "begin", "x": 100, "y": 200})
        before = len(rows(self.logs["Background Target"]))
        os.kill(self.channel.process.pid, signal.SIGKILL)
        self.channel.process.wait(timeout=5)
        recovered = until(
            lambda: rows(self.logs["Background Target"])[before:],
            lambda values: (
                self.expect_global_button_limit or any(value["type"] == 2 for value in values)
            )
            and any(value["type"] == 12 and not value["flags"] & 131072 for value in values),
        )
        if self.content != "electron":
            assert all(value["frontmost_pid"] == self.guard.pid for value in recovered), recovered
        self.assert_isolated()

    def target_exit(self):
        self.action({"kind": "key_down", "key": "shift"})
        self.action({"kind": "drag_step", "phase": "begin", "x": 100, "y": 200})
        previous = self.observe()
        self.app.terminate()
        self.app.wait(timeout=5)

        def released_without_cleanup():
            self.channel.request("capabilities", {})
            return [
                event
                for event in self.channel.input_telemetry
                if event["context"]["session_id"] == self.base["session_id"]
                and event["input_generation"] == previous["input_generation"]
                and event["phase"] == "paused"
                and not event["held_keys"]
                and not event["held_buttons"]
            ]

        until(released_without_cleanup, bool)
        rejected = self.action({"kind": "move", "x": 2, "y": 2}, state=previous, success=False)
        assert "error" in rejected, rejected
        ended = self.channel.request("end_session", self.base)
        assert "result" in ended, ended
        self.assert_isolated()

    def close(self):
        stop(self.monitor)
        if hasattr(self, "monitor_output"):
            self.monitor_output.close()
        self.channel.close()
        for process in reversed(self.processes):
            stop(process)


def main():
    if "--allow-own-fixture-input" not in os.sys.argv:
        raise SystemExit("Pass --allow-own-fixture-input to reserve disposable fixture windows")
    with tempfile.TemporaryDirectory(
        prefix="memstack-background-", dir=os.environ.get("TMPDIR")
    ) as directory:
        fixture = BackgroundFixture(Path(directory))
        try:
            fixture.setup()
            fixture.text_input()
            fixture.context_menu()
            fixture.mouse_and_modifiers()
            fixture.other_application_input()
            fixture.secure_input_limit()
            fixture.window_generation()
            fixture.window_movement()
            fixture.pause_and_generation()
            if "--fault-target-exit" in os.sys.argv:
                fixture.target_exit()
            else:
                fixture.crash_recovery()
            print(
                "BACKGROUND_INPUT_COMPATIBILITY_OK_WITH_GLOBAL_BUTTON_LIMIT"
                if fixture.expect_global_button_limit
                else "BACKGROUND_INPUT_FIXTURE_OK"
            )
        except Exception:
            for name, path in fixture.logs.items():
                print(name, json.dumps(rows(path)[-20:], ensure_ascii=False), flush=True)
            for name, path in fixture.dom_logs.items():
                if rows(path):
                    print(name + " DOM", json.dumps(rows(path)[-20:]), flush=True)
            if hasattr(fixture, "system_log"):
                print("SYSTEM_STATES", rows(fixture.system_log), flush=True)
            print("INPUT_TELEMETRY", fixture.channel.input_telemetry[-5:], flush=True)
            raise
        finally:
            fixture.close()


if __name__ == "__main__":
    main()
