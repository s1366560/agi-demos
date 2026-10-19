"""Build a signed, disposable fixture bundle with an explicit code-drawn app icon."""

import plistlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICON_NAME = "ComputerUseFixture.icns"


def build_fixture(bundle: Path) -> Path:
    binary = bundle / "Contents/MacOS/ComputerUseFixture"
    resources = bundle / "Contents/Resources"
    binary.parent.mkdir(parents=True)
    resources.mkdir(parents=True)
    (bundle / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "ai.memstack.cua.fixture",
                "CFBundleExecutable": binary.name,
                "CFBundleName": "Computer Use Fixture",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "2",
                "CFBundleIconFile": ICON_NAME,
                "LSUIElement": False,
            }
        )
    )
    subprocess.run(
        ["swiftc", str(ROOT / "NativeFixture/main.swift"), "-o", str(binary)], check=True
    )
    painter = bundle.parent / "fixture-icon-builder"
    subprocess.run(
        ["swiftc", str(ROOT / "NativeFixture/Icon.swift"), "-o", str(painter)], check=True
    )
    iconset = bundle.parent / "Fixture.iconset"
    subprocess.run([str(painter), str(iconset)], check=True)
    subprocess.run(
        [
            "/usr/bin/iconutil",
            "--convert",
            "icns",
            "--output",
            str(resources / ICON_NAME),
            str(iconset),
        ],
        check=True,
    )
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)], check=True)
    return binary
