"""Safety and filesystem integration tests for the explicit build-artifact cleaner."""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts/dev_disk.py"
SPEC = importlib.util.spec_from_file_location("dev_disk", SCRIPT)
assert SPEC and SPEC.loader
disk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(disk)
RELATIVE = "agi-stack/target/debug/incremental"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path.resolve() / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def artifact(repo: Path, relative: str = RELATIVE) -> Path:
    path = repo / relative
    path.mkdir(parents=True)
    (path / "object.o").write_bytes(b"x" * 8192)
    return path


def selected(result: dict, relative: str = RELATIVE) -> dict:
    return next(row for row in result["candidates"] if row["path"] == relative)


def idle(_root: Path, _relative: str) -> list[str]:
    return []


def test_default_report_never_mutates_or_inspects_processes(repo: Path) -> None:
    path = artifact(repo)
    before = (path / "object.o").read_bytes()

    def forbidden(*_args: object) -> list[str]:
        raise AssertionError("dry-run must not inspect processes")

    result = disk.run(repo, inspector=forbidden)
    assert result["mode"] == "dry-run"
    assert selected(result)["action"] == "would-remove"
    assert selected(result)["allocated_bytes"] >= len(before)
    assert (path / "object.o").read_bytes() == before


def test_apply_removes_only_allowlisted_artifacts_and_preserves_dirty_data(repo: Path) -> None:
    path = artifact(repo)
    preserved = [
        ".cache/avernet-bcs/test-data/bcs.db",
        ".cache/avernet-bcs/test-data/bcs.db-wal",
        "logs/server.log",
        "node_modules/library.js",
        "agi-stack/target/debug/server",
        ".cache/avernet-bcs/rustup/toolchain",
        "src/dirty.py",
        ".cache/unknown/object.o",
    ]
    for name in preserved:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("keep")
    subprocess.run(["git", "-C", str(repo), "add", "src/dirty.py"], check=True)
    (repo / "src/dirty.py").write_text("dirty source")
    result = disk.run(repo, "rust-incremental", True, idle)
    assert selected(result)["action"] == "removed"
    assert not path.exists()
    assert all((repo / name).exists() for name in preserved)
    assert (repo / "src/dirty.py").read_text() == "dirty source"


def test_tracked_descendant_blocks_even_when_dirty(repo: Path) -> None:
    path = artifact(repo)
    subprocess.run(["git", "-C", str(repo), "add", RELATIVE], check=True)
    (path / "object.o").write_bytes(b"dirty")
    result = disk.run(repo, apply=True, inspector=idle)
    assert selected(result)["action"] == "blocked"
    assert (path / "object.o").read_bytes() == b"dirty"


@pytest.mark.parametrize("component", ["root", "ancestor", "candidate", "child"])
def test_symlink_at_any_level_never_traversed(repo: Path, component: str) -> None:
    outside = repo.parent / "outside"
    outside.mkdir()
    (outside / "sentinel").write_text("safe")
    if component == "root":
        alias = repo.parent / "alias"
        alias.symlink_to(repo, target_is_directory=True)
        with pytest.raises(OSError):
            disk.run(alias, apply=True, inspector=idle)
    else:
        path = repo / RELATIVE
        target = {"ancestor": repo / "agi-stack", "candidate": path, "child": path / "link"}[
            component
        ]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(outside, target_is_directory=True)
        result = disk.run(repo, apply=True, inspector=idle)
        assert selected(result)["action"] == "blocked"
        assert target.is_symlink()
    assert (outside / "sentinel").read_text() == "safe"


def test_unknown_group_and_arbitrary_root_rejected(repo: Path) -> None:
    with pytest.raises(ValueError):
        disk.run(repo, "../logs", True, idle)
    subdir = repo / "nested"
    subdir.mkdir()
    with pytest.raises(disk.UnsafePath):
        disk.run(subdir, apply=True, inspector=idle)


def test_active_files_and_unavailable_inspection_block_removal(repo: Path) -> None:
    path = artifact(repo)
    for inspector in [
        lambda *_: ["open artifact pid=123"],
        lambda *_: (_ for _ in ()).throw(disk.UnsafePath("inspection unavailable")),
    ]:
        result = disk.run(repo, apply=True, inspector=inspector)
        assert selected(result)["action"] == "blocked"
        assert path.exists()


def test_change_during_process_inspection_blocks_removal(repo: Path) -> None:
    path = artifact(repo)

    def change(*_args: object) -> list[str]:
        (path / "new.o").write_text("new compilation")
        return []

    result = disk.run(repo, apply=True, inspector=change)
    assert selected(result)["action"] == "blocked"
    assert (path / "object.o").exists()
    assert (path / "new.o").exists()


def test_candidate_replaced_after_inventory_cannot_redirect_deletion(repo: Path) -> None:
    path = artifact(repo)
    row, snapshot = disk.inspect(repo, RELATIVE, set(), set())
    assert row["action"] == "would-remove"
    old = path.with_name("preserved")
    path.rename(old)
    path.mkdir()
    (path / "sentinel").write_text("replacement")
    with pytest.raises(disk.UnsafePath):
        disk.apply_candidate(repo, RELATIVE, snapshot, idle)
    assert (path / "sentinel").exists()
    assert (old / "object.o").exists()


def test_hardlinked_bytes_counted_once_and_external_link_survives(repo: Path) -> None:
    path = artifact(repo)
    os.link(path / "object.o", path / "second.o")
    os.link(path / "object.o", repo / "external.o")
    result = disk.run(repo)
    row = selected(result)
    expected = path.stat().st_blocks * 512 + (path / "object.o").stat().st_blocks * 512
    assert row["allocated_bytes"] == expected
    assert row["hardlinked_files"] == 2
    assert row["reclaim_estimate_bytes"] < row["allocated_bytes"]
    disk.run(repo, apply=True, inspector=idle)
    assert (repo / "external.o").read_bytes() == b"x" * 8192


def test_process_inspector_blocks_compilers_and_open_candidate(repo: Path) -> None:
    responses = [
        subprocess.CompletedProcess([], 0, "321 1 /usr/bin/rustc\n", ""),
        subprocess.CompletedProcess([], 0, f"p654\nn{repo / RELATIVE}/object.o\n", ""),
    ]
    with (
        patch.object(disk.shutil, "which", return_value="/usr/bin/tool"),
        patch.object(disk.subprocess, "run", side_effect=responses),
    ):
        blockers = disk.process_blockers(repo, RELATIVE)
    assert any("321" in blocker for blocker in blockers)
    assert any("654" in blocker for blocker in blockers)


def test_process_inspection_failure_is_closed(repo: Path) -> None:
    with patch.object(disk.shutil, "which", return_value=None), pytest.raises(disk.UnsafePath):
        disk.process_blockers(repo, RELATIVE)
    responses = [
        subprocess.CompletedProcess([], 0, "", ""),
        subprocess.CompletedProcess([], 1, "", "permission denied"),
    ]
    with (
        patch.object(disk.shutil, "which", return_value="/usr/bin/tool"),
        patch.object(disk.subprocess, "run", side_effect=responses),
        pytest.raises(disk.UnsafePath),
    ):
        disk.process_blockers(repo, RELATIVE)


def test_cli_requires_explicit_group_for_apply(repo: Path) -> None:
    path = artifact(repo)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo), "--apply"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert path.exists()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["mode"] == "dry-run"
    assert path.exists()


def test_incremental_group_preserves_deps_and_all_groups_preserve_binaries(repo: Path) -> None:
    incremental = artifact(repo)
    deps = artifact(repo, RELATIVE.replace("incremental", "deps"))
    legacy = artifact(repo, "third_party/avernet-bcs/target/debug/incremental")
    disk.run(repo, "rust-incremental", True, idle)
    assert not incremental.exists() and not legacy.exists()
    assert deps.exists()
    disk.run(repo, "rust-build", True, idle)
    assert not deps.exists()


@pytest.mark.parametrize(
    "filename", ["unexpected.db", "bcs.db-wal", "database.sqlite3", "server.log"]
)
def test_database_or_logs_inside_artifact_block_entire_candidate(repo: Path, filename: str) -> None:
    path = artifact(repo)
    (path / filename).write_text("protected")
    result = disk.run(repo, apply=True, inspector=idle)
    assert selected(result)["action"] == "blocked"
    assert (path / filename).read_text() == "protected"
    assert (path / "object.o").exists()


def test_process_inspector_ignores_own_held_fd_but_not_other_process(repo: Path) -> None:
    output = f"p{os.getpid()}\nn{repo / RELATIVE}\np999999\nn{repo / RELATIVE}/object.o\n"
    responses = [
        subprocess.CompletedProcess([], 0, "", ""),
        subprocess.CompletedProcess([], 0, output, ""),
    ]
    with (
        patch.object(disk.shutil, "which", return_value="/usr/bin/tool"),
        patch.object(disk.subprocess, "run", side_effect=responses),
    ):
        assert disk.process_blockers(repo, RELATIVE) == ["open artifact pid=999999"]


def test_tracking_added_during_process_inspection_blocks_removal(repo: Path) -> None:
    path = artifact(repo)

    def track(*_args: object) -> list[str]:
        subprocess.run(["git", "-C", str(repo), "add", RELATIVE], check=True)
        return []

    result = disk.run(repo, apply=True, inspector=track)
    assert selected(result)["action"] == "blocked"
    assert (path / "object.o").exists()


@pytest.mark.parametrize("target", ["all", "legacy-workspace-core"])
def test_real_cli_apply_in_disposable_git_repository(repo: Path, target: str) -> None:
    relative = RELATIVE if target == "all" else "third_party/avernet-bcs/target/debug/incremental"
    path = artifact(repo, relative)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(repo),
            "--group",
            "rust-incremental",
            "--target",
            target,
            "--apply",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    report = json.loads(result.stdout)
    row = selected(report, relative)
    if (
        result.returncode
        and row["action"] == "blocked"
        and any(
            reason in row.get("reason", "")
            for reason in ["lsof", "ps", "active standalone compiler", "timed out"]
        )
    ):
        assert path.exists()
        pytest.skip("host process inspection prevents disposable apply: " + row["reason"])
    assert result.returncode == 0, report
    assert row["action"] == "removed"
    assert not path.exists()


@pytest.mark.parametrize("mode", ["LOCK_SH", "LOCK_EX"])
def test_cargo_lock_held_by_separate_process_blocks_apply(repo: Path, mode: str) -> None:
    path = artifact(repo)
    code = "import fcntl,sys; f=open(sys.argv[1],'a+'); fcntl.flock(f, getattr(fcntl,sys.argv[2])); print('locked',flush=True); sys.stdin.read()"
    with subprocess.Popen(
        [sys.executable, "-c", code, str(path.parent / ".cargo-lock"), mode],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdout.readline().strip() == "locked"
        try:
            result = disk.run(repo, apply=True, inspector=idle)
            assert selected(result)["action"] == "blocked"
            assert "Cargo profile lock" in selected(result)["reason"]
            assert (path / "object.o").exists()
        finally:
            process.communicate("", timeout=5)
    assert (path.parent / ".cargo-lock").exists()


def test_profile_lock_held_during_rescan_inspection_and_removal(repo: Path) -> None:
    path = artifact(repo)
    original = disk.delete_tree
    original_scan = disk.scan_tree
    scans = []
    checks = []

    def verify_lock(*_args: object) -> list[str]:
        code = "import fcntl,sys; f=open(sys.argv[1]); fcntl.flock(f,fcntl.LOCK_SH|fcntl.LOCK_NB)"
        probe = subprocess.run(
            [sys.executable, "-c", code, str(path.parent / ".cargo-lock")],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert probe.returncode != 0 and "BlockingIOError" in probe.stderr
        checks.append(True)
        return []

    def remove(*args: object) -> None:
        verify_lock()
        original(*args)

    def scan(*args: object) -> dict:
        if scans:
            verify_lock()
        scans.append(True)
        return original_scan(*args)

    with (
        patch.object(disk, "delete_tree", side_effect=remove),
        patch.object(disk, "scan_tree", side_effect=scan),
    ):
        result = disk.run(repo, apply=True, inspector=verify_lock)
    assert selected(result)["action"] == "removed"
    assert len(checks) == 4
    with (path.parent / ".cargo-lock").open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("link", ["symbolic", "hard"])
def test_linked_profile_lock_is_refused(repo: Path, link: str) -> None:
    path = artifact(repo)
    other = repo / "user-data"
    other.write_text("untouched")
    target = path.parent / ".cargo-lock"
    if link == "symbolic":
        target.symlink_to(other)
    else:
        os.link(other, target)
    assert selected(disk.run(repo, apply=True, inspector=idle))["action"] == "blocked"
    assert (path / "object.o").exists() and other.read_text() == "untouched"


def test_real_offline_cargo_waits_for_cleaner_profile_lock(repo: Path) -> None:
    cargo = shutil.which("cargo")
    if not cargo:
        pytest.skip("Cargo unavailable")
    path = artifact(repo)
    (repo / "Cargo.toml").write_text(
        '[package]\nname="lock-probe"\nversion="0.1.0"\nedition="2021"\n[lib]\npath="lib.rs"\n'
    )
    (repo / "lib.rs").write_text("pub fn value() -> u8 { 1 }\n")
    parent = disk.open_directory(path.parent)
    lock = disk.acquire_profile_lock(parent)
    try:
        command = [
            cargo,
            "check",
            "--offline",
            "--manifest-path",
            str(repo / "Cargo.toml"),
            "--target-dir",
            str(repo / "agi-stack/target"),
        ]
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        ) as process:
            try:
                process.communicate(timeout=2)
                pytest.fail("Cargo unexpectedly bypassed the profile lock")
            except subprocess.TimeoutExpired:
                process.terminate()
                _, errors = process.communicate(timeout=5)
                assert "file lock" in errors, errors
    finally:
        os.close(lock)
        os.close(parent)
    assert (path / "object.o").exists()


def test_explicit_legacy_target_preserves_fresh_current_caches(repo: Path) -> None:
    current = artifact(repo)
    canonical = artifact(repo, ".cache/avernet-bcs/target/debug/deps")
    legacy = artifact(repo, "third_party/avernet-bcs/target/debug/deps")
    result = disk.run(repo, "rust-build", True, idle, target="legacy-workspace-core")
    assert not legacy.exists()
    assert current.exists() and canonical.exists()
    assert all(
        row["path"].startswith("third_party/avernet-bcs/target/") for row in result["candidates"]
    )
    with pytest.raises(ValueError):
        disk.run(repo, target="../logs")


@pytest.mark.parametrize("phase", ["inventory", "apply"])
def test_candidate_on_different_device_is_never_deleted(repo: Path, phase: str) -> None:
    path = artifact(repo)
    _, snapshot = disk.inspect(repo, RELATIVE, set(), set())
    real_fstat = disk.os.fstat
    inode = path.stat().st_ino

    def mounted(fd: int) -> os.stat_result:
        info = real_fstat(fd)
        if info.st_ino == inode:
            fields = list(info)
            fields[2] = info.st_dev + 1
            return os.stat_result(fields)
        return info

    with patch.object(disk.os, "fstat", side_effect=mounted):
        if phase == "inventory":
            row, _ = disk.inspect(repo, RELATIVE, set(), set())
            assert row["action"] == "blocked"
            assert "different filesystem" in row["reason"]
        else:
            with pytest.raises(disk.UnsafePath, match="different filesystem"):
                disk.apply_candidate(repo, RELATIVE, snapshot, idle)
    assert (path / "object.o").exists()


def test_cargo_tree_is_coordinated_but_standalone_compiler_and_open_files_block(repo: Path) -> None:
    processes = "100 1 /bin/cargo\n101 100 /bin/rustc\n102 101 /bin/clang\n200 1 /bin/rustc\n"
    responses = [
        subprocess.CompletedProcess([], 0, processes, ""),
        subprocess.CompletedProcess([], 0, f"p101\nn{repo / RELATIVE}/object.o\n", ""),
    ]
    with (
        patch.object(disk.shutil, "which", return_value="/usr/bin/tool"),
        patch.object(disk.subprocess, "run", side_effect=responses),
    ):
        blockers = disk.process_blockers(repo, RELATIVE)
    assert blockers == ["active standalone compiler pid=200 name=rustc", "open artifact pid=101"]


def test_cargo_waiting_on_our_profile_lock_does_not_abort_inspection(repo: Path) -> None:
    path = artifact(repo)
    parent = disk.open_directory(path.parent)
    lock = disk.acquire_profile_lock(parent)
    try:
        responses = [
            subprocess.CompletedProcess([], 0, f"300 {os.getpid()} /bin/cargo\n", ""),
            subprocess.CompletedProcess([], 0, f"p{os.getpid()}\nn{path}\n", ""),
        ]
        with (
            patch.object(disk.shutil, "which", return_value="/usr/bin/tool"),
            patch.object(disk.subprocess, "run", side_effect=responses),
        ):
            assert disk.process_blockers(repo, RELATIVE) == []
    finally:
        os.close(lock)
        os.close(parent)


def test_incomplete_process_parent_metadata_fails_closed(repo: Path) -> None:
    response = subprocess.CompletedProcess([], 0, "100 /bin/cargo\n", "")
    with (
        patch.object(disk.shutil, "which", return_value="/usr/bin/tool"),
        patch.object(disk.subprocess, "run", return_value=response),
        pytest.raises(disk.UnsafePath, match="metadata"),
    ):
        disk.process_blockers(repo, RELATIVE)
