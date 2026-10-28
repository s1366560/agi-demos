"""Real Space/lock acceptance using owned native apps and read-only OS observation.

The driver never changes Spaces or locks/unlocks the machine. After READY, an
operator performs the requested transition; synthetic notifications do not pass.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from background_fixture_test import ROOT, BackgroundFixture, rows, stop, until


def error_kind(response):
    return response.get("error", {}).get("data", {}).get("kind")


class CompatibilityFixture(BackgroundFixture):
    def __init__(self, directory, timeout, operator_gates=False):
        super().__init__(directory)
        self.timeout = timeout
        self.operator_gates = operator_gates
        self.compatibility_monitor = None
        self.identity_monitor = None

    def setup(self):
        super().setup()
        binary = self.directory / "compatibility-monitor"
        subprocess.run(
            [
                "swiftc",
                "-parse-as-library",
                str(ROOT / "tests/NativeCompatibilityMonitor.swift"),
                "-o",
                str(binary),
            ],
            check=True,
        )
        # The process's native CGWindow number is independent of the helper's
        # opaque window ID. A delivered click gives the exact target number.
        state = self.observe()
        field = int(re.search(r"\[(\d+)\] AXTextField", state["text"])[1])
        self.action({"kind": "click", "element_index": field}, state=state)
        events = until(
            lambda: rows(self.logs["Background Target"]),
            lambda values: any(value["type"] == 1 for value in values),
        )
        window = next(value["window"] for value in reversed(events) if value["type"] == 1)
        self.compatibility_log = self.directory / "compatibility-state.jsonl"
        self.compatibility_output = self.compatibility_log.open("w")
        self.compatibility_monitor = subprocess.Popen(
            [str(binary), str(self.app.pid), str(window), str(self.channel.process.pid)],
            stdout=self.compatibility_output,
        )
        until(lambda: rows(self.compatibility_log), bool)
        identity_binary = self.directory / "window-identity-monitor"
        subprocess.run(
            [
                "swiftc",
                "-parse-as-library",
                str(ROOT / "tests/WindowIdentityMonitor.swift"),
                "-o",
                str(identity_binary),
            ],
            check=True,
        )
        self.identity_output = (self.directory / "window-identity.jsonl").open("w")
        self.identity_monitor = subprocess.Popen(
            [str(identity_binary), str(self.app.pid)], stdout=self.identity_output
        )

    def status(self):
        assert self.compatibility_monitor.poll() is None, "compatibility observer exited"
        return rows(self.compatibility_log)[-1]

    def session_records(self, values, offset=0, generation=None):
        return [
            value
            for value in values[offset:]
            if value.get("context", {}).get("session_id") == self.base["session_id"]
            and (generation is None or value.get("input_generation") == generation)
        ]

    def observe_after_space_switch(self, status_offset, telemetry_offset):
        generation = self.channel.bindings[self.base["session_id"]]["input_generation"]
        response = self.channel.request(
            "get_app_state",
            {**self.target, "window_id": self.windows[0]["window_id"], "disable_diff": True},
        )
        if "result" in response:
            return response["result"]
        assert error_kind(response) == "user_stopped_session", response

        def user_pause():
            self.channel.request("capabilities", {})
            telemetry = self.session_records(
                self.channel.input_telemetry, telemetry_offset, generation
            )
            statuses = self.session_records(self.channel.notifications, status_offset)
            if not telemetry or not statuses:
                return False
            latest, status = telemetry[-1], statuses[-1]
            if latest["phase"] not in {"paused", "stopped", "error"}:
                return False
            assert latest["phase"] == "paused" and latest.get("reason") == "user_input_detected", (
                latest
            )
            if status["phase"] not in {"paused", "stopped", "error"}:
                return False
            assert status["phase"] == "paused" and status["user_initiated"], status
            return not latest["held_keys"] and not latest["held_buttons"]

        assert until(user_pause, bool)
        resumed = self.channel.request("resume_session", self.base)
        assert "result" in resumed and resumed["result"]["requires_observation"], resumed
        print("SPACE_SETUP_USER_PAUSE_RESUMED", flush=True)
        return self.observe()

    def ready(self, stage):
        (self.directory / stage).touch()
        print(json.dumps({"stage": stage, "directory": str(self.directory)}), flush=True)

    def wait_before_space_input(self, stage):
        if self.operator_gates:
            self.ready(stage)
            until(
                lambda: (self.directory / f"{stage}_CONTINUE").exists(), bool, timeout=self.timeout
            )
        previous = self.system_state()
        stable_since = time.monotonic()

        def quiet():
            nonlocal previous, stable_since
            current = self.system_state()
            if (
                current != previous
                or current["held_key_codes"]
                or any(
                    current[key]
                    for key in ("left", "right", "middle", "shift", "command", "option", "control")
                )
            ):
                previous, stable_since = current, time.monotonic()
            return time.monotonic() - stable_since >= 1

        until(quiet, bool, timeout=self.timeout)

    def space(self):
        # Expose an actual part of the background target before switching away.
        os.kill(self.app.pid, signal.SIGUSR2)
        until(lambda: (self.directory / "Background Target-moved").exists(), bool)
        self.action({"kind": "move", "x": 20, "y": 20})
        until(self.visible_cursors, bool)
        self.action({"kind": "press_key", "key": "super+a"})
        initial = until(
            self.status,
            lambda value: value["windows_available"]
            and value["target_visible"]
            and value["cursor_count"] == 1,
        )
        status_offset = len(self.channel.notifications)
        telemetry_offset = len(self.channel.input_telemetry)
        self.ready("SPACE_SWITCH_AWAY_READY")
        away = until(
            self.status,
            lambda value: value["space_epoch"] > initial["space_epoch"]
            and value["windows_available"]
            and not value["target_visible"],
            timeout=self.timeout,
        )
        until(self.status, lambda value: value["windows_available"] and value["cursor_count"] == 0)
        self.wait_before_space_input("SPACE_INPUT_READY")
        current = self.status()
        assert current["space_epoch"] == away["space_epoch"] and not current["target_visible"], (
            current
        )
        # Reaching the Space controls can move the operator's pointer over the
        # exposed target. Respect that pause, then explicitly resume this owned
        # test session; never turn a different failure into a passing transition.
        state = self.observe_after_space_switch(status_offset, telemetry_offset)
        stable = self.system_state()
        system_offset = len(rows(self.system_log))
        guard_offset = len(rows(self.logs["Foreground Guard"]))
        expected = "Background text from another Space"
        self.action({"kind": "type_text", "text": expected}, state=state)
        observed = until(self.observe, lambda value: f'value="{expected}"' in value["text"])
        assert observed["screenshot"], observed
        time.sleep(0.3)
        assert self.system_state() == stable, (stable, self.system_state())
        assert all(value == stable for value in rows(self.system_log)[system_offset:])
        assert not rows(self.logs["Foreground Guard"])[guard_offset:]
        assert self.status()["space_epoch"] == away["space_epoch"], self.status()
        current = self.status()
        assert current["windows_available"] and not current["target_visible"]
        assert current["cursor_count"] == 0
        status_offset = len(self.channel.notifications)
        telemetry_offset = len(self.channel.input_telemetry)
        self.ready("SPACE_SWITCH_BACK_READY")
        returned = until(
            self.status,
            lambda value: value["space_epoch"] > away["space_epoch"]
            and value["windows_available"]
            and value["target_visible"],
            timeout=self.timeout,
        )
        assert not returned["screen_locked"]
        self.wait_before_space_input("SPACE_RETURN_INPUT_READY")
        state = self.observe_after_space_switch(status_offset, telemetry_offset)
        assert f'value="{expected}"' in state["text"]
        stable = self.system_state()
        system_offset = len(rows(self.system_log))
        guard_offset = len(rows(self.logs["Foreground Guard"]))
        self.action({"kind": "move", "x": 20, "y": 20}, state=state)
        until(
            self.status,
            lambda value: value["windows_available"]
            and value["target_visible"]
            and value["cursor_count"] == 1,
        )
        assert self.status()["space_epoch"] == returned["space_epoch"], self.status()
        assert self.system_state() == stable, (stable, self.system_state())
        assert all(value == stable for value in rows(self.system_log)[system_offset:])
        assert not rows(self.logs["Foreground Guard"])[guard_offset:]
        print("NATIVE_SPACE_BACKGROUND_INPUT_OK", flush=True)

    def lock_screen(self):
        status_offset = len(self.channel.notifications)
        self.action({"kind": "key_down", "key": "shift"})
        self.action({"kind": "drag_step", "phase": "begin", "x": 100, "y": 200})
        previous = until(
            self.observe,
            lambda value: "Shift held: true" in value["text"]
            and "Left button held: true" in value["text"],
        )
        generation = previous["input_generation"]

        def held():
            self.channel.request("capabilities", {})
            values = self.session_records(self.channel.input_telemetry, generation=generation)
            assert not any(
                value["phase"] in {"paused", "stopped"}
                for value in self.session_records(self.channel.notifications, status_offset)
            ), self.channel.notifications[status_offset:]
            return values and values[-1]["held_keys"] == [56] and values[-1]["held_buttons"] == [0]

        assert until(held, bool)
        target_offset = len(rows(self.logs["Background Target"]))
        telemetry_offset = len(self.channel.input_telemetry)
        stop_reasons = {"screen_locked", "console_session_inactive", "display_sleep"}

        def validate_hold_transition():
            self.channel.request("capabilities", {})
            statuses = self.session_records(self.channel.notifications, status_offset)
            assert not any(value["phase"] == "paused" for value in statuses), statuses
            telemetry = self.session_records(
                self.channel.input_telemetry, telemetry_offset, generation
            )
            for value in telemetry:
                if value["phase"] == "stopped":
                    assert value.get("reason") in stop_reasons, value
                    assert not value["held_keys"] and not value["held_buttons"], value
                else:
                    assert value["phase"] not in {"paused", "error"}, value
                    assert value["held_keys"] == [56] and value["held_buttons"] == [0], value
            return telemetry

        def real_lock():
            validate_hold_transition()
            status = self.status()
            return status["session_available"] and status["screen_locked"]

        self.ready("REAL_LOCK_READY")
        until(real_lock, bool, timeout=self.timeout)
        capabilities = self.channel.request("capabilities", {})
        assert capabilities["result"]["screen_locked"], capabilities

        def stopped():
            return [
                value
                for value in validate_hold_transition()
                if value["phase"] == "stopped"
                and not value["held_keys"]
                and not value["held_buttons"]
                and value.get("reason") in stop_reasons
            ]

        assert until(stopped, bool), self.channel.input_telemetry
        until(
            self.status,
            lambda value: value["session_available"]
            and value["screen_locked"]
            and value["windows_available"]
            and value["cursor_count"] == 0,
        )
        rejected = self.action({"kind": "move", "x": 2, "y": 2}, state=previous, success=False)
        assert error_kind(rejected) in {"screen_locked", "user_stopped_session"}, rejected
        self.ready("REAL_UNLOCK_READY")
        until(
            self.status,
            lambda value: value["session_available"]
            and not value["screen_locked"]
            and value["on_console"],
            timeout=self.timeout,
        )
        for method in ("resume_session", "reset_session"):
            rejected = self.channel.request(method, self.base)
            expected_kind = (
                "session_not_paused" if method == "resume_session" else "user_stopped_session"
            )
            assert error_kind(rejected) == expected_kind, rejected
        rejected = self.action({"kind": "move", "x": 2, "y": 2}, state=previous, success=False)
        assert error_kind(rejected) == "user_stopped_session", rejected
        released = until(
            lambda: [
                value
                for value in rows(self.logs["Background Target"])[target_offset:]
                if value["source_pid"] == self.channel.process.pid
            ],
            lambda values: any(value["type"] == 2 for value in values)
            and any(value["type"] == 12 and not value["flags"] & 131072 for value in values),
        )
        assert released
        self.new_session_after_unlock(previous)
        print("NATIVE_REAL_LOCK_RELEASE_AND_NEW_SESSION_OK", flush=True)

    def read_after_unlock(self, method, params):
        deadline = time.monotonic() + 10
        while True:
            response = self.channel.request(method, params)
            if "result" in response:
                return response
            error = response.get("error", {}).get("data", {})
            assert (
                error.get("kind") == "accessibility_unavailable"
                and error.get("ax_error") == -25204
                and error.get("attribute") == "AXWindows"
            ), response
            assert time.monotonic() < deadline, response
            time.sleep(0.1)

    def new_session_after_unlock(self, previous):
        self.base = {"session_id": "after-real-unlock"}
        started = self.channel.request("begin_session", {**self.base, "input_mode": "background"})
        assert "result" in started, started
        self.target = {**self.target, **self.base}
        resolved = self.channel.request("resolve_app", {**self.base, "app": self.target["app"]})
        assert "result" in resolved, resolved
        self.target["expected_identity_digest"] = resolved["result"]["identity_digest"]
        listed = until(
            lambda: self.read_after_unlock("list_windows", self.target),
            lambda value: len(value.get("result", {}).get("windows", [])) == 2,
            timeout=10,
        )
        self.windows = sorted(listed["result"]["windows"], key=lambda window: window["title"])
        current = self.read_after_unlock(
            "get_app_state",
            {**self.target, "window_id": self.windows[0]["window_id"], "disable_diff": True},
        )["result"]
        assert current["input_generation"], current
        assert current["input_generation"] != previous["input_generation"], (previous, current)
        assert "Shift held: false" in current["text"]
        assert "Left button held: false" in current["text"]
        self.action({"kind": "move", "x": 20, "y": 20}, state=current)

    def close(self):
        stop(self.identity_monitor)
        stop(self.compatibility_monitor)
        if hasattr(self, "identity_output"):
            self.identity_output.close()
        if hasattr(self, "compatibility_output"):
            self.compatibility_output.close()
        super().close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-own-fixture-input", action="store_true", required=True)
    parser.add_argument("--scenario", choices=("space", "lock"), required=True)
    parser.add_argument("--wait-seconds", type=int, default=300)
    parser.add_argument(
        "--operator-gates",
        action="store_true",
        help="Wait for <stage>_CONTINUE files after Space input READY messages.",
    )
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    os.environ["CUA_FIXTURE_CONTENT"] = "appkit"
    if args.scenario == "space":
        os.environ["CUA_FIXTURE_EXPOSE_MOVED_WINDOW"] = "1"
    directory = args.directory or Path(
        tempfile.mkdtemp(prefix="memstack-native-compat-", dir=os.environ.get("TMPDIR"))
    )
    directory.mkdir(parents=True, exist_ok=True)
    fixture = CompatibilityFixture(directory, args.wait_seconds, args.operator_gates)
    try:
        fixture.setup()
        if args.scenario == "space":
            fixture.space()
        else:
            fixture.lock_screen()
    except Exception:
        print("NATIVE_STATUS", json.dumps(fixture.channel.notifications[-6:]), flush=True)
        print("INPUT_TELEMETRY", json.dumps(fixture.channel.input_telemetry[-3:]), flush=True)
        raise
    finally:
        (directory / "native-status.json").write_text(json.dumps(fixture.channel.notifications))
        (directory / "input-telemetry.json").write_text(json.dumps(fixture.channel.input_telemetry))
        fixture.close()


if __name__ == "__main__":
    main()
