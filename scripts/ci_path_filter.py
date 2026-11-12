"""Classify a diff into CI job groups. Unknown paths fail open."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def classify(paths: list[str]) -> dict[str, bool]:
    """Return which expensive CI groups a set of changed paths must run."""
    backend = False
    web = False
    agi = False
    unknown = False
    for path in paths:
        matched = False
        if path.startswith(("src/", "sdk/", "alembic/", "scripts/")) or path in {
            "pyproject.toml",
            "uv.lock",
            "pytest.ini",
            ".github/workflows/ci.yml",
            ".github/workflows/e2e.yml",
            ".github/workflows/neo4j-runtime.yml",
        }:
            backend = True
            matched = True
        if path.startswith("web/") or path in {
            ".github/workflows/ci.yml",
            ".github/workflows/e2e.yml",
        }:
            web = True
            matched = True
        if path.startswith("agi-stack/") or path == ".github/workflows/ci.yml":
            agi = True
            matched = True
        if path.startswith("docs/") or path.endswith(".md"):
            matched = True
        if not matched:
            unknown = True
    if unknown or not paths:
        return {"backend": True, "web": True, "agi": True}
    return {"backend": backend, "web": web, "agi": agi}


def _changed_paths(base: str) -> list[str]:
    if not base or not base.strip("0"):
        return []
    result = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    output = Path(os.environ.get("GITHUB_OUTPUT", ""))
    groups = classify(_changed_paths(os.environ.get("BASE_SHA", "")))
    lines = [f"{name}={'true' if enabled else 'false'}" for name, enabled in groups.items()]
    text = "\n".join(lines) + "\n"
    if output.parent.exists() and str(output):
        with output.open("a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
