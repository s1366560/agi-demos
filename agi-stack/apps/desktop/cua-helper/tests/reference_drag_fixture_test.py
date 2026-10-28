"""Observe an external native drag in owned fixture windows.

This diagnostic does not generate drag input. After READY, a native controller
drags horizontally 90 logical pixels inside window 2's marked drag region, then
sends done on stdin. Derive the start point from the current native screenshot.
Both the actual page result and independent system-state changes are reported.
"""

import json
import os
import tempfile
from pathlib import Path

from background_fixture_test import BackgroundFixture, rows


def main():
    if "--allow-own-fixture-input" not in os.sys.argv:
        raise SystemExit("Pass --allow-own-fixture-input to reserve disposable fixture windows")
    directory = Path(
        tempfile.mkdtemp(prefix="memstack-reference-drag-", dir=os.environ.get("TMPDIR"))
    )
    fixture = BackgroundFixture(directory)
    try:
        fixture.setup()
        observed = fixture.observe(1)
        baseline = fixture.system_state()
        offsets = {name: len(rows(path)) for name, path in fixture.logs.items()}
        dom_offset = len(rows(fixture.dom_logs["Background Target"]))
        system_offset = len(rows(fixture.system_log))
        print(
            "REFERENCE_DRAG_READY",
            json.dumps(
                {
                    "directory": str(directory),
                    "target_pid": fixture.app.pid,
                    "window": fixture.windows[1],
                    "bounds": observed["bounds"],
                }
            ),
            flush=True,
        )
        assert input() == "done", "Send done after the external native drag finishes"
        dom = rows(fixture.dom_logs["Background Target"])[dom_offset:]
        target = rows(fixture.logs["Background Target"])[offsets["Background Target"] :]
        guard = rows(fixture.logs["Foreground Guard"])[offsets["Foreground Guard"] :]
        system = rows(fixture.system_log)[system_offset:]
        # The external controller is real user input from our helper's point of
        # view and can pause its session. Keep the raw observations even then;
        # a rejected observation must not discard the diagnostic or imply that
        # the target completed the drag.
        observation_error = None
        drag_completed = None
        try:
            state = fixture.observe(1)
            drag_completed = "drag complete:90,0" in state["text"]
        except AssertionError as error:
            observation_error = str(error)
        result = {
            "content": fixture.content,
            "drag_completed": drag_completed,
            "observation_error": observation_error,
            "baseline": baseline,
            "system_changes": system,
            "final_system_state": fixture.system_state(),
            "target_events": target,
            "dom_events": dom,
            "guard_events": guard,
            "native_status": fixture.channel.notifications,
        }
        (directory / "result.json").write_text(json.dumps(result, indent=2))
        print("REFERENCE_DRAG_RESULT", json.dumps(result), flush=True)
    finally:
        fixture.close()


if __name__ == "__main__":
    main()
