from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.infrastructure.agent.memory.markdown_store import MarkdownMemoryStore


async def test_capture_recall_list_and_delete_round_trip(tmp_path: Path) -> None:
    store = MarkdownMemoryStore(tmp_path / "memory")
    first_path = await store.capture(
        "project-1",
        "conversation-1",
        "Alpha deployment note",
        {"owner": "Platform"},
    )
    second_path = await store.capture(
        "project-1",
        "conversation-2",
        "Beta release note",
        {"topic": "alpha metadata"},
    )

    entries = await store.list_entries("project-1")
    assert {entry.file_path for entry in entries} == {first_path, second_path}
    assert {entry.conversation_id for entry in entries} == {
        "conversation-1",
        "conversation-2",
    }

    content_matches = await store.recall("project-1", "DEPLOYMENT", limit=1)
    assert len(content_matches) == 1
    assert content_matches[0].content == "Alpha deployment note"

    metadata_matches = await store.recall("project-1", "alpha metadata")
    assert [entry.content for entry in metadata_matches] == ["Beta release note"]

    assert await store.delete(first_path) is True
    assert await store.delete(first_path) is False
    assert [entry.file_path for entry in await store.list_entries("project-1")] == [second_path]
    assert await store.list_entries("missing-project") == []
    assert await store.recall("missing-project", "anything") == []


@pytest.mark.parametrize(
    "project_id,conversation_id",
    [
        ("", "conversation"),
        (".", "conversation"),
        ("..", "conversation"),
        ("../outside", "conversation"),
        ("nested/project", "conversation"),
        (r"nested\project", "conversation"),
        ("project", ""),
        ("project", "../outside"),
        ("project", "nested/conversation"),
    ],
)
async def test_capture_rejects_non_component_scope_ids(
    tmp_path: Path,
    project_id: str,
    conversation_id: str,
) -> None:
    store = MarkdownMemoryStore(tmp_path / "memory")

    with pytest.raises(ValueError, match="scope identifier"):
        await store.capture(project_id, conversation_id, "secret")

    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("project_id", ["", ".", "..", "../outside", "nested/project"])
async def test_read_operations_reject_non_component_project_ids(
    tmp_path: Path,
    project_id: str,
) -> None:
    store = MarkdownMemoryStore(tmp_path / "memory")

    with pytest.raises(ValueError, match="scope identifier"):
        await store.list_entries(project_id)
    with pytest.raises(ValueError, match="scope identifier"):
        await store.recall(project_id, "query")


async def test_delete_rejects_files_outside_store(tmp_path: Path) -> None:
    store = MarkdownMemoryStore(tmp_path / "memory")
    outside = tmp_path / "outside.md"
    outside.write_text("must survive", encoding="utf-8")

    with pytest.raises(ValueError, match="outside memory store"):
        await store.delete(str(outside))

    assert outside.read_text(encoding="utf-8") == "must survive"


async def test_capture_rejects_symlink_escape(tmp_path: Path) -> None:
    base_dir = tmp_path / "memory"
    outside = tmp_path / "outside"
    outside.mkdir()
    base_dir.mkdir()
    (base_dir / "project-1").symlink_to(outside, target_is_directory=True)
    store = MarkdownMemoryStore(base_dir)

    with pytest.raises(ValueError, match="outside memory store"):
        await store.capture("project-1", "conversation-1", "secret")

    assert list(outside.iterdir()) == []


def test_parse_markdown_tolerates_invalid_optional_fields(tmp_path: Path) -> None:
    file_path = tmp_path / "entry.md"
    file_path.write_text(
        "---\n"
        "project_id: project-1\n"
        "conversation_id: conversation-1\n"
        "created_at: not-a-date\n"
        "metadata: not-json\n"
        "ignored line\n"
        "---\n\n"
        "Body\n",
        encoding="utf-8",
    )

    before = datetime.now(tz=UTC) - timedelta(seconds=1)
    entry = MarkdownMemoryStore._parse_markdown(file_path)
    after = datetime.now(tz=UTC) + timedelta(seconds=1)

    assert entry is not None
    assert entry.content == "Body"
    assert entry.metadata == {}
    assert before <= entry.created_at <= after


@pytest.mark.parametrize("contents", ["plain markdown", "---\nmissing closing marker"])
def test_parse_markdown_rejects_invalid_frontmatter(tmp_path: Path, contents: str) -> None:
    file_path = tmp_path / "entry.md"
    file_path.write_text(contents, encoding="utf-8")

    assert MarkdownMemoryStore._parse_markdown(file_path) is None
