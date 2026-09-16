"""Unit tests for the recorded-change revert planner and sandbox script."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from src.application.schemas.agent_run_authority import ChangeFileResponse
from src.application.services.agent.run_change_revert import (
    ChangeContentNotRecordedError,
    InvalidSelectorPathError,
    UnknownChangeSelectorError,
    apply_change_revert_exclusions,
    build_reverse_patch,
    change_revert_exclusions,
    parse_revert_script_output,
    plan_change_revert,
    render_revert_script,
    validate_selector_path,
)
from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

pytestmark = pytest.mark.unit


def _file(
    path: str,
    *,
    status: str = "modified",
    old_path: str | None = None,
    binary: bool = False,
    patch_digest: str = "digest-1",
    hunks: list[dict] | None = None,
) -> ChangeFileResponse:
    hunks = hunks if hunks is not None else [_hunk()]
    additions = sum(1 for h in hunks for line in h["lines"] if line["kind"] == "addition")
    deletions = sum(1 for h in hunks for line in h["lines"] if line["kind"] == "deletion")
    return ChangeFileResponse.model_validate(
        {
            "path": path,
            "old_path": old_path,
            "status": status,
            "additions": additions,
            "deletions": deletions,
            "binary": binary,
            "untracked": status == "untracked",
            "patch_digest": patch_digest,
            "hunks": hunks,
        }
    )


def _hunk(
    old_start: int = 1,
    new_start: int = 1,
    lines: list[dict] | None = None,
) -> dict:
    return {
        "header": f"@@ -{old_start} +{new_start} @@",
        "old_start": old_start,
        "new_start": new_start,
        "lines": lines
        or [
            {"kind": "context", "old_line": 1, "new_line": 1, "text": "alpha"},
            {"kind": "deletion", "old_line": 2, "new_line": None, "text": "beta"},
            {"kind": "addition", "old_line": None, "new_line": 2, "text": "BETA"},
            {"kind": "context", "old_line": 3, "new_line": 3, "text": "gamma"},
        ],
    }


class TestSelectorPaths:
    def test_accepts_nested_relative_path(self) -> None:
        assert validate_selector_path("src/app/main.py") == "src/app/main.py"

    @pytest.mark.parametrize(
        "path",
        ["", "/etc/passwd", "../escape", "a/../b", "./x", "a//b", "x\ry", "x\ny", "x\0y", "~/.ssh"],
    )
    def test_rejects_escape_or_control_paths(self, path: str) -> None:
        with pytest.raises(InvalidSelectorPathError):
            validate_selector_path(path)


class TestPlanChangeRevert:
    def test_whole_file_selects_all_hunks(self) -> None:
        file = _file("src/a.py", hunks=[_hunk(), _hunk(old_start=10, new_start=10)])
        plans = plan_change_revert([file], [("src/a.py", None)])
        assert plans[0].reverted_indices == (0, 1)
        assert plans[0].delete_file is False

    def test_hunk_subset_selection(self) -> None:
        file = _file("src/a.py", hunks=[_hunk(), _hunk(old_start=10, new_start=10)])
        plans = plan_change_revert([file], [("src/a.py", (1,))])
        assert plans[0].reverted_indices == (1,)
        assert len(plans[0].hunks) == 1

    def test_unknown_path_fails_closed(self) -> None:
        with pytest.raises(UnknownChangeSelectorError):
            plan_change_revert([_file("src/a.py")], [("src/missing.py", None)])

    def test_unknown_hunk_index_fails_closed(self) -> None:
        with pytest.raises(UnknownChangeSelectorError):
            plan_change_revert([_file("src/a.py")], [("src/a.py", (3,))])

    def test_binary_file_fails_closed(self) -> None:
        with pytest.raises(ChangeContentNotRecordedError):
            plan_change_revert([_file("bin/x", binary=True)], [("bin/x", None)])

    def test_rename_fails_closed(self) -> None:
        with pytest.raises(ChangeContentNotRecordedError):
            plan_change_revert(
                [_file("src/new.py", old_path="src/old.py")],
                [("src/new.py", None)],
            )

    def test_untracked_without_hunks_plans_delete(self) -> None:
        file = _file("notes.txt", status="untracked", hunks=[])
        plans = plan_change_revert([file], [("notes.txt", None)])
        assert plans[0].delete_file is True

    def test_modified_without_hunks_fails_closed(self) -> None:
        file = _file("src/a.py", status="modified", hunks=[])
        with pytest.raises(ChangeContentNotRecordedError):
            plan_change_revert([file], [("src/a.py", None)])


class TestBuildReversePatch:
    def test_modified_file_patch_shape(self) -> None:
        plans = plan_change_revert([_file("src/a.py")], [("src/a.py", None)])
        patch, deletions = build_reverse_patch(plans)
        assert deletions == []
        assert patch == (
            "--- a/src/a.py\n+++ b/src/a.py\n@@ -1,3 +1,3 @@\n alpha\n-beta\n+BETA\n gamma\n"
        )

    def test_added_file_uses_dev_null_source(self) -> None:
        file = _file(
            "new.py",
            status="added",
            hunks=[
                _hunk(
                    old_start=0,
                    new_start=1,
                    lines=[{"kind": "addition", "old_line": None, "new_line": 1, "text": "x"}],
                )
            ],
        )
        patch, _ = build_reverse_patch(plan_change_revert([file], [("new.py", None)]))
        assert patch.startswith("--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,1 @@\n+x\n")

    def test_deleted_file_uses_dev_null_target(self) -> None:
        file = _file(
            "gone.py",
            status="deleted",
            hunks=[
                _hunk(
                    old_start=1,
                    new_start=0,
                    lines=[{"kind": "deletion", "old_line": 1, "new_line": None, "text": "x"}],
                )
            ],
        )
        patch, _ = build_reverse_patch(plan_change_revert([file], [("gone.py", None)]))
        assert patch.startswith("--- a/gone.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-x\n")

    def test_untracked_delete_produces_empty_patch(self) -> None:
        file = _file("notes.txt", status="untracked", hunks=[])
        patch, deletions = build_reverse_patch(plan_change_revert([file], [("notes.txt", None)]))
        assert patch == ""
        assert deletions == ["notes.txt"]


class TestRenderRevertScript:
    def test_script_checks_before_applying(self) -> None:
        plans = plan_change_revert([_file("src/a.py")], [("src/a.py", None)])
        patch, deletions = build_reverse_patch(plans)
        script = render_revert_script(repository_root="/repo", patch=patch, deletions=deletions)
        check_at = script.index("git apply --check --reverse")
        apply_at = script.index("git apply --reverse --whitespace=nowarn", check_at + 1)
        assert check_at < apply_at
        assert "base64 -d" in script
        assert "REVERT_OK" in script
        assert "'/repo'" in script

    def test_script_quotes_single_quotes(self) -> None:
        script = render_revert_script(repository_root="/repo's", patch="", deletions=[])
        assert "'/repo'\\''s'" in script

    def test_deletion_only_script_skips_git_apply(self) -> None:
        script = render_revert_script(repository_root="/repo", patch="", deletions=["notes.txt"])
        assert "git apply" not in script
        assert "[ -e 'notes.txt' ]" in script
        assert "rm -- 'notes.txt'" in script

    def test_deletion_failure_rolls_back_applied_patch(self) -> None:
        plans = plan_change_revert([_file("src/a.py")], [("src/a.py", None)])
        patch, _ = build_reverse_patch(plans)
        script = render_revert_script(repository_root="/repo", patch=patch, deletions=["notes.txt"])
        rm_line = next(line for line in script.splitlines() if line.startswith("rm --"))
        assert "REVERT_PARTIAL" in rm_line
        assert "git apply --whitespace=nowarn" in rm_line


class TestParseRevertOutput:
    def test_ok_with_head(self) -> None:
        result = parse_revert_script_output("noise\nREVERT_OK abc123\n")
        assert result.kind == "ok"
        assert result.head_commit == "abc123"

    def test_ok_without_head(self) -> None:
        result = parse_revert_script_output("REVERT_OK ")
        assert result.kind == "ok"
        assert result.head_commit is None

    @pytest.mark.parametrize(
        ("marker", "kind"),
        [
            ("REVERT_ROOT_UNAVAILABLE", "root_unavailable"),
            ("REVERT_CHECK_FAILED", "check_failed"),
            ("REVERT_DELETE_MISSING x", "delete_missing"),
            ("REVERT_PARTIAL x", "partial"),
        ],
    )
    def test_failure_markers(self, marker: str, kind: str) -> None:
        result = parse_revert_script_output(f"git stderr noise\n{marker}\n")
        assert result.kind == kind

    def test_no_marker(self) -> None:
        assert parse_revert_script_output("unexpected").kind == "no_marker"


class TestRevertExclusions:
    def _event(self, reverted: list[dict]) -> AgentExecutionEvent:
        return cast(
            AgentExecutionEvent,
            SimpleNamespace(
                event_type="change_reverted",
                event_data={"source": "run_change_revert", "reverted": reverted},
            ),
        )

    def test_collects_file_and_hunk_levels(self) -> None:
        events = [
            self._event(
                [
                    {"path": "a.py", "patch_digest": "d1", "hunk_indices": None},
                    {"path": "b.py", "patch_digest": "d2", "hunk_indices": [1, 3]},
                ]
            )
        ]
        file_level, hunk_level = change_revert_exclusions(events)
        assert file_level == {("a.py", "d1")}
        assert hunk_level == {("b.py", "d2", 1), ("b.py", "d2", 3)}

    def test_ignores_foreign_events(self) -> None:
        foreign = cast(
            AgentExecutionEvent,
            SimpleNamespace(
                event_type="tool_result",
                event_data={"source": "run_change_revert", "reverted": []},
            ),
        )
        assert change_revert_exclusions([foreign]) == (set(), set())

    def test_exclusion_drops_reverted_file(self) -> None:
        file = _file("a.py", patch_digest="d1")
        visible = apply_change_revert_exclusions([file], ({("a.py", "d1")}, set()))
        assert visible == []

    def test_exclusion_filters_hunks_and_recounts(self) -> None:
        file = _file(
            "a.py",
            patch_digest="d1",
            hunks=[_hunk(), _hunk(old_start=10, new_start=10)],
        )
        visible = apply_change_revert_exclusions([file], (set(), {("a.py", "d1", 0)}))
        assert len(visible) == 1
        assert len(visible[0].hunks) == 1
        assert visible[0].hunks[0].old_start == 10
        assert visible[0].additions == 1
        assert visible[0].deletions == 1

    def test_exclusion_drops_file_when_all_hunks_reverted(self) -> None:
        file = _file("a.py", patch_digest="d1")
        visible = apply_change_revert_exclusions([file], (set(), {("a.py", "d1", 0)}))
        assert visible == []

    def test_empty_exclusions_pass_through(self) -> None:
        file = _file("a.py")
        assert apply_change_revert_exclusions([file], (set(), set())) == [file]


@pytest.mark.skipif(shutil.which("git") is None, reason="git binary unavailable")
class TestGitRoundTrip:
    """Prove reconstructed patches reverse-apply with the real git binary."""

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        return repo

    def _git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        ).stdout

    def test_reverse_patch_restores_modified_file(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        target = repo / "a.py"
        target.write_text("alpha\nbeta\ngamma\n")
        self._git(repo, "add", ".")
        target.write_text("alpha\nBETA\ngamma\ndelta\n")
        diff = self._git(repo, "diff")

        # Rebuild the recorded-change model from the real diff, then revert.
        from src.application.services.agent.run_change_revert import (
            build_reverse_patch as _build,
        )

        file = _file(
            "a.py",
            hunks=[
                {
                    "header": "@@ -1,3 +1,4 @@",
                    "old_start": 1,
                    "new_start": 1,
                    "lines": [
                        {"kind": "context", "old_line": 1, "new_line": 1, "text": "alpha"},
                        {"kind": "deletion", "old_line": 2, "new_line": None, "text": "beta"},
                        {"kind": "addition", "old_line": None, "new_line": 2, "text": "BETA"},
                        {"kind": "context", "old_line": 3, "new_line": 3, "text": "gamma"},
                        {"kind": "addition", "old_line": None, "new_line": 4, "text": "delta"},
                    ],
                }
            ],
        )
        assert "BETA" in diff
        patch, deletions = _build(plan_change_revert([file], [("a.py", None)]))
        assert deletions == []
        (repo / "revert.patch").write_text(patch)
        self._git(repo, "apply", "--check", "--reverse", "revert.patch")
        self._git(repo, "apply", "--reverse", "revert.patch")
        assert target.read_text() == "alpha\nbeta\ngamma\n"

    def test_reverse_patch_deletes_added_file(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        (repo / "seed").write_text("seed\n")
        self._git(repo, "add", ".")
        created = repo / "new.py"
        created.write_text("first\nsecond\n")
        file = _file(
            "new.py",
            status="added",
            hunks=[
                {
                    "header": "@@ -0,0 +1,2 @@",
                    "old_start": 0,
                    "new_start": 1,
                    "lines": [
                        {"kind": "addition", "old_line": None, "new_line": 1, "text": "first"},
                        {"kind": "addition", "old_line": None, "new_line": 2, "text": "second"},
                    ],
                }
            ],
        )
        patch, _ = build_reverse_patch(plan_change_revert([file], [("new.py", None)]))
        (repo / "revert.patch").write_text(patch)
        self._git(repo, "apply", "--check", "--reverse", "revert.patch")
        self._git(repo, "apply", "--reverse", "revert.patch")
        assert not created.exists()

    def test_reverse_patch_recreates_deleted_file(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        target = repo / "gone.py"
        target.write_text("keep me\n")
        self._git(repo, "add", ".")
        target.unlink()
        file = _file(
            "gone.py",
            status="deleted",
            hunks=[
                {
                    "header": "@@ -1 +0,0 @@",
                    "old_start": 1,
                    "new_start": 0,
                    "lines": [
                        {"kind": "deletion", "old_line": 1, "new_line": None, "text": "keep me"},
                    ],
                }
            ],
        )
        patch, _ = build_reverse_patch(plan_change_revert([file], [("gone.py", None)]))
        (repo / "revert.patch").write_text(patch)
        self._git(repo, "apply", "--reverse", "revert.patch")
        assert target.read_text() == "keep me\n"

    def test_stale_worktree_fails_check_closed(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        target = repo / "a.py"
        target.write_text("alpha\nbeta\ngamma\n")
        self._git(repo, "add", ".")
        target.write_text("alpha\nBETA\ngamma\n")
        file = _file("a.py")
        patch, _ = build_reverse_patch(plan_change_revert([file], [("a.py", None)]))
        (repo / "revert.patch").write_text(patch)
        # A later edit rewrites the same region: reverse apply must refuse.
        target.write_text("alpha\ncompletely different\ngamma\n")
        result = subprocess.run(
            ["git", "apply", "--check", "--reverse", "revert.patch"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert target.read_text() == "alpha\ncompletely different\ngamma\n"
