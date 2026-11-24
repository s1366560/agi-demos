"""Build the full clients without business package sources, optionally keeping them for UI tests."""

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path("agi-stack/apps/desktop")
WEB = Path("web")
SOURCES = (
    WEB,
    DESKTOP,
    Path("agi-stack/packages"),
    Path("shared"),
    Path("sdk"),
    Path("package.json"),
    Path("pnpm-lock.yaml"),
    Path("pnpm-workspace.yaml"),
)


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


def install_dependencies(destination: Path) -> None:
    # Reinstall from each host's lockfile. Linking node_modules to the development
    # checkout lets its absolute pnpm shims and transformed module caches leak in.
    for package in (Path("."), WEB, DESKTOP):
        subprocess.run(
            [
                "corepack",
                "pnpm",
                "install",
                "--frozen-lockfile",
                "--prefer-offline",
                "--config.enableGlobalVirtualStore=false",
            ],
            cwd=destination / package,
            check=True,
        )


def build_clients(checkout: Path) -> int:
    copy_client_sources(checkout)
    install_dependencies(checkout)
    results = []
    for package, script in ((WEB, "build:full"), (DESKTOP, "build:electron:full")):
        print(f"Building {package} with {script}", flush=True)
        result = subprocess.run(["npm", "run", script], cwd=checkout / package, check=False)
        results.append(result.returncode)
    return int(any(results))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-root",
        type=Path,
        help="Create a new directory and retain the isolated checkout and both build outputs.",
    )
    args = parser.parse_args()
    if args.build_root is not None:
        checkout = args.build_root.resolve()
        try:
            checkout.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            parser.error(f"Choose a new build directory: {checkout}")
        print(f"Retaining builds in {checkout}", flush=True)
        return build_clients(checkout)
    with tempfile.TemporaryDirectory(prefix="memstack-full-clients-") as directory:
        return build_clients(Path(directory).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
