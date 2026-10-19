"""Reject invalid menu-driver identities before accessing UI; no GUI app is launched."""

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "darwin", "macOS libproc identity checks")
class NativeMenuDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="memstack-menu-driver-negative-")
        cls.root = Path(cls.temporary.name)
        cls.driver = cls.root / "native-menu-driver"
        source = Path(__file__).with_name("native_menu_driver.swift")
        subprocess.run(
            ["swiftc", "-parse-as-library", str(source), "-o", str(cls.driver)],
            check=True,
            capture_output=True,
            text=True,
        )
        bundle = cls.root / "Memstack Computer Use.app"
        cls.executable = bundle / "Contents/MacOS/cua-helper"
        cls.executable.parent.mkdir(parents=True)
        (bundle / "Contents/Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleIdentifier": "ai.agistack.desktop.cua-helper",
                }
            )
        )
        fixture = cls.root / "metadata_only.c"
        fixture.write_text("#include <unistd.h>\nint main(void) { for (;;) pause(); }\n")
        subprocess.run(
            ["clang", str(fixture), "-o", str(cls.executable)],
            check=True,
            capture_output=True,
            text=True,
        )
        # This process has no AppKit, windows, UI, IPC, permissions, or input API.
        cls.process = subprocess.Popen(
            [str(cls.executable)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.temporary.cleanup()

    def invoke(self, command, *arguments, executable=None, pid=None):
        result = subprocess.run(
            [
                str(self.driver),
                command,
                "--pid",
                str(pid or self.process.pid),
                "--executable",
                str(executable or self.executable),
                *arguments,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.stderr, "")
        return result.returncode, json.loads(result.stdout)

    def test_identity_reads_exact_process_start_without_ui(self):
        code, payload = self.invoke("identity")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["pid"], self.process.pid)
        self.assertEqual(Path(payload["result"]["executable"]).resolve(), self.executable.resolve())
        seconds, microseconds = map(int, payload["result"]["start"].split(":"))
        self.assertGreater(seconds, 0)
        self.assertGreaterEqual(microseconds, 0)
        self.assertLess(microseconds, 1_000_000)

    def test_non_helper_target_is_rejected_before_ui(self):
        code, payload = self.invoke("capture", executable="/usr/bin/true")
        self.assertEqual(code, 1)
        self.assertEqual(payload["code"], "target-not-helper")

    def test_missing_start_is_rejected_before_ui(self):
        code, payload = self.invoke("capture")
        self.assertEqual(code, 1)
        self.assertEqual(payload["code"], "usage")
        self.assertIn("--start", payload["message"])

    def test_stale_start_is_rejected_before_ui(self):
        code, payload = self.invoke("capture", "--start", "0:0")
        self.assertEqual(code, 1)
        self.assertEqual(payload["code"], "process-replaced")

    def test_same_bundle_path_with_wrong_pid_is_rejected_before_ui(self):
        code, payload = self.invoke("capture", "--start", "0:0", pid=os.getpid())
        self.assertEqual(code, 1)
        self.assertEqual(payload["code"], "identity-mismatch")


if __name__ == "__main__":
    unittest.main()
