"""The prompt lists the active skills it is given and does not invent a catalog."""

import pytest

from src.infrastructure.agent.prompts.manager import (
    ModelProvider,
    PromptContext,
    SystemPromptManager,
)

pytestmark = pytest.mark.unit


def test_skill_section_uses_only_active_skill_names() -> None:
    section = SystemPromptManager()._build_skill_section(
        PromptContext(
            model_provider=ModelProvider.DEFAULT,
            skills=[
                {
                    "name": "memory-curator",
                    "status": "active",
                    "description": "curate",
                    "tools": ["memory_search"],
                },
                {
                    "name": "darwinian-evolver",
                    "status": "inactive",
                    "description": "hidden",
                    "tools": [],
                },
            ],
        )
    )
    assert "`memory-curator`" in section
    assert "darwinian-evolver" not in section
    assert "github" not in section
    assert "docker-compose" not in section
    assert "drone" not in section
    assert "skill_loader" in section
