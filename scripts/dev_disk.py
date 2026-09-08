#!/usr/bin/env python3
"""Report or explicitly remove a fixed set of reproducible Rust build artifacts.

Inspection is read-only by default. Apply holds the Cargo profile lock throughout
rescan and deletion. Stop non-Cargo writers before applying. No arbitrary paths accepted.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Literal, NotRequired


type Snapshot = dict[str, os.stat_result]


class CandidateRow(TypedDict):
    path: str
    action: Literal["missing", "blocked", "would-remove", "removed"]
    allocated_bytes: int
    reclaim_estimate_bytes: int
    hardlinked_files: int
    reason: NotRequired[str]


class Report(TypedDict):
    mode: Literal["dry-run", "apply"]
    root: str
    group: str
    target: str
    allocated_bytes: int
    process_check: str
    size_note: str
    candidates: list[CandidateRow]


TARGETS = {
    "agi-stack": "agi-stack/target",
    "workspace-core": ".cache/avernet-bcs/target",
    "legacy-workspace-core": "third_party/avernet-bcs/target",
    "audit": ".cache/avernet-bcs/audit-target",
}
PARTS = ("deps", "build", ".fingerprint", "incremental")
COMPILERS = frozenset(
    {"cargo", "rustc", "rustup", "clang", "clang++", "gcc", "g++", "cc", "c++", "ld", "lld"}
)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class UnsafePath(RuntimeError):
    """The requested location cannot be safely inspected or removed."""


def candidates(group: str, target: str = "all") -> list[str]:
    """Return only declared generated directories, never an arbitrary glob."""
    if group not in ("rust-incremental", "rust-build", "all-static-artifacts"):
        raise ValueError("unknown artifact group")
    if target != "all" and target not in TARGETS:
        raise ValueError("unknown artifact target")
    roots = TARGETS.values() if target == "all" else (TARGETS[target],)
    parts = ("incremental",) if group == "rust-incremental" else PARTS
    paths = [
        f"{root}/{profile}/{part}"
        for root in roots
        for profile in ("debug", "release")
        for part in parts
    ]
    return paths


def open_directory(path: Path) -> int:
    """Open every path component without following ancestor symlinks."""
    if ".." in path.parts:
        raise UnsafePath("parent traversal is not allowed")
    absolute = Path(os.path.abspath(path))
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode


def scan_tree(fd: int, prefix: str = "") -> Snapshot:
    """Snapshot regular files and directories; reject links and special files."""
    result = {"": os.fstat(fd)} if not prefix else {}
    device = os.fstat(fd).st_dev
    for name in os.listdir(fd):
        key = f"{prefix}/{name}" if prefix else name
        if name in {"test-data", "logs", "node_modules", ".git"} or name.endswith(
            (
                ".db",
                ".db-wal",
                ".db-shm",
                ".sqlite",
                ".sqlite-wal",
                ".sqlite-shm",
                ".sqlite3",
                ".sqlite3-wal",
                ".sqlite3-shm",
                ".log",
            )
        ):
            raise UnsafePath("artifact contains a protected data filename")
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if info.st_dev != device:
            raise UnsafePath("artifact crosses a filesystem boundary")
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, DIR_FLAGS, dir_fd=fd)
            try:
                if identity(os.fstat(child)) != identity(info):
                    raise UnsafePath("directory changed during inspection")
                result[key] = info
                result.update(scan_tree(child, key))
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            result[key] = info
        else:
            raise UnsafePath("artifact contains a symlink or special file")
    return result


def tracked_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached"],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return set(result.stdout.decode("utf-8", errors="surrogateescape").split("\0")) - {""}


def standalone_compilers(output: str) -> list[str]:
    """Read structural ancestry; Cargo-coordinated writers use its profile lock."""
    blockers: list[str] = []
    tree: dict[str, tuple[str, str]] = {}
    for line in output.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
            raise UnsafePath("ps did not provide complete pid/parent/command metadata")
        tree[fields[0]] = (fields[1], Path(fields[2]).name)
    for pid, (_, command) in tree.items():
        if command not in COMPILERS:
            continue
        ancestor = pid
        visited: set[str] = set()
        while ancestor in tree and ancestor not in visited:
            visited.add(ancestor)
            parent, name = tree[ancestor]
            if name == "cargo":
                # apply_candidate already owns the profile lock. Same-profile
                # Cargo waits; other-profile Cargo can safely continue its work.
                break
            ancestor = parent
        else:
            blockers.append(f"active standalone compiler pid={pid} name={command}")
    return blockers


def process_blockers(root: Path, relative: str) -> list[str]:
    """Fail closed on unavailable inspection; never inspect process arguments."""
    lsof = shutil.which("lsof")
    ps = shutil.which("ps")
    if not lsof or not ps:
        raise UnsafePath("lsof and ps are required for apply")
    processes = subprocess.run(
        [ps, "-axo", "pid=,ppid=,comm="], capture_output=True, text=True, check=True, timeout=30
    )
    blockers = standalone_compilers(processes.stdout)
    opened = subprocess.run([lsof, "-nP", "-F", "pn"], capture_output=True, text=True, timeout=60)
    if opened.returncode != 0 or opened.stderr.strip():
        raise UnsafePath("lsof could not provide a complete open-file snapshot")
    path = str(root / relative)
    pid = "?"
    for line in opened.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n"):
            name = line[1:]
            if pid != str(os.getpid()) and (name == path or name.startswith(path + "/")):
                blockers.append(f"open artifact pid={pid}")
    return sorted(set(blockers))


def same_snapshot(before: Snapshot, after: Snapshot) -> bool:
    def record(info: os.stat_result) -> tuple[int, ...]:
        return (*identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)

    return before.keys() == after.keys() and all(
        record(before[k]) == record(after[k]) for k in before
    )


def delete_tree(fd: int, snapshot: Snapshot, prefix: str = "") -> None:
    """Delete relative to held directory descriptors, refusing replacements."""
    for name in os.listdir(fd):
        key = f"{prefix}/{name}" if prefix else name
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        expected = snapshot.get(key)
        if expected is None or identity(info) != identity(expected):
            raise UnsafePath("artifact replaced during removal")
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, DIR_FLAGS, dir_fd=fd)
            try:
                if identity(os.fstat(child)) != identity(expected):
                    raise UnsafePath("directory replaced during removal")
                delete_tree(child, snapshot, key)
            finally:
                os.close(child)
            if identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != identity(expected):
                raise UnsafePath("directory replaced before removal")
            os.rmdir(name, dir_fd=fd)
        elif stat.S_ISREG(info.st_mode):
            os.unlink(name, dir_fd=fd)
        else:
            raise UnsafePath("refusing a symlink or special file")


def require_repository_device(root: Path, fd: int) -> None:
    """Reject artifact roots or ancestors mounted from a different filesystem."""
    repository = open_directory(root)
    try:
        if os.fstat(fd).st_dev != os.fstat(repository).st_dev:
            raise UnsafePath("artifact is on a different filesystem from the repository")
    finally:
        os.close(repository)


def inspect(
    root: Path, relative: str, tracked: set[str], seen: set[tuple[int, int]]
) -> tuple[CandidateRow, Snapshot]:
    row: CandidateRow = {
        "path": relative,
        "action": "missing",
        "allocated_bytes": 0,
        "reclaim_estimate_bytes": 0,
        "hardlinked_files": 0,
    }
    snapshot: Snapshot = {}
    if any(
        p == relative or p.startswith(relative + "/") or relative.startswith(p + "/")
        for p in tracked
    ):
        row.update(action="blocked", reason="tracked path intersects artifact")
        return row, snapshot
    try:
        fd = open_directory(root / relative)
        try:
            require_repository_device(root, fd)
            snapshot = scan_tree(fd)
        finally:
            os.close(fd)
        for info in snapshot.values():
            key = (info.st_dev, info.st_ino)
            if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                row["hardlinked_files"] += 1
            if key not in seen:
                seen.add(key)
                allocated = info.st_blocks * 512
                row["allocated_bytes"] += allocated
                # External hardlinks may keep data alive: do not promise these bytes.
                if not stat.S_ISREG(info.st_mode) or info.st_nlink == 1:
                    row["reclaim_estimate_bytes"] += allocated
        row["action"] = "would-remove"
    except FileNotFoundError:
        pass
    except (OSError, UnsafePath) as exc:
        row.update(action="blocked", reason=str(exc))
    return row, snapshot


def acquire_profile_lock(parent: int) -> int:
    """Use Cargo's Unix flock, never a separate cleaner-only lock namespace."""
    # https://doc.rust-lang.org/nightly/nightly-rustc/cargo/util/flock/struct.Filesystem.html
    # https://github.com/rust-lang/cargo/pull/16887 (shared locks also require exclusion)
    lock = os.open(".cargo-lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise UnsafePath("Cargo profile lock must be a regular file without hardlinks")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UnsafePath("Cargo profile lock is held by another process") from exc
        if identity(os.stat(".cargo-lock", dir_fd=parent, follow_symlinks=False)) != identity(info):
            raise UnsafePath("Cargo profile lock changed while acquiring it")
        return lock
    except BaseException:
        os.close(lock)
        raise


def apply_candidate(
    root: Path, relative: str, snapshot: Snapshot, inspector: Callable[[Path, str], list[str]]
) -> None:
    # Hold the parent descriptor throughout; never rmtree an attacker-replaced path.
    parent = open_directory((root / relative).parent)
    name = Path(relative).name
    lock = None
    try:
        require_repository_device(root, parent)
        lock = acquire_profile_lock(parent)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if identity(current) != identity(snapshot[""]):
            raise UnsafePath("artifact root changed after inventory")
        fd = os.open(name, DIR_FLAGS, dir_fd=parent)
        try:
            require_repository_device(root, fd)
            if identity(os.fstat(fd)) != identity(current) or not same_snapshot(
                snapshot, scan_tree(fd)
            ):
                raise UnsafePath("artifact changed after inventory")
            blockers = inspector(root, relative)
            if blockers:
                raise UnsafePath("; ".join(blockers))
            # Git index and activity may have changed while inventory was running.
            tracked = tracked_paths(root)
            if any(
                p == relative or p.startswith(relative + "/") or relative.startswith(p + "/")
                for p in tracked
            ):
                raise UnsafePath("tracked path intersects artifact")
            if not same_snapshot(snapshot, scan_tree(fd)):
                raise UnsafePath("artifact changed during process inspection")
            delete_tree(fd, snapshot)
        finally:
            os.close(fd)
        if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(current):
            raise UnsafePath("artifact root replaced during removal")
        os.rmdir(name, dir_fd=parent)
    finally:
        if lock is not None:
            os.close(lock)
        os.close(parent)


def run(
    root: Path,
    group: str = "rust-build",
    apply: bool = False,
    inspector: Callable[[Path, str], list[str]] = process_blockers,
    target: str = "all",
) -> Report:
    fd = open_directory(root)
    os.close(fd)
    root = Path(os.path.abspath(root))
    if root == Path("/"):
        raise UnsafePath("filesystem root is not a repository cleanup root")
    top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    if Path(top) != root:
        raise UnsafePath("root must be the exact Git worktree root")
    tracked = tracked_paths(root)
    rows: list[CandidateRow] = []
    seen: set[tuple[int, int]] = set()
    for relative in candidates(group, target):
        row, snapshot = inspect(root, relative, tracked, seen)
        if apply and row["action"] == "would-remove":
            try:
                apply_candidate(root, relative, snapshot, inspector)
                row["action"] = "removed"
            except (OSError, UnsafePath, subprocess.SubprocessError) as exc:
                row.update(action="blocked", reason=str(exc))
        rows.append(row)
    return {
        "mode": "apply" if apply else "dry-run",
        "root": str(root),
        "group": group,
        "target": target,
        "allocated_bytes": sum(r["allocated_bytes"] for r in rows),
        "process_check": "Cargo profile flock held; process scan supplements lock; stop non-Cargo writers",
        "size_note": "allocated blocks deduplicate hardlinks; estimate excludes hardlinked files; APFS clones may reclaim less",
        "candidates": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--root", type=Path, default=Path(__file__).absolute().parents[1])
    _ = parser.add_argument(
        "--group", choices=("rust-incremental", "rust-build", "all-static-artifacts")
    )
    _ = parser.add_argument("--target", choices=("all", *TARGETS), default="all")
    _ = parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.group:
        parser.error("--apply requires an explicit --group")
    try:
        result = run(args.root, args.group or "rust-build", args.apply, target=args.target)
    except (OSError, UnsafePath, subprocess.SubprocessError, ValueError) as exc:
        print(json.dumps({"mode": "blocked", "reason": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return int(args.apply and any(r["action"] == "blocked" for r in result["candidates"]))


if __name__ == "__main__":
    raise SystemExit(main())
