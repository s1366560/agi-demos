"""The shipped CLI and signed tool share the independent publisher implementation."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_local_and_worker_validation_return_the_same_verdict(tmp_path: Path) -> None:
    from plugins.business.agent.skill_validation.validator import AgentSkillsValidator
    from plugins.business.agent.worker import validate_skill

    directory = tmp_path / "my-skill"
    directory.mkdir()
    content = "---\nname: my-skill\ndescription: Reads the archive\n---\n# Read"
    (directory / "SKILL.md").write_text(content, encoding="utf-8")
    local = AgentSkillsValidator().validate_file(directory)
    assert local.to_dict() == validate_skill({"content": content})


def test_package_validation_preserves_strict_mode_and_never_opens_a_caller_path(
    tmp_path: Path,
) -> None:
    from plugins.business.agent.worker import validate_skill

    content = (
        "---\nname: my-skill\ndescription: Reads the archive\ntrigger_patterns: [load]\n---\n# Load"
    )
    assert validate_skill({"content": content})["is_valid"]
    strict = validate_skill({"content": content, "strict": True})
    assert not strict["is_valid"]
    assert strict["error_count"] == 1
    with pytest.raises(ValueError, match=r"expected SKILL\.md"):
        validate_skill({"path": str(tmp_path / "SKILL.md")})
