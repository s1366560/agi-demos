"""Run both full client builds in a disposable checkout without business package sources."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path("agi-stack/apps/desktop")
WEB = Path("web")
SOURCES = (WEB, DESKTOP, Path("agi-stack/packages"), Path("shared"), Path("sdk"))


def copy_client_sources(destination: Path) -> None:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *SOURCES],
        cwd=ROOT,
    )
    for raw in paths.split(b"\0"):
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        source = ROOT / relative
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            link = os.readlink(source)
            if Path(link).is_absolute() or not (target.parent / link).resolve().is_relative_to(
                destination
            ):
                raise ValueError(f"Source link leaves the build context: {relative}")
            target.symlink_to(link)
        else:
            shutil.copyfile(source, target)
    for package in (Path("."), WEB, DESKTOP):
        (destination / package / "node_modules").symlink_to(
            ROOT / package / "node_modules", target_is_directory=True
        )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="memstack-full-clients-") as directory:
        checkout = Path(directory).resolve()
        copy_client_sources(checkout)
        results = []
        for package, script in ((WEB, "build:full"), (DESKTOP, "build:electron:full")):
            print(f"Building {package} with {script}", flush=True)
            result = subprocess.run(["npm", "run", script], cwd=checkout / package, check=False)
            results.append(result.returncode)
        return int(any(results))


if __name__ == "__main__":
    raise SystemExit(main())
