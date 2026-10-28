"""Opt-in focus activation and post-stop keyboard routing in disposable apps.

The activation control deliberately changes the foreground app. This verifies
that the helper pauses and releases input, never that it prevented activation.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from background_fixture_test import ROOT, BackgroundFixture, rows, until


def run(fixture):
    fixture.setup()
    probe = fixture.directory / "focus-probe"
    subprocess.run(
        [
            "swiftc",
            "-parse-as-library",
            str(ROOT / "tests/BackgroundFocusProbe.swift"),
            "-o",
            str(probe),
        ],
        check=True,
    )

    def activate(pid):
        subprocess.run([str(probe), "activate", str(pid)], check=True)
        until(fixture.system_state, lambda value: value["frontmost_pid"] == pid)

    # An unbound negative control proves this request really steals focus.
    activate(fixture.app.pid)
    activate(fixture.guard.pid)
    fixture.action({"kind": "key_down", "key": "shift"})
    fixture.action({"kind": "drag_step", "phase": "begin", "x": 100, "y": 200})
    before = len(rows(fixture.logs["Background Target"]))
    activate(fixture.app.pid)
    released = until(
        lambda: rows(fixture.logs["Background Target"])[before:],
        lambda values: any(value["type"] == 2 for value in values)
        and any(value["type"] == 12 and not value["flags"] & 131072 for value in values),
    )
    assert released
    fixture.channel.request("capabilities", {})
    assert any(
        value["phase"] == "paused" and value.get("reason") == "target_became_foreground"
        for value in fixture.channel.input_telemetry
    ), fixture.channel.input_telemetry
    assert any(
        value["phase"] == "paused" and value["user_initiated"] is False
        for value in fixture.channel.notifications
    ), fixture.channel.notifications
    assert fixture.system_state()["frontmost_pid"] == fixture.app.pid
    print("TARGET_ACTIVATION_OBSERVED_AND_INPUT_PAUSED", flush=True)

    # Changing focus back is explicit test setup after the failure assertion.
    # The helper itself must never steal focus back to conceal this boundary.
    stopped = fixture.channel.request("stop_session", fixture.base)
    assert "result" in stopped, stopped
    activate(fixture.guard.pid)
    baseline = fixture.system_state()
    target_offset = len(rows(fixture.logs["Background Target"]))
    guard_offset = len(rows(fixture.logs["Foreground Guard"]))
    subprocess.run([str(probe), "key", str(fixture.guard.pid)], check=True)
    delivered = until(
        lambda: rows(fixture.logs["Foreground Guard"])[guard_offset:],
        lambda values: any(
            value["type"] == 11 and value.get("source_tag") == -92 for value in values
        ),
    )
    key_events = [value for value in delivered if value.get("source_tag") == -92]
    assert [value["type"] for value in key_events] == [10, 11], key_events
    assert all(value.get("key_code") == 0 for value in key_events), key_events
    assert not any(
        value.get("source_tag") == -92
        for value in rows(fixture.logs["Background Target"])[target_offset:]
    )
    until(fixture.system_state, lambda value: value == baseline)
    print("STOPPED_GUARD_KEYBOARD_ROUTING_OK", flush=True)


def main():
    if "--allow-own-fixture-input" not in os.sys.argv:
        raise SystemExit("Pass --allow-own-fixture-input to reserve disposable fixture windows")
    os.environ["CUA_FIXTURE_CONTENT"] = "appkit"
    with tempfile.TemporaryDirectory(
        prefix="memstack-background-focus-", dir=os.environ.get("TMPDIR")
    ) as directory:
        fixture = BackgroundFixture(Path(directory))
        try:
            run(fixture)
        finally:
            fixture.close()


if __name__ == "__main__":
    main()
