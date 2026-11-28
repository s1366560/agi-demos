"""Build the default Rust host in a checkout containing no official business packages."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STACK = ROOT / "agi-stack"


def main() -> None:
    files = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard", "-z", "--", "agi-stack", "shared"],
        cwd=ROOT,
    )
    with tempfile.TemporaryDirectory(prefix="memstack-sidecar-host-") as temporary:
        stage = Path(temporary)
        for raw in files.split(b"\0"):
            if not raw:
                continue
            relative = Path(os.fsdecode(raw))
            source = ROOT / relative
            if not source.is_file() or source.is_symlink():
                continue
            if (
                relative.parts[:5] == ("agi-stack", "apps", "desktop", "sidecar", "src")
                and relative.name == "legacy_http.rs"
            ):
                continue
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        subprocess.run(
            [
                "cargo",
                "build",
                "--locked",
                "--no-default-features",
                "-p",
                "agistack-desktop-sidecar",
            ],
            cwd=stage / "agi-stack",
            env={**os.environ, "CARGO_TARGET_DIR": str(STACK / "target")},
            check=True,
        )


if __name__ == "__main__":
    main()
