"""Human-assisted input isolation; never generates the foreground user's input.

Run only after arranging a one-minute physical keyboard/mouse session. The
operator uses Foreground Guard while the helper operates Background Target.
The script waits for an explicit newline before starting the measurement.
"""

import json
import os
import re
import tempfile
import time
from pathlib import Path

from background_fixture_test import BackgroundFixture, rows, stop, until


# Keep setup, the human measurement, and frozen result checks in one ordered lifecycle.
def main():  # noqa: PLR0915
    if "--allow-own-fixture-input" not in os.sys.argv:
        raise SystemExit("Pass --allow-own-fixture-input after arranging physical participation")
    with tempfile.TemporaryDirectory(
        prefix="memstack-physical-input-", dir=os.environ.get("TMPDIR")
    ) as directory:
        fixture = BackgroundFixture(Path(directory))
        try:
            fixture.setup()
            fixture.text_input(verify_isolation=False)
            # Put the background caret in its first field before the user starts.
            state = fixture.observe()
            field = next(
                line
                for line in state["text"].splitlines()
                if "AXTextField" in line and 'value="后台中文输入 😀"' in line
            )
            element = int(re.search(r"\[(\d+)\]", field).group(1))
            fixture.action({"kind": "click", "element_index": element}, state=state)
            fixture.action({"kind": "press_key", "key": "super+a"})
            fixture.action({"kind": "type_text", "text": "background:"})
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "guard_pid": fixture.guard.pid,
                        "target_pid": fixture.app.pid,
                        "duration_seconds": 60,
                    }
                ),
                flush=True,
            )
            input("Send a newline when the operator is ready: ")
            print("WAITING_FOR_FOREGROUND_GUARD", flush=True)
            until(
                fixture.system_state, lambda s: s["frontmost_pid"] == fixture.guard.pid, timeout=120
            )
            started = time.monotonic()
            samples = []
            guard_start = len(rows(fixture.logs["Foreground Guard"]))
            system_start = len(rows(fixture.system_log))
            target_start = len(rows(fixture.logs["Background Target"]))
            print("PHYSICAL_INPUT_MEASUREMENT_STARTED", flush=True)
            while time.monotonic() - started < 60:
                before = fixture.system_state()
                fixture.action({"kind": "key_down", "key": "b"})
                fixture.action({"kind": "key_up", "key": "b"})
                fixture.action({"kind": "move", "x": 120, "y": 210})
                fixture.action({"kind": "move", "x": 180, "y": 250})
                after = fixture.system_state()
                samples.append({"before": before, "after": after})
                time.sleep(0.25)
            expected = "background:" + "b" * len(samples)
            final_state = fixture.observe()
            ended = fixture.channel.request("stop_session", fixture.base)
            assert "result" in ended, ended
            stop(fixture.monitor)
            system = rows(fixture.system_log)[system_start:]
            guard = rows(fixture.logs["Foreground Guard"])[guard_start:]
            target = rows(fixture.logs["Background Target"])[target_start:]
            print("PHYSICAL_INPUT_MEASUREMENT_STOPPED", flush=True)
            assert system and all(s["frontmost_pid"] == fixture.guard.pid for s in system), system
            assert len({(s["x"], s["y"]) for s in system}) > 5, (
                "no physical mouse movement observed"
            )
            assert any(s["shift"] for s in system), "no physical Shift hold observed"
            assert any(s["before"]["shift"] and s["after"]["shift"] for s in samples), (
                "Shift was not held across a background action"
            )
            keys = [e for e in target if e["type"] in (10, 11, 12)]
            assert [e["type"] for e in keys] == [10, 11] * len(samples), keys
            assert all(
                e.get("key_code") == 11
                and e["characters"] == "b"
                and not e["flags"] & 131072
                and e["source_pid"] == fixture.channel.process.pid
                for e in keys
            ), keys
            assert any(
                "AXTextField" in line and f'value="{expected}"' in line
                for line in final_state["text"].splitlines()
            ), final_state["text"]
            physical_keys = [e for e in guard if e["type"] == 10]
            assert physical_keys, "no foreground physical typing observed"
            assert any(e["flags"] & 131072 for e in physical_keys), (
                "no foreground Shift typing observed"
            )
            assert all(e["source_pid"] != fixture.channel.process.pid for e in guard), guard
            until(fixture.system_state, lambda s: not s["shift"] and not s["left"], timeout=15)
            print(
                json.dumps(
                    {
                        "status": "PHYSICAL_INPUT_ISOLATION_OK",
                        "background_key_events": len(keys),
                        "background_iterations": len(samples),
                        "foreground_key_events": len(physical_keys),
                        "system_state_changes": len(system),
                        "concurrent_shift_intervals": sum(
                            s["before"]["shift"] and s["after"]["shift"] for s in samples
                        ),
                    }
                ),
                flush=True,
            )
        finally:
            fixture.close()


if __name__ == "__main__":
    main()
