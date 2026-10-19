"""Verify fixture packaging and native icon lookup without starting the application."""

import plistlib
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from fixture_bundle import ICON_NAME, build_fixture


class FixtureBundleTests(unittest.TestCase):
    def test_fixture_has_sealed_code_drawn_icon_recognized_by_native_icon_services(self):
        with tempfile.TemporaryDirectory(prefix="memstack-cua-fixture-icon-") as directory:
            bundle = Path(directory) / "ComputerUseFixture.app"
            binary = build_fixture(bundle)
            info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
            self.assertEqual(info["CFBundleIconFile"], ICON_NAME)
            self.assertTrue(binary.is_file())
            icon = (bundle / "Contents/Resources" / ICON_NAME).read_bytes()
            self.assertEqual(icon[:4], b"icns")
            self.assertEqual(struct.unpack(">I", icon[4:8])[0], len(icon))
            subprocess.run(
                ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)], check=True
            )
            verified = subprocess.check_output(
                [str(Path(directory) / "fixture-icon-builder"), "--verify-bundle", str(bundle)],
                text=True,
            )
            self.assertIn("native_bundle_icon_verified", verified)


if __name__ == "__main__":
    unittest.main()
