"""Unit tests for SkillVersion domain model."""

import pytest

from src.domain.model.agent.skill.skill_version import SkillVersion


@pytest.mark.unit
class TestSkillVersion:
    """Tests for SkillVersion domain model."""

    def test_create_skill_version(self):
        version = SkillVersion(
            id="v-1",
            skill_id="skill-1",
            version_number=1,
            skill_md_content="# Test Skill\nContent here",
            resource_files={"template.py": "print('hello')"},
        )
        assert version.id
        assert version.skill_id == "skill-1"
        assert version.version_number == 1
        assert version.skill_md_content == "# Test Skill\nContent here"
        assert version.resource_files == {"template.py": "print('hello')"}
        assert version.created_by == "agent"
        assert version.version_label is None
        assert version.change_summary is None

    def test_create_with_version_label(self):
        version = SkillVersion(
            id="v-2",
            skill_id="skill-1",
            version_number=2,
            version_label="1.2.0",
            skill_md_content="# Skill",
            resource_files={},
            change_summary="Updated prompt",
            created_by="api",
        )
        assert version.version_label == "1.2.0"
        assert version.change_summary == "Updated prompt"
        assert version.created_by == "api"

    def test_to_dict(self):
        version = SkillVersion(
            id="v-123",
            skill_id="skill-1",
            version_number=3,
            version_label="2.0.0",
            skill_md_content="# Content",
            resource_files={"a.txt": "hello"},
            change_summary="Major update",
            created_by="rollback",
        )
        d = version.to_dict()
        assert d["id"] == "v-123"
        assert d["skill_id"] == "skill-1"
        assert d["version_number"] == 3
        assert d["version_label"] == "2.0.0"
        assert d["skill_md_content"] == "# Content"
        assert d["resource_files"] == {"a.txt": "hello"}
        assert d["change_summary"] == "Major update"
        assert d["created_by"] == "rollback"
        assert "created_at" in d

    def test_from_dict(self):
        d = {
            "id": "v-456",
            "skill_id": "skill-2",
            "version_number": 5,
            "version_label": "3.0.0",
            "skill_md_content": "# V5",
            "resource_files": {},
            "change_summary": "V5 release",
            "created_by": "agent",
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        version = SkillVersion.from_dict(d)
        assert version.id == "v-456"
        assert version.skill_id == "skill-2"
        assert version.version_number == 5
        assert version.version_label == "3.0.0"

    def test_invalid_empty_skill_id_raises(self):
        with pytest.raises(ValueError, match="skill_id"):
            SkillVersion(
                id="v-x",
                skill_id="",
                version_number=1,
                skill_md_content="# Test",
            )

    def test_invalid_version_number_raises(self):
        with pytest.raises(ValueError, match="version_number"):
            SkillVersion(
                id="v-y",
                skill_id="skill-1",
                version_number=0,
                skill_md_content="# Test",
            )
