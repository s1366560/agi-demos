#!/usr/bin/env python3
"""Native clipboard and private-root recovery on an isolated Xvfb display."""

import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import linux_native_smoke as smoke


# Fault injection and recovery assertions share one live clipboard owner and helper session.
def exercise(executable, fault, user_copy):  # noqa: PLR0915
    with tempfile.TemporaryDirectory(prefix="memstack-resource-fixture-") as directory:
        root = Path(directory)
        app = subprocess.Popen([sys.executable, smoke.__file__, "--fixture", str(root / "value")])
        client = None
        counter = 0

        def clipboard(kind, **arguments):
            nonlocal counter
            counter += 1
            command = root / "clipboard-command.json"
            temporary = command.with_suffix(".tmp")
            temporary.write_text(json.dumps({"id": counter, "kind": kind, **arguments}))
            temporary.replace(command)
            for _ in range(200):
                reply = root / "clipboard-reply.json"
                if reply.exists():
                    result = json.loads(reply.read_text())
                    if result["id"] == counter:
                        return result
                time.sleep(0.01)
            raise TimeoutError("fixture clipboard response deadline exceeded")

        try:
            time.sleep(0.3)
            client = smoke.Client(executable)
            guardian = int(
                Path(f"/proc/{client.process.pid}/task/{client.process.pid}/children")
                .read_text()
                .split()[0]
            )
            private = list(Path("/tmp").glob(f"memstack-cua-owned-{guardian}-*"))
            assert len(private) == 2, private
            for path in private:
                assert path.stat().st_mode & 0o777 == 0o700
                (path / "incomplete-owned-file").write_text("isolated fixture")
            original = clipboard("get")["text"]
            assert original == "ORIGINAL_NATIVE_中文🙂", original
            client.call("clipboard_write", {"text": "OWNED_FIXTURE_COPY", "format": "html"})
            assert clipboard("get")["text"] == "OWNED_FIXTURE_COPY"
            if user_copy:
                clipboard("set", text="USER_COPY_AFTER_HELPER")
                if user_copy == "clear":
                    clipboard("clear")
            if fault.startswith("guardian_"):
                os.kill(guardian, signal.SIGSTOP if fault.endswith("SIGSTOP") else signal.SIGKILL)
            else:
                client.process.send_signal(signal.SIGSTOP if fault == "SIGSTOP" else signal.SIGKILL)
            client.process.wait(timeout=8)
            expected = (
                None
                if user_copy == "clear"
                else "USER_COPY_AFTER_HELPER"
                if user_copy
                else original
            )
            for _ in range(200):
                restored = clipboard("get")["text"]
                if restored == expected and all(not path.exists() for path in private):
                    break
                time.sleep(0.01)
            assert restored == expected, (fault, user_copy, restored)
            assert all(not path.exists() for path in private)
            # A restored X11 selection needs its independent owner until this new copy.
            clipboard("set", text="FIXTURE_RELEASES_RESTORED_SELECTION")
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "platform": "isolated_linux_x11",
                        "fault": fault,
                        "user_copy_preserved": user_copy,
                        "original_restored": not user_copy,
                        "private_roots_removed": len(private),
                        "parent_cannot_resume": client.process.poll() is not None,
                        "actual_recording_started": False,
                    }
                )
            )
        finally:
            if client and client.process.poll() is None:
                client.process.send_signal(signal.SIGCONT)
                client.close()
            app.terminate()
            app.wait(timeout=5)


def exercise_grab_fault(executable):
    with tempfile.TemporaryDirectory(prefix="memstack-clipboard-grab-fixture-") as directory:
        root = Path(directory)
        app = subprocess.Popen([sys.executable, smoke.__file__, "--fixture", str(root / "value")])
        helper = None
        try:
            time.sleep(0.3)
            helper = subprocess.Popen(
                [executable, "--native-clipboard-grab-fixture"], stdout=subprocess.PIPE, text=True
            )
            assert select.select([helper.stdout], [], [], 5)[0], (
                "native grab acknowledgement missing"
            )
            assert helper.stdout.readline().strip() == "native_grab_acknowledged"
            guardian = int(
                Path(f"/proc/{helper.pid}/task/{helper.pid}/children").read_text().split()[0]
            )
            os.kill(guardian, signal.SIGKILL)
            helper.wait(timeout=3)
            # This roundtrip would time out if a retained old client still held GrabServer.
            subprocess.run(["xdpyinfo"], stdout=subprocess.DEVNULL, check=True, timeout=2)
            command = root / "clipboard-command.json"
            temporary = command.with_suffix(".tmp")
            temporary.write_text(json.dumps({"id": 1, "kind": "get"}))
            temporary.replace(command)
            reply = root / "clipboard-reply.json"
            for _ in range(200):
                if reply.exists():
                    break
                time.sleep(0.01)
            assert reply.exists(), "other native selection client no longer responds"
            value = json.loads(reply.read_text())
            assert value["text"] == "ORIGINAL_NATIVE_中文🙂", value
            temporary.write_text(
                json.dumps({"id": 2, "kind": "set", "text": "USER_COPY_AFTER_NATIVE_GRAB"})
            )
            temporary.replace(command)
            for _ in range(200):
                if json.loads(reply.read_text())["id"] == 2:
                    break
                time.sleep(0.01)
            assert json.loads(reply.read_text())["id"] == 2
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "platform": "isolated_linux_x11",
                        "fault": "guardian_SIGKILL_with_native_server_grab_ack",
                        "server_roundtrip_after_fault": True,
                        "original_restored": True,
                        "user_copy_after_fault": True,
                        "actual_recording_started": False,
                    }
                )
            )
        finally:
            if helper and helper.poll() is None:
                helper.kill()
                helper.wait(timeout=3)
            app.terminate()
            app.wait(timeout=5)


if __name__ == "__main__":
    if sys.argv[1] == "--inside":
        manager = subprocess.Popen(
            ["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            for fault in ("SIGKILL", "SIGSTOP", "guardian_SIGKILL", "guardian_SIGSTOP"):
                for user_copy in (False, True, "clear"):
                    exercise(sys.argv[2], fault, user_copy)
            exercise_grab_fault(sys.argv[2])
        finally:
            manager.terminate()
            manager.wait(timeout=5)
    else:
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
