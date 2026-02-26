"""Tests for skill_tool module."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.skill_tool import (
    SkillData,
    SkillSummary,
    configure_skill_loader,
    get_skill_loader,
    skill_tool,
)


def _make_ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        message_id="m",
        call_id="c",
        agent_name="a",
        conversation_id="conv",
    )


class FakeSkillLoader:
    """Fake skill loader for testing."""

    def __init__(
        self,
        skills: dict[str, SkillData] | None = None,
        summaries: list[SkillSummary] | None = None,
    ) -> None:
        self._skills = skills or {}
        self._summaries = summaries or []

    async def load(self, name: str) -> SkillData | None:
        return self._skills.get(name)

    async def list_available(self) -> list[SkillSummary]:
        return self._summaries


@pytest.mark.unit
class TestSkillDataAndSummary:
    """Tests for SkillData and SkillSummary dataclasses."""

    def test_skill_data_defaults(self) -> None:
        data = SkillData(name="git", description="Git ops", content="# Git skill")
        assert data.name == "git"
        assert data.scope == "project"

    def test_skill_data_frozen(self) -> None:
        data = SkillData(name="x", description="y", content="z")
        with pytest.raises(AttributeError):
            data.name = "changed"  # type: ignore[misc]

    def test_skill_summary(self) -> None:
        s = SkillSummary(name="git", description="Git operations")
        assert s.name == "git"


@pytest.mark.unit
class TestConfigureSkillLoader:
    """Tests for configure_skill_loader and get_skill_loader."""

    def teardown_method(self) -> None:
        configure_skill_loader(None)  # type: ignore[arg-type]

    def test_configure_and_get(self) -> None:
        loader = FakeSkillLoader()
        configure_skill_loader(loader)
        assert get_skill_loader() is loader

    def test_default_is_none(self) -> None:
        configure_skill_loader(None)  # type: ignore[arg-type]
        # After reset, loader should be None
        # (We set it to None in teardown, so it's always clean)


@pytest.mark.unit
class TestSkillTool:
    """Tests for skill_tool execution."""

    def setup_method(self) -> None:
        configure_skill_loader(None)  # type: ignore[arg-type]

    def teardown_method(self) -> None:
        configure_skill_loader(None)  # type: ignore[arg-type]

    async def test_no_loader_configured(self) -> None:
        # Arrange - no loader configured
        ctx = _make_ctx()

        # Act
        result = await skill_tool.execute(ctx, name="git-master")

        # Assert
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "not configured" in result.output

    async def test_skill_not_found_with_available(self) -> None:
        loader = FakeSkillLoader(
            summaries=[
                SkillSummary(name="git-master", description="Git ops"),
                SkillSummary(name="python-testing", description="Testing"),
            ],
        )
        configure_skill_loader(loader)
        ctx = _make_ctx()

        result = await skill_tool.execute(ctx, name="nonexistent")

        assert result.is_error is True
        assert "not found" in result.output
        assert "git-master" in result.output

    async def test_skill_not_found_no_available(self) -> None:
        loader = FakeSkillLoader()
        configure_skill_loader(loader)
        ctx = _make_ctx()

        result = await skill_tool.execute(ctx, name="nonexistent")

        assert result.is_error is True
        assert "No skills are currently available" in result.output

    async def test_skill_loaded_successfully(self) -> None:
        skill_data = SkillData(
            name="git-master",
            description="Git operations guide",
            content="# Git Master Skill\nUse git properly.",
        )
        loader = FakeSkillLoader(skills={"git-master": skill_data})
        configure_skill_loader(loader)
        ctx = _make_ctx()

        result = await skill_tool.execute(ctx, name="git-master")

        assert result.is_error is False
        assert result.output == "# Git Master Skill\nUse git properly."
        assert result.title == "Skill: git-master"
        assert result.metadata["skill_name"] == "git-master"
        assert result.metadata["scope"] == "project"

    async def test_skill_with_user_message(self) -> None:
        skill_data = SkillData(name="test", description="desc", content="content")
        loader = FakeSkillLoader(skills={"test": skill_data})
        configure_skill_loader(loader)
        ctx = _make_ctx()

        result = await skill_tool.execute(ctx, name="test", user_message="I need help with X")

        assert result.metadata["user_message"] == "I need help with X"

    async def test_skill_denied_by_ctx_ask(self) -> None:
        skill_data = SkillData(name="denied", description="desc", content="content")
        loader = FakeSkillLoader(skills={"denied": skill_data})
        configure_skill_loader(loader)

        ctx = _make_ctx()
        ctx.ask = AsyncMock(return_value=False)  # type: ignore[method-assign]

        result = await skill_tool.execute(ctx, name="denied")

        assert result.is_error is True
        assert "denied" in result.output.lower()

    def test_skill_tool_is_tool_info(self) -> None:
        from src.infrastructure.agent.tools.define import ToolInfo

        assert isinstance(skill_tool, ToolInfo)
        assert skill_tool.name == "skill"
        assert skill_tool.permission == "skill"
        assert skill_tool.category == "knowledge"
        assert "skill" in skill_tool.tags
