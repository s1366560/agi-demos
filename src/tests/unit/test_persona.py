"""Unit tests for persona types: PersonaSource, PersonaField, AgentPersona,
PromptSectionEntry, and PromptReport.

Tests the first-class persona system used in the agent prompt pipeline.
"""

import pytest

from src.infrastructure.agent.prompts.persona import (
    AgentPersona,
    PersonaField,
    PersonaSource,
    PromptReport,
    PromptSectionEntry,
)


@pytest.mark.unit
class TestPersonaSource:
    """Test PersonaSource enum values and behavior."""

    def test_workspace_value(self):
        """PersonaSource.WORKSPACE should have value 'workspace'."""
        assert PersonaSource.WORKSPACE.value == "workspace"

    def test_template_value(self):
        """PersonaSource.TEMPLATE should have value 'template'."""
        assert PersonaSource.TEMPLATE.value == "template"

    def test_config_value(self):
        """PersonaSource.CONFIG should have value 'config'."""
        assert PersonaSource.CONFIG.value == "config"

    def test_none_value(self):
        """PersonaSource.NONE should have value 'none'."""
        assert PersonaSource.NONE.value == "none"

    def test_is_str_subclass(self):
        """PersonaSource should be a str enum (usable as string)."""
        assert isinstance(PersonaSource.WORKSPACE, str)
        assert PersonaSource.WORKSPACE == "workspace"

    def test_from_string(self):
        """PersonaSource should be constructible from string values."""
        assert PersonaSource("workspace") == PersonaSource.WORKSPACE
        assert PersonaSource("none") == PersonaSource.NONE

    def test_tenant_value(self):
        """PersonaSource.TENANT should have value 'tenant'."""
        assert PersonaSource.TENANT.value == "tenant"
    def test_invalid_value_raises(self):
        """Creating PersonaSource from invalid string should raise."""
        with pytest.raises(ValueError):
            PersonaSource("invalid")


@pytest.mark.unit
class TestPersonaField:
    """Test PersonaField dataclass and its properties."""

    def test_default_values(self):
        """PersonaField defaults should be empty/unloaded."""
        field = PersonaField()
        assert field.content == ""
        assert field.source == PersonaSource.NONE
        assert field.raw_chars == 0
        assert field.injected_chars == 0
        assert field.is_truncated is False
        assert field.filename == ""

    def test_is_loaded_with_content_and_source(self):
        """is_loaded should be True when content exists and source is not NONE."""
        field = PersonaField(
            content="Hello",
            source=PersonaSource.WORKSPACE,
        )
        assert field.is_loaded is True

    def test_is_loaded_false_when_empty_content(self):
        """is_loaded should be False when content is empty."""
        field = PersonaField(
            content="",
            source=PersonaSource.WORKSPACE,
        )
        assert field.is_loaded is False

    def test_is_loaded_false_when_source_none(self):
        """is_loaded should be False when source is NONE."""
        field = PersonaField(
            content="Hello",
            source=PersonaSource.NONE,
        )
        assert field.is_loaded is False

    def test_empty_factory(self):
        """PersonaField.empty() should create an unloaded field."""
        field = PersonaField.empty("SOUL.md")
        assert field.content == ""
        assert field.source == PersonaSource.NONE
        assert field.filename == "SOUL.md"
        assert field.is_loaded is False

    def test_empty_factory_default_filename(self):
        """PersonaField.empty() with no args should have empty filename."""
        field = PersonaField.empty()
        assert field.filename == ""

    def test_frozen_prevents_mutation(self):
        """PersonaField is frozen; attribute assignment should raise."""
        field = PersonaField(content="test")
        with pytest.raises(AttributeError):
            field.content = "modified"  # type: ignore[misc]

    def test_custom_values(self):
        """PersonaField should accept custom values at construction."""
        field = PersonaField(
            content="soul content",
            source=PersonaSource.TEMPLATE,
            raw_chars=500,
            injected_chars=400,
            is_truncated=True,
            filename="SOUL.md",
        )
        assert field.content == "soul content"
        assert field.source == PersonaSource.TEMPLATE
        assert field.raw_chars == 500
        assert field.injected_chars == 400
        assert field.is_truncated is True
        assert field.filename == "SOUL.md"


@pytest.mark.unit
class TestAgentPersona:
    """Test AgentPersona container and its properties."""

    def test_default_fields_are_empty(self):
        """Default AgentPersona should have empty fields."""
        persona = AgentPersona()
        assert persona.soul.filename == "SOUL.md"
        assert persona.identity.filename == "IDENTITY.md"
        assert persona.user_profile.filename == "USER.md"
        assert persona.soul.is_loaded is False
        assert persona.identity.is_loaded is False
        assert persona.user_profile.is_loaded is False

    def test_has_any_false_when_empty(self):
        """has_any should be False when no fields are loaded."""
        persona = AgentPersona()
        assert persona.has_any is False

    def test_has_any_true_with_soul(self):
        """has_any should be True when soul is loaded."""
        persona = AgentPersona(
            soul=PersonaField(
                content="soul",
                source=PersonaSource.WORKSPACE,
            ),
        )
        assert persona.has_any is True

    def test_has_any_true_with_identity(self):
        """has_any should be True when identity is loaded."""
        persona = AgentPersona(
            identity=PersonaField(
                content="identity",
                source=PersonaSource.TEMPLATE,
            ),
        )
        assert persona.has_any is True

    def test_has_any_true_with_user_profile(self):
        """has_any should be True when user_profile is loaded."""
        persona = AgentPersona(
            user_profile=PersonaField(
                content="profile",
                source=PersonaSource.CONFIG,
            ),
        )
        assert persona.has_any is True

    def test_total_chars(self):
        """total_chars should sum injected_chars from all fields."""
        persona = AgentPersona(
            soul=PersonaField(injected_chars=100),
            identity=PersonaField(injected_chars=200),
            user_profile=PersonaField(injected_chars=300),
        )
        assert persona.total_chars == 600

    def test_total_raw_chars(self):
        """total_raw_chars should sum raw_chars from all fields."""
        persona = AgentPersona(
            soul=PersonaField(raw_chars=1000),
            identity=PersonaField(raw_chars=2000),
            user_profile=PersonaField(raw_chars=3000),
        )
        assert persona.total_raw_chars == 6000

    def test_any_truncated_false(self):
        """any_truncated should be False when no fields are truncated."""
        persona = AgentPersona()
        assert persona.any_truncated is False

    def test_any_truncated_true(self):
        """any_truncated should be True if any field is truncated."""
        persona = AgentPersona(
            soul=PersonaField(is_truncated=True),
        )
        assert persona.any_truncated is True

    def test_loaded_fields(self):
        """loaded_fields should return only fields with content."""
        soul = PersonaField(
            content="soul",
            source=PersonaSource.WORKSPACE,
        )
        identity = PersonaField.empty("IDENTITY.md")
        profile = PersonaField(
            content="profile",
            source=PersonaSource.TEMPLATE,
        )
        persona = AgentPersona(
            soul=soul,
            identity=identity,
            user_profile=profile,
        )
        loaded = persona.loaded_fields()
        assert len(loaded) == 2
        assert soul in loaded
        assert profile in loaded

    def test_loaded_fields_empty(self):
        """loaded_fields should return empty list when nothing loaded."""
        persona = AgentPersona()
        assert persona.loaded_fields() == []

    def test_empty_factory(self):
        """AgentPersona.empty() should create persona with no content."""
        persona = AgentPersona.empty()
        assert persona.has_any is False
        assert persona.total_chars == 0

    def test_soul_text_backward_compat_loaded(self):
        """soul_text should return content when soul is loaded."""
        persona = AgentPersona(
            soul=PersonaField(
                content="my soul",
                source=PersonaSource.WORKSPACE,
            ),
        )
        assert persona.soul_text == "my soul"

    def test_soul_text_backward_compat_not_loaded(self):
        """soul_text should return None when soul is not loaded."""
        persona = AgentPersona()
        assert persona.soul_text is None

    def test_identity_text_backward_compat_loaded(self):
        """identity_text should return content when identity is loaded."""
        persona = AgentPersona(
            identity=PersonaField(
                content="my identity",
                source=PersonaSource.TEMPLATE,
            ),
        )
        assert persona.identity_text == "my identity"

    def test_identity_text_backward_compat_not_loaded(self):
        """identity_text should return None when identity is not loaded."""
        persona = AgentPersona()
        assert persona.identity_text is None

    def test_user_profile_text_backward_compat_loaded(self):
        """user_profile_text should return content when loaded."""
        persona = AgentPersona(
            user_profile=PersonaField(
                content="my profile",
                source=PersonaSource.CONFIG,
            ),
        )
        assert persona.user_profile_text == "my profile"

    def test_user_profile_text_backward_compat_not_loaded(self):
        """user_profile_text should return None when not loaded."""
        persona = AgentPersona()
        assert persona.user_profile_text is None

    def test_default_fields_include_agents_and_tools(self):
        """Default AgentPersona should have agents and tools fields."""
        persona = AgentPersona()
        assert persona.agents.filename == "AGENTS.md"
        assert persona.tools.filename == "TOOLS.md"
        assert persona.agents.is_loaded is False
        assert persona.tools.is_loaded is False

    def test_has_any_true_with_agents(self):
        """has_any should be True when agents is loaded."""
        persona = AgentPersona(
            agents=PersonaField(
                content="agents config",
                source=PersonaSource.WORKSPACE,
            ),
        )
        assert persona.has_any is True

    def test_has_any_true_with_tools(self):
        """has_any should be True when tools is loaded."""
        persona = AgentPersona(
            tools=PersonaField(
                content="tools config",
                source=PersonaSource.TENANT,
            ),
        )
        assert persona.has_any is True

    def test_total_chars_with_all_fields(self):
        """total_chars should sum injected_chars from all five fields."""
        persona = AgentPersona(
            soul=PersonaField(injected_chars=100),
            identity=PersonaField(injected_chars=200),
            user_profile=PersonaField(injected_chars=300),
            agents=PersonaField(injected_chars=400),
            tools=PersonaField(injected_chars=500),
        )
        assert persona.total_chars == 1500

    def test_total_raw_chars_with_all_fields(self):
        """total_raw_chars should sum raw_chars from all five fields."""
        persona = AgentPersona(
            soul=PersonaField(raw_chars=1000),
            identity=PersonaField(raw_chars=2000),
            user_profile=PersonaField(raw_chars=3000),
            agents=PersonaField(raw_chars=4000),
            tools=PersonaField(raw_chars=5000),
        )
        assert persona.total_raw_chars == 15000

    def test_any_truncated_true_agents(self):
        """any_truncated should be True if agents field is truncated."""
        persona = AgentPersona(
            agents=PersonaField(is_truncated=True),
        )
        assert persona.any_truncated is True

    def test_loaded_fields_includes_agents_and_tools(self):
        """loaded_fields should include agents and tools when loaded."""
        agents = PersonaField(
            content="agents",
            source=PersonaSource.WORKSPACE,
        )
        tools = PersonaField(
            content="tools",
            source=PersonaSource.TENANT,
        )
        persona = AgentPersona(
            agents=agents,
            tools=tools,
        )
        loaded = persona.loaded_fields()
        assert len(loaded) == 2
        assert agents in loaded
        assert tools in loaded

    def test_agents_text_backward_compat_loaded(self):
        """agents_text should return content when agents is loaded."""
        persona = AgentPersona(
            agents=PersonaField(
                content="my agents",
                source=PersonaSource.WORKSPACE,
            ),
        )
        assert persona.agents_text == "my agents"

    def test_agents_text_backward_compat_not_loaded(self):
        """agents_text should return None when agents is not loaded."""
        persona = AgentPersona()
        assert persona.agents_text is None

    def test_tools_text_backward_compat_loaded(self):
        """tools_text should return content when tools is loaded."""
        persona = AgentPersona(
            tools=PersonaField(
                content="my tools",
                source=PersonaSource.TENANT,
            ),
        )
        assert persona.tools_text == "my tools"

    def test_tools_text_backward_compat_not_loaded(self):
        """tools_text should return None when tools is not loaded."""
        persona = AgentPersona()
        assert persona.tools_text is None

    def test_frozen_prevents_mutation(self):
        """AgentPersona is frozen; field assignment should raise."""
        persona = AgentPersona()
        with pytest.raises(AttributeError):
            persona.soul = PersonaField()  # type: ignore[misc]


@pytest.mark.unit
class TestPromptSectionEntry:
    """Test PromptSectionEntry dataclass."""

    def test_default_values(self):
        """PromptSectionEntry defaults should be sensible."""
        entry = PromptSectionEntry(name="base_prompt")
        assert entry.name == "base_prompt"
        assert entry.chars == 0
        assert entry.included is True
        assert entry.source == ""
        assert entry.truncated is False

    def test_custom_values(self):
        """PromptSectionEntry should accept all custom values."""
        entry = PromptSectionEntry(
            name="soul",
            chars=500,
            included=True,
            source="workspace",
            truncated=True,
        )
        assert entry.name == "soul"
        assert entry.chars == 500
        assert entry.included is True
        assert entry.source == "workspace"
        assert entry.truncated is True

    def test_skipped_entry(self):
        """A skipped entry should have included=False."""
        entry = PromptSectionEntry(
            name="identity",
            chars=0,
            included=False,
            source="not loaded",
        )
        assert entry.included is False
        assert entry.source == "not loaded"

    def test_frozen_prevents_mutation(self):
        """PromptSectionEntry is frozen; assignment should raise."""
        entry = PromptSectionEntry(name="test")
        with pytest.raises(AttributeError):
            entry.name = "changed"  # type: ignore[misc]


@pytest.mark.unit
class TestPromptReport:
    """Test PromptReport mutable diagnostic container."""

    def test_default_values(self):
        """PromptReport defaults should be empty."""
        report = PromptReport()
        assert report.sections == []
        assert report.total_chars == 0
        assert report.persona.has_any is False
        assert report.warnings == []

    def test_add_section(self):
        """add_section should append an included PromptSectionEntry."""
        report = PromptReport()
        report.add_section("base_prompt", "Hello world")
        assert len(report.sections) == 1
        section = report.sections[0]
        assert section.name == "base_prompt"
        assert section.chars == len("Hello world")
        assert section.included is True

    def test_add_section_with_source_and_truncated(self):
        """add_section should accept source and truncated kwargs."""
        report = PromptReport()
        report.add_section(
            "soul",
            "soul content",
            source="workspace",
            truncated=True,
        )
        section = report.sections[0]
        assert section.source == "workspace"
        assert section.truncated is True

    def test_add_skipped(self):
        """add_skipped should append a non-included section."""
        report = PromptReport()
        report.add_skipped("identity", reason="not loaded")
        assert len(report.sections) == 1
        section = report.sections[0]
        assert section.name == "identity"
        assert section.included is False
        assert section.chars == 0
        assert section.source == "not loaded"

    def test_add_warning(self):
        """add_warning should append to the warnings list."""
        report = PromptReport()
        report.add_warning("truncation occurred")
        assert len(report.warnings) == 1
        assert report.warnings[0] == "truncation occurred"

    def test_included_section_count(self):
        """included_section_count should count only included sections."""
        report = PromptReport()
        report.add_section("base", "content")
        report.add_section("tools", "tool content")
        report.add_skipped("soul", reason="missing")
        assert report.included_section_count == 2

    def test_summary_format(self):
        """summary() should return a human-readable string."""
        report = PromptReport()
        report.total_chars = 5000
        report.add_section("base", "x" * 3000)
        report.add_section(
            "soul",
            "y" * 1000,
            source="workspace",
            truncated=True,
        )
        report.add_skipped("identity", reason="not loaded")
        report.add_warning("test warning")

        summary = report.summary()
        assert "5000 chars" in summary
        assert "2 sections" in summary
        assert "[OK] base: 3000 chars" in summary
        assert "[OK] soul: 1000 chars [TRUNCATED] (workspace)" in summary
        assert "[SKIPPED] identity: 0 chars (not loaded)" in summary
        assert "test warning" in summary

    def test_summary_no_warnings(self):
        """summary() without warnings should not have Warnings section."""
        report = PromptReport()
        report.total_chars = 100
        report.add_section("base", "x" * 100)
        summary = report.summary()
        assert "Warnings" not in summary

    def test_is_mutable(self):
        """PromptReport is NOT frozen; mutation should work."""
        report = PromptReport()
        report.total_chars = 999
        assert report.total_chars == 999
        report.warnings.append("new warning")
        assert len(report.warnings) == 1

    def test_persona_default_is_empty(self):
        """Default persona on PromptReport should be AgentPersona.empty()."""
        report = PromptReport()
        assert isinstance(report.persona, AgentPersona)
        assert report.persona.has_any is False

    def test_multiple_sections_ordering(self):
        """Sections should maintain insertion order."""
        report = PromptReport()
        report.add_section("first", "a")
        report.add_section("second", "bb")
        report.add_skipped("third")
        report.add_section("fourth", "dddd")

        names = [s.name for s in report.sections]
        assert names == ["first", "second", "third", "fourth"]
