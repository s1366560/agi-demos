"""Real signed watchdog + named fixture pasteboards. No general clipboard or input."""

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


# Keep watchdog failure and lease recovery assertions in one ordered resource lifecycle.
def main():  # noqa: C901, PLR0915
    with tempfile.TemporaryDirectory(
        prefix="memstack-cua-resource-tests-", dir=os.environ.get("TMPDIR")
    ) as directory:
        supplied = os.environ.get("MEMSTACK_CUA_RECOVERY_TEST_BINARY")
        binary = Path(supplied) if supplied else Path(directory) / "recovery-fixture"
        if not supplied:
            sources = sorted(
                path for path in (ROOT / "Sources").glob("*.swift") if path.name != "main.swift"
            )
            subprocess.run(
                [
                    "swiftc",
                    "-swift-version",
                    "5",
                    "-O",
                    "-o",
                    str(binary),
                    *map(str, sources),
                    str(ROOT / "tests/RecoveryFixture.swift"),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "codesign",
                    "--force",
                    "--sign",
                    "-",
                    "--identifier",
                    "ai.memstack.cua.recovery-fixture",
                    str(binary),
                ],
                check=True,
                capture_output=True,
            )

        def run(*arguments, code=0):
            value = subprocess.run(
                [str(binary), *arguments], capture_output=True, text=True, timeout=5
            )
            assert value.returncode == code, value.stderr
            return value.stdout.strip()

        def start(*arguments):
            process = subprocess.Popen(
                [str(binary), *arguments],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            path = process.stdout.readline().strip()
            root = Path(path)
            assert path and root.is_absolute() and root.is_dir(), process.stderr.read()
            return process, root

        def settle(root):
            deadline = time.monotonic() + 5
            while root.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not root.exists(), "private crash resources remain"
            assert run("lease-probe") == "available"

        def changed_tmpdir_probe(code):
            # Environment-controlled TMPDIR must not partition the login
            # desktop mutex into independent helper profiles.
            value = subprocess.run(
                [str(binary), "lease-probe"],
                capture_output=True,
                env={**os.environ, "TMPDIR": directory},
                timeout=5,
            )
            assert value.returncode == code, value.stderr

        def close(process):
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()

        def kill_watchdog(process):
            inventory = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, check=True
            )
            children = []
            for line in inventory.stdout.splitlines():
                fields = line.strip().split(None, 2)
                if (
                    len(fields) == 3
                    and fields[1] == str(process.pid)
                    and fields[2] == str(binary) + " --input-watchdog"
                ):
                    children.append(int(fields[0]))
            assert len(children) == 1, "owned watchdog child not unique"
            os.kill(children[0], signal.SIGKILL)

        run("lease-probe")
        board = "memstack-cua-test-" + str(uuid4())
        try:
            for local_copy in (False, True):
                run("seed", board)
                process, root = start("write", board)
                assert run("lease-probe", code=3) == "device_busy"
                changed_tmpdir_probe(3)
                if local_copy:
                    run("local-copy", board)
                process.kill()
                process.wait(timeout=5)
                close(process)
                settle(root)
                run("check", board, "fixture-local-copy" if local_copy else "fixture-original")
            for operation, local_copy in (
                ("write", False),
                ("write-nested", False),
                ("write-nested", True),
            ):
                run("seed", board)
                process, root = start(operation, board)
                kill_watchdog(process)
                if local_copy:
                    run("local-copy", board)
                process.stdin.close()
                process.wait(timeout=5)
                assert process.returncode == 0, process.stderr.read()
                process.stdout.close()
                process.stderr.close()
                settle(root)
                run("check", board, "fixture-local-copy" if local_copy else "fixture-original")
            process, root = start("lease-holder")
            assert run("lease-probe", code=3) == "device_busy"
            process.stdin.close()
            process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()
            settle(root)
            changed_tmpdir_probe(0)
            process, root = start("lease-holder")
            process.send_signal(signal.SIGSTOP)
            try:
                assert run("lease-probe", code=3) == "device_busy"
                process.wait(timeout=13)
                assert process.returncode == -signal.SIGKILL
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                close(process)
            settle(root)
            print(
                "CUA_RECOVERY_OK: worker/watchdog SIGKILL clipboard rollback, nested mirror recovery, later local copy preserved, cross-profile OS lease busy/release, SIGSTOP bounded kill, private artifact cleanup"
            )
        finally:
            run("drop", board)


if __name__ == "__main__":
    main()
