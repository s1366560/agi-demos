#!/usr/bin/env python3
"""check-i18n-gettext.py

Scan backend source for user-facing string literals that escape the
``gettext`` wrapper. Today we focus on the highest-leverage entry point:

    raise HTTPException(..., detail="literal string", ...)

A baseline file (``scripts/i18n-gettext-baseline.txt``) records every
violation that exists today so the script can be wired into CI without
forcing a flag-day fix of the long tail. New violations introduced after
the baseline cause a non-zero exit.

Usage
-----
    python scripts/check-i18n-gettext.py            # check against baseline
    python scripts/check-i18n-gettext.py --update   # rewrite baseline
    python scripts/check-i18n-gettext.py --list     # print all current
                                                    # violations, ignore
                                                    # baseline (exit 0)

The scanner uses Python's ``ast`` module so f-strings, concatenations,
variable detail values, and ``_(...)``-wrapped calls are all correctly
classified.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOT = REPO_ROOT / "src"
BASELINE_PATH = Path(__file__).resolve().parent / "i18n-gettext-baseline.txt"

SCAN_SKIP_PARTS = {"tests", "test", "__pycache__"}


def _detail_arg(call: ast.Call) -> ast.expr | None:
    """Return the ``detail=`` keyword argument node if present."""
    for kw in call.keywords:
        if kw.arg == "detail":
            return kw.value
    return None


def _is_gettext_wrapped(node: ast.expr) -> bool:
    """True if ``node`` is a ``_()`` / ``gettext()`` / ``ngettext()`` call."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in {"_", "gettext", "ngettext", "pgettext"}
    if isinstance(func, ast.Attribute):
        return func.attr in {"gettext", "ngettext", "pgettext"}
    return False


def _is_string_literal(node: ast.expr) -> bool:
    """True if ``node`` is a string constant or an f-string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.JoinedStr):  # f-string
        return True
    return False


def _is_httpexception_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == "HTTPException"
    if isinstance(func, ast.Attribute):
        return func.attr == "HTTPException"
    return False


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in SCAN_ROOT.rglob("*.py"):
        if any(part in SCAN_SKIP_PARTS for part in path.relative_to(SCAN_ROOT).parts):
            continue
        files.append(path)
    return files


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (lineno, snippet) violations for ``path``."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    violations: list[tuple[int, str]] = []
    lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_httpexception_call(node):
            continue
        detail = _detail_arg(node)
        if detail is None:
            continue
        if not _is_string_literal(detail):
            continue
        if _is_gettext_wrapped(detail):
            continue
        # f-string: also OK if every formatted-value piece is unwrapped
        # but the literal segments contain user-visible English — flag it.
        lineno = detail.lineno
        snippet = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
        violations.append((lineno, snippet))
    return violations


def _format_key(rel_path: Path, lineno: int) -> str:
    """Stable identifier for a violation (path + line)."""
    return f"{rel_path.as_posix()}:{lineno}"


def _collect_all_violations() -> list[tuple[str, str]]:
    """Return sorted list of (key, snippet)."""
    out: list[tuple[str, str]] = []
    for file_path in _iter_python_files():
        rel = file_path.relative_to(REPO_ROOT)
        for lineno, snippet in _scan_file(file_path):
            out.append((_format_key(rel, lineno), snippet))
    out.sort(key=lambda item: item[0])
    return out


def _load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    return {
        line.strip()
        for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _write_baseline(violations: list[tuple[str, str]]) -> None:
    header = (
        "# scripts/i18n-gettext-baseline.txt\n"
        "# Pre-existing HTTPException(detail=...) violations not yet wrapped\n"
        "# with gettext (_()). Maintained by scripts/check-i18n-gettext.py.\n"
        "# New entries must NOT be added; instead, wrap the detail string\n"
        "# with _() and remove the existing entry from this file.\n"
    )
    body = "\n".join(key for key, _snippet in violations)
    BASELINE_PATH.write_text(header + "\n" + body + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the baseline file with the current violations",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list all current violations and exit 0 (ignores baseline)",
    )
    args = parser.parse_args(argv)

    violations = _collect_all_violations()

    if args.list:
        for key, snippet in violations:
            print(f"{key}: {snippet}")
        print(f"\nTotal: {len(violations)} violation(s).")
        return 0

    if args.update:
        _write_baseline(violations)
        print(
            f"Updated baseline at {BASELINE_PATH.relative_to(REPO_ROOT)} "
            f"with {len(violations)} entry/entries."
        )
        return 0

    baseline = _load_baseline()
    current_keys = {key for key, _snippet in violations}
    new_violations = [
        (key, snippet) for key, snippet in violations if key not in baseline
    ]
    removed = baseline - current_keys

    if new_violations:
        print("New i18n-gettext violations detected:")
        for key, snippet in new_violations:
            print(f"  {key}: {snippet}")
        print()
        print(
            "Wrap the detail string with gettext: "
            "raise HTTPException(detail=_(\"...\"))."
        )
        print("If the change is intentional and translation is not desired,")
        print(
            f"run `python {Path(__file__).relative_to(REPO_ROOT)} --update` "
            "after careful review."
        )
        return 1

    if removed:
        print(f"Note: {len(removed)} baseline entry/entries no longer apply:")
        for key in sorted(removed):
            print(f"  - {key}")
        print(
            f"Run `python {Path(__file__).relative_to(REPO_ROOT)} --update` "
            "to refresh the baseline."
        )

    print(f"OK: {len(violations)} known violation(s), 0 new.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
