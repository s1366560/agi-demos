"""Tests for Phase 5.3: SubAgent Template Registry (Marketplace)."""

import pytest
from unittest.mock import MagicMock

from src.domain.model.agent.subagent import AgentModel, SubAgent
from src.infrastructure.agent.subagent.template_registry import (
    SubAgentTemplate,
    TemplateRegistry,
)


def _make_subagent(
    name: str = "test-agent",
    description: str = "A test agent",
    system_prompt: str = "You are a helper.",
) -> SubAgent:
    return SubAgent.create(
        tenant_id="tenant-1",
        name=name,
        display_name=name,
        system_prompt=system_prompt,
        trigger_description=f"Trigger for {name}",
        trigger_keywords=[name, "help"],
        trigger_examples=[f"Use {name} for tasks"],
    )


@pytest.mark.unit
class TestSubAgentTemplate:
    def test_from_subagent(self):
        sa = _make_subagent("code-reviewer", "Reviews code", "You review code.")
        template = SubAgentTemplate.from_subagent(sa, author="team-a", category="code")

        assert template.name == "code-reviewer"
        assert template.system_prompt == "You review code."
        assert template.author == "team-a"
        assert template.category == "code"
        assert "code-reviewer" in template.trigger_keywords
        assert template.version == "1.0.0"

    def test_to_subagent(self):
        template = SubAgentTemplate(
            name="writer",
            description="Writes content",
            system_prompt="You are a writer.",
            model_preference="inherit",
            trigger_description="Writing tasks",
            trigger_keywords=["write", "draft"],
            trigger_examples=["Write a report"],
        )

        sa = template.to_subagent(project_id="proj-1", tenant_id="tenant-1")

        assert sa.name == "writer"
        assert sa.system_prompt == "You are a writer."
        assert template.usage_count == 1

    def test_to_subagent_increments_usage(self):
        template = SubAgentTemplate(
            name="helper",
            trigger_description="General help",
        )

        template.to_subagent(tenant_id="t1")
        template.to_subagent(tenant_id="t1")
        template.to_subagent(tenant_id="t1")

        assert template.usage_count == 3

    def test_roundtrip_serialization(self):
        template = SubAgentTemplate(
            name="analyzer",
            description="Analyzes data",
            version="2.0.0",
            author="team-b",
            category="data",
            system_prompt="You analyze data.",
            temperature=0.3,
            max_iterations=10,
            trigger_keywords=["analyze", "data"],
            tags=["analytics", "data"],
            metadata={"custom_key": "value"},
        )

        data = template.to_dict()
        restored = SubAgentTemplate.from_dict(data)

        assert restored.name == "analyzer"
        assert restored.version == "2.0.0"
        assert restored.author == "team-b"
        assert restored.category == "data"
        assert restored.temperature == 0.3
        assert restored.max_iterations == 10
        assert "analyze" in restored.trigger_keywords
        assert "analytics" in restored.tags
        assert restored.metadata["custom_key"] == "value"

    def test_from_dict_defaults(self):
        template = SubAgentTemplate.from_dict({"name": "minimal"})

        assert template.name == "minimal"
        assert template.version == "1.0.0"
        assert template.category == "general"
        assert template.temperature == 0.7

    def test_to_dict_contains_all_fields(self):
        template = SubAgentTemplate(name="test")
        data = template.to_dict()

        expected_keys = {
            "template_id", "name", "description", "version", "author",
            "category", "system_prompt", "model_preference", "temperature",
            "max_iterations", "max_tokens", "trigger_keywords",
            "trigger_description", "trigger_examples", "tool_filter_tags",
            "tags", "metadata", "created_at", "usage_count",
        }
        assert set(data.keys()) == expected_keys


@pytest.mark.unit
class TestTemplateRegistry:
    def test_register_and_get(self):
        registry = TemplateRegistry()
        template = SubAgentTemplate(name="agent-a")

        tid = registry.register(template)

        assert tid == template.template_id
        assert registry.get(tid) is template

    def test_get_by_name(self):
        registry = TemplateRegistry()
        t1 = SubAgentTemplate(name="Agent-A")
        registry.register(t1)

        # Case-insensitive
        found = registry.get_by_name("agent-a")
        assert found is t1

    def test_get_by_name_returns_latest(self):
        registry = TemplateRegistry()
        t1 = SubAgentTemplate(name="Agent-A", version="1.0.0")
        t2 = SubAgentTemplate(name="Agent-A", version="2.0.0")

        registry.register(t1)
        registry.register(t2)

        found = registry.get_by_name("Agent-A")
        assert found is t2

    def test_unregister(self):
        registry = TemplateRegistry()
        t = SubAgentTemplate(name="temp")
        registry.register(t)

        assert registry.unregister(t.template_id)
        assert registry.get(t.template_id) is None
        assert registry.get_by_name("temp") is None

    def test_unregister_nonexistent(self):
        registry = TemplateRegistry()
        assert not registry.unregister("fake-id")

    def test_search_by_query(self):
        registry = TemplateRegistry()
        registry.register(SubAgentTemplate(name="code-reviewer", description="Reviews Python code"))
        registry.register(SubAgentTemplate(name="writer", description="Writes documentation"))

        results = registry.search(query="code")
        assert len(results) == 1
        assert results[0].name == "code-reviewer"

    def test_search_by_category(self):
        registry = TemplateRegistry()
        registry.register(SubAgentTemplate(name="a1", category="code"))
        registry.register(SubAgentTemplate(name="a2", category="writing"))
        registry.register(SubAgentTemplate(name="a3", category="code"))

        results = registry.search(category="code")
        assert len(results) == 2

    def test_search_by_tags(self):
        registry = TemplateRegistry()
        registry.register(SubAgentTemplate(name="a1", tags=["python", "code"]))
        registry.register(SubAgentTemplate(name="a2", tags=["javascript", "code"]))
        registry.register(SubAgentTemplate(name="a3", tags=["writing"]))

        results = registry.search(tags=["python"])
        assert len(results) == 1
        assert results[0].name == "a1"

    def test_search_combined_filters(self):
        registry = TemplateRegistry()
        registry.register(SubAgentTemplate(
            name="py-reviewer", category="code", tags=["python"],
            description="Reviews Python code",
        ))
        registry.register(SubAgentTemplate(
            name="js-reviewer", category="code", tags=["javascript"],
            description="Reviews JS code",
        ))
        registry.register(SubAgentTemplate(
            name="blog-writer", category="writing", tags=["python"],
            description="Writes blog posts about Python",
        ))

        results = registry.search(query="python", category="code")
        assert len(results) == 1
        assert results[0].name == "py-reviewer"

    def test_search_sorted_by_usage(self):
        registry = TemplateRegistry()
        t1 = SubAgentTemplate(name="a1", usage_count=5)
        t2 = SubAgentTemplate(name="a2", usage_count=20)
        t3 = SubAgentTemplate(name="a3", usage_count=10)

        registry.register(t1)
        registry.register(t2)
        registry.register(t3)

        results = registry.search()
        assert results[0].name == "a2"
        assert results[1].name == "a3"
        assert results[2].name == "a1"

    def test_search_empty_query_returns_all(self):
        registry = TemplateRegistry()
        registry.register(SubAgentTemplate(name="a1"))
        registry.register(SubAgentTemplate(name="a2"))

        results = registry.search()
        assert len(results) == 2

    def test_list_all(self):
        registry = TemplateRegistry()
        registry.register(SubAgentTemplate(name="a1"))
        registry.register(SubAgentTemplate(name="a2"))

        assert len(registry.list_all()) == 2

    def test_list_categories(self):
        registry = TemplateRegistry()
        registry.register(SubAgentTemplate(name="a1", category="code"))
        registry.register(SubAgentTemplate(name="a2", category="writing"))
        registry.register(SubAgentTemplate(name="a3", category="code"))

        categories = registry.list_categories()
        assert categories == ["code", "writing"]

    def test_get_versions(self):
        registry = TemplateRegistry()
        t1 = SubAgentTemplate(name="Agent", version="1.0.0")
        t2 = SubAgentTemplate(name="Agent", version="2.0.0")
        t3 = SubAgentTemplate(name="Agent", version="3.0.0")

        registry.register(t1)
        registry.register(t2)
        registry.register(t3)

        versions = registry.get_versions("Agent")
        assert len(versions) == 3
        assert versions[0].version == "1.0.0"
        assert versions[2].version == "3.0.0"

    def test_clear(self):
        registry = TemplateRegistry()
        registry.register(SubAgentTemplate(name="a1"))
        registry.register(SubAgentTemplate(name="a2"))

        registry.clear()

        assert len(registry.list_all()) == 0

    def test_registry_capacity(self):
        """Test that registry enforces MAX_TEMPLATES."""
        from src.infrastructure.agent.subagent.template_registry import MAX_TEMPLATES

        registry = TemplateRegistry()
        for i in range(MAX_TEMPLATES):
            registry.register(SubAgentTemplate(name=f"agent-{i}"))

        with pytest.raises(ValueError, match="full"):
            registry.register(SubAgentTemplate(name="one-too-many"))

    def test_get_missing_returns_none(self):
        registry = TemplateRegistry()
        assert registry.get("fake-id") is None
        assert registry.get_by_name("nonexistent") is None
