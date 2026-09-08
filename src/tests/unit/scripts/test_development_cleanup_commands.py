"""Keep routine cleanup separate from data-destroying maintenance commands."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def planned_commands(target: str) -> str:
    return subprocess.run(
        ["make", "--dry-run", "--no-print-directory", target],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_routine_clean_preserves_database_volumes_and_logs() -> None:
    commands = planned_commands("clean")
    assert "docker compose" not in commands
    assert "rm -rf logs" not in commands
    assert "find . " not in commands
    assert "--group rust-incremental --apply" in commands


def test_inventory_has_no_apply_and_full_rebuild_cleanup_is_explicit() -> None:
    assert "--apply" not in planned_commands("disk-usage")
    assert "--group rust-build --apply" in planned_commands("clean-build-cache")


def test_explicit_data_reset_commands_remain_separate() -> None:
    assert "docker compose down -v" in planned_commands("clean-docker")
    assert "rm -rf logs" in planned_commands("clean-logs")


def test_web_cleanup_preserves_shared_dependency_cache(tmp_path: Path) -> None:
    shared_cache = tmp_path / "shared-dependencies/.vite"
    shared_cache.mkdir(parents=True)
    sentinel = shared_cache / "keep.txt"
    sentinel.write_text("active dependency cache", encoding="utf-8")
    checkout = tmp_path / "checkout"
    (checkout / "web/dist").mkdir(parents=True)
    (checkout / "web/node_modules").symlink_to(shared_cache.parent, target_is_directory=True)
    subprocess.run(
        ["make", "--no-print-directory", "-f", str(ROOT / "Makefile"), "clean-web"],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    assert sentinel.read_text(encoding="utf-8") == "active dependency cache"
    assert not (checkout / "web/dist").exists()


def test_web_cleanup_refuses_linked_source_directory(tmp_path: Path) -> None:
    outside = tmp_path / "other-checkout"
    (outside / "dist").mkdir(parents=True)
    sentinel = outside / "dist/keep.txt"
    sentinel.write_text("other checkout output", encoding="utf-8")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "web").symlink_to(outside, target_is_directory=True)
    result = subprocess.run(
        ["make", "--no-print-directory", "-f", str(ROOT / "Makefile"), "clean-web"],
        cwd=checkout,
        check=False,
        capture_output=True,
    )
    assert result.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "other checkout output"
