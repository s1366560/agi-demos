from pathlib import Path

import pytest

from src.application.services.instance_file_service import InstanceFileService


@pytest.mark.unit
class TestInstanceFileService:
    async def test_read_content_allows_files_inside_instance_root(self, tmp_path: Path) -> None:
        service = InstanceFileService(base_dir=str(tmp_path))
        target = tmp_path / "instance-1" / "workspace" / "docs" / "note.txt"
        target.parent.mkdir(parents=True)
        target.write_text("hello", encoding="utf-8")

        content = await service.read_content("instance-1", "docs/note.txt")

        assert content == "hello"

    async def test_resolve_safe_rejects_symlink_escape_to_sibling_prefix(
        self,
        tmp_path: Path,
    ) -> None:
        service = InstanceFileService(base_dir=str(tmp_path))
        root = tmp_path / "instance-1" / "workspace"
        root.mkdir(parents=True)
        sibling = tmp_path / "instance-1" / "workspace-secret"
        sibling.mkdir()
        (sibling / "leak.txt").write_text("secret", encoding="utf-8")
        (root / "link").symlink_to(sibling)

        with pytest.raises(ValueError, match="Path traversal not allowed"):
            await service.read_content("instance-1", "link/leak.txt")
