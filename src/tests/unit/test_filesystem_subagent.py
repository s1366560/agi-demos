"""
Tests for filesystem SubAgent loading system.

Tests the markdown parser, filesystem scanner, filesystem loader,
SubAgent source enum, and SubAgentService merge logic.
"""

import logging
import tempfile
from pathlib import Path

import pytest

from src.application.services.subagent_service import SubAgentService
from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.model.agent.subagent_source import SubAgentSource
from src.infrastructure.agent.subagent.agent_validator import (
    SubAgentValidator,
)
from src.infrastructure.agent.subagent.filesystem_loader import (
    MODEL_MAPPING,
    FileSystemSubAgentLoader,
)
from src.infrastructure.agent.subagent.filesystem_scanner import (
    FileSystemSubAgentScanner,
)
from src.infrastructure.agent.subagent.markdown_parser import (
    SubAgentMarkdown,
    SubAgentMarkdownParser,
    SubAgentParseError,
)
from src.infrastructure.agent.subagent.override_resolver import AgentOverrideResolver

# =============================================================================
# SubAgentMarkdownParser Tests
# =============================================================================


class TestSubAgentMarkdownParser:
    """Tests for SubAgentMarkdownParser."""

    def setup_method(self):
        self.parser = SubAgentMarkdownParser()

    def test_parse_basic_agent(self):
        """Parse a basic agent definition."""
        content = """---
name: architect
description: Software architecture specialist
tools: ["Read", "Grep", "Glob"]
model: opus
---

You are a senior software architect."""

        result = self.parser.parse(content)

        assert result.name == "architect"
        assert result.description == "Software architecture specialist"
        assert result.tools == ["Read", "Grep", "Glob"]
        assert result.model_raw == "opus"
        assert result.content == "You are a senior software architect."
        assert result.enabled is True

    def test_parse_extended_frontmatter(self):
        """Parse agent with extended fields."""
        content = """---
name: code-reviewer
description: Code review specialist
tools: ["Read", "Bash"]
model: sonnet
display_name: Code Reviewer Pro
keywords: ["review", "audit", "check"]
examples: ["Review this code", "Check for bugs"]
max_iterations: 15
temperature: 0.5
color: "#FF5733"
enabled: false
---

# Code Reviewer

Review code thoroughly."""

        result = self.parser.parse(content)

        assert result.name == "code-reviewer"
        assert result.display_name == "Code Reviewer Pro"
        assert result.keywords == ["review", "audit", "check"]
        assert result.examples == ["Review this code", "Check for bugs"]
        assert result.max_iterations == 15
        assert result.temperature == 0.5
        assert result.color == "#FF5733"
        assert result.enabled is False

    def test_parse_minimal_frontmatter(self):
        """Parse with only required fields."""
        content = """---
name: simple-agent
description: A simple agent
---

Do things."""

        result = self.parser.parse(content)

        assert result.name == "simple-agent"
        assert result.description == "A simple agent"
        assert result.tools == []
        assert result.model_raw == "inherit"
        assert result.content == "Do things."

    def test_parse_missing_name_raises(self):
        """Missing name should raise error."""
        content = """---
description: No name agent
---

Content."""

        with pytest.raises(SubAgentParseError, match="Missing required field 'name'"):
            self.parser.parse(content)

    def test_parse_empty_content_raises(self):
        """Empty content should raise error."""
        with pytest.raises(SubAgentParseError, match="Empty content"):
            self.parser.parse("")

    def test_parse_no_frontmatter_raises(self):
        """Content without frontmatter should raise error."""
        with pytest.raises(SubAgentParseError, match="missing or malformed YAML"):
            self.parser.parse("Just some text without frontmatter")

    def test_parse_invalid_yaml_raises(self):
        """Invalid YAML should raise error."""
        content = """---
name: [invalid yaml
  : broken
---

Content."""

        with pytest.raises(SubAgentParseError, match="Invalid YAML"):
            self.parser.parse(content)

    def test_parse_tools_as_comma_string(self):
        """Tools as comma-separated string."""
        content = """---
name: test
description: test
tools: Read, Write, Bash
---

Content."""

        result = self.parser.parse(content)
        assert result.tools == ["Read", "Write", "Bash"]

    def test_parse_file(self):
        """Parse from actual file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("""---
name: file-agent
description: From file
tools: ["Read"]
model: gpt-4
---

System prompt from file.""")
            f.flush()

            result = self.parser.parse_file(f.name)

        assert result.name == "file-agent"
        assert result.model_raw == "gpt-4"

    def test_parse_file_not_found(self):
        """Missing file should raise error."""
        with pytest.raises(SubAgentParseError, match="File not found"):
            self.parser.parse_file("/nonexistent/path.md")

    def test_parse_enabled_string_values(self):
        """Boolean-like strings for enabled field."""
        for val, expected in [("true", True), ("false", False), ("yes", True), ("no", False)]:
            content = f"""---
name: test
description: test
enabled: {val}
---

Content."""
            result = self.parser.parse(content)
            assert result.enabled == expected, f"'{val}' should be {expected}"


# =============================================================================
# SubAgentMarkdownParser New Fields Tests
# =============================================================================


class TestSubAgentMarkdownParserNewFields:
    """Tests for 7 new fields added to SubAgentMarkdown."""

    def setup_method(self):
        self.parser = SubAgentMarkdownParser()

    def _make_content(self, **extra_fields: object) -> str:
        """Build minimal valid agent markdown with optional extra frontmatter fields."""
        lines = ["---", "name: test-agent", "description: Test agent"]
        for key, val in extra_fields.items():
            lines.append(f"{key}: {val}")
        lines.append("---")
        lines.append("")
        lines.append("System prompt.")
        return "\n".join(lines)

    # -- max_tokens --

    def test_parse_max_tokens(self):
        """YAML with max_tokens: 4096."""
        result = self.parser.parse(self._make_content(max_tokens=4096))
        assert result.max_tokens == 4096

    def test_parse_max_tokens_absent(self):
        """YAML without max_tokens."""
        result = self.parser.parse(self._make_content())
        assert result.max_tokens is None

    def test_parse_max_tokens_invalid_string(self):
        """YAML with max_tokens: not_a_number."""
        result = self.parser.parse(self._make_content(max_tokens="not_a_number"))
        assert result.max_tokens is None

    # -- max_retries --

    def test_parse_max_retries(self):
        """YAML with max_retries: 3."""
        result = self.parser.parse(self._make_content(max_retries=3))
        assert result.max_retries == 3

    def test_parse_max_retries_absent(self):
        """YAML without max_retries."""
        result = self.parser.parse(self._make_content())
        assert result.max_retries is None

    # -- fallback_models --

    def test_parse_fallback_models_list(self):
        """YAML list of fallback_models."""
        content = """---
name: test-agent
description: Test agent
fallback_models: ["gpt-4", "deepseek"]
---

System prompt."""
        result = self.parser.parse(content)
        assert result.fallback_models == ["gpt-4", "deepseek"]

    def test_parse_fallback_models_absent(self):
        """No fallback_models field."""
        result = self.parser.parse(self._make_content())
        assert result.fallback_models == []

    def test_parse_fallback_models_comma_string(self):
        """YAML with fallback_models as comma-separated string."""
        content = """---
name: test-agent
description: Test agent
fallback_models: gpt-4, deepseek
---

System prompt."""
        result = self.parser.parse(content)
        assert result.fallback_models == ["gpt-4", "deepseek"]

    # -- allowed_skills --

    def test_parse_allowed_skills(self):
        """YAML list of allowed_skills."""
        content = """---
name: test-agent
description: Test agent
allowed_skills: ["code-review", "search"]
---

System prompt."""
        result = self.parser.parse(content)
        assert result.allowed_skills == ["code-review", "search"]

    def test_parse_allowed_skills_absent(self):
        """No allowed_skills field."""
        result = self.parser.parse(self._make_content())
        assert result.allowed_skills == []

    # -- allowed_mcp_servers --

    def test_parse_allowed_mcp_servers(self):
        """YAML list of allowed_mcp_servers."""
        content = """---
name: test-agent
description: Test agent
allowed_mcp_servers: ["github", "jira"]
---

System prompt."""
        result = self.parser.parse(content)
        assert result.allowed_mcp_servers == ["github", "jira"]

    def test_parse_allowed_mcp_servers_absent(self):
        """No allowed_mcp_servers field."""
        result = self.parser.parse(self._make_content())
        assert result.allowed_mcp_servers == []

    # -- mode --

    def test_parse_mode_subagent(self):
        """mode: subagent."""
        result = self.parser.parse(self._make_content(mode="subagent"))
        assert result.mode == "subagent"

    def test_parse_mode_primary(self):
        """mode: primary."""
        result = self.parser.parse(self._make_content(mode="primary"))
        assert result.mode == "primary"

    def test_parse_mode_all(self):
        """mode: all."""
        result = self.parser.parse(self._make_content(mode="all"))
        assert result.mode == "all"

    def test_parse_mode_invalid_falls_back(self):
        """mode: invalid falls back to default 'subagent'."""
        result = self.parser.parse(self._make_content(mode="invalid"))
        assert result.mode == "subagent"

    def test_parse_mode_absent(self):
        """No mode field defaults to 'subagent'."""
        result = self.parser.parse(self._make_content())
        assert result.mode == "subagent"

    # -- allow_spawn --

    def test_parse_allow_spawn_true(self):
        """allow_spawn: true."""
        result = self.parser.parse(self._make_content(allow_spawn="true"))
        assert result.allow_spawn is True

    def test_parse_allow_spawn_false(self):
        """allow_spawn: false."""
        result = self.parser.parse(self._make_content(allow_spawn="false"))
        assert result.allow_spawn is False

    def test_parse_allow_spawn_absent(self):
        """No allow_spawn field defaults to False."""
        result = self.parser.parse(self._make_content())
        assert result.allow_spawn is False

    # -- all fields together --

    def test_parse_all_new_fields_together(self):
        """YAML with all 7 new fields."""
        content = """---
name: full-agent
description: Full featured agent
max_tokens: 8192
max_retries: 5
fallback_models: ["gpt-4", "deepseek"]
allowed_skills: ["code-review"]
allowed_mcp_servers: ["github"]
mode: primary
allow_spawn: true
---

Full system prompt."""
        result = self.parser.parse(content)
        assert result.max_tokens == 8192
        assert result.max_retries == 5
        assert result.fallback_models == ["gpt-4", "deepseek"]
        assert result.allowed_skills == ["code-review"]
        assert result.allowed_mcp_servers == ["github"]
        assert result.mode == "primary"
        assert result.allow_spawn is True


# =============================================================================
# FileSystemSubAgentScanner Tests
# =============================================================================


class TestFileSystemSubAgentScanner:
    """Tests for FileSystemSubAgentScanner."""

    def test_scan_empty_directory(self, tmp_path):
        """Scan empty directory returns no agents."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)

        scanner = FileSystemSubAgentScanner(include_global=False)
        result = scanner.scan(tmp_path)

        assert result.count == 0
        assert len(result.errors) == 0

    def test_scan_finds_md_files(self, tmp_path):
        """Scanner finds .md files in agents directory."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)

        (agents_dir / "architect.md").write_text("---\nname: architect\n---\nContent")
        (agents_dir / "reviewer.md").write_text("---\nname: reviewer\n---\nContent")

        scanner = FileSystemSubAgentScanner(include_global=False)
        result = scanner.scan(tmp_path)

        assert result.count == 2
        names = result.get_agent_names()
        assert "architect" in names
        assert "reviewer" in names

    def test_scan_ignores_non_md_files(self, tmp_path):
        """Scanner ignores non-.md files."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)

        (agents_dir / "agent.md").write_text("---\nname: agent\n---\nContent")
        (agents_dir / "README.txt").write_text("Not an agent")
        (agents_dir / "notes.json").write_text("{}")

        scanner = FileSystemSubAgentScanner(include_global=False)
        result = scanner.scan(tmp_path)

        assert result.count == 1
        assert result.agents[0].name == "agent"

    def test_scan_ignores_hidden_files(self, tmp_path):
        """Scanner ignores hidden files."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)

        (agents_dir / "visible.md").write_text("---\nname: visible\n---\nContent")
        (agents_dir / ".hidden.md").write_text("---\nname: hidden\n---\nContent")

        scanner = FileSystemSubAgentScanner(include_global=False)
        result = scanner.scan(tmp_path)

        assert result.count == 1
        assert result.agents[0].name == "visible"

    def test_scan_ignores_directories(self, tmp_path):
        """Scanner ignores subdirectories (flat file convention)."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)

        (agents_dir / "agent.md").write_text("---\nname: agent\n---\nContent")
        subdir = agents_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.md").write_text("---\nname: nested\n---\nContent")

        scanner = FileSystemSubAgentScanner(include_global=False)
        result = scanner.scan(tmp_path)

        assert result.count == 1
        assert result.agents[0].name == "agent"

    def test_scan_nonexistent_base_path(self):
        """Non-existent base path returns error."""
        scanner = FileSystemSubAgentScanner(include_global=False)
        result = scanner.scan(Path("/nonexistent/path"))

        assert result.count == 0
        assert len(result.errors) == 1

    def test_scan_source_type_project(self, tmp_path):
        """Project agents have source_type 'project'."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "test.md").write_text("---\nname: test\n---\nContent")

        scanner = FileSystemSubAgentScanner(include_global=False)
        result = scanner.scan(tmp_path)

        assert result.agents[0].source_type == "project"

    def test_scan_custom_dirs(self, tmp_path):
        """Scanner supports custom directories."""
        custom_dir = tmp_path / "custom" / "agents"
        custom_dir.mkdir(parents=True)
        (custom_dir / "custom-agent.md").write_text("---\nname: custom\n---\nContent")

        scanner = FileSystemSubAgentScanner(
            agent_dirs=["custom/agents"],
            include_global=False,
        )
        result = scanner.scan(tmp_path)

        assert result.count == 1
        assert result.agents[0].name == "custom-agent"


# =============================================================================
# FileSystemSubAgentLoader Tests
# =============================================================================


class TestFileSystemSubAgentLoader:
    """Tests for FileSystemSubAgentLoader."""

    def _create_agent_file(self, agents_dir: Path, name: str, **kwargs) -> Path:
        """Helper to create an agent .md file."""
        model = kwargs.get("model", "opus")
        description = kwargs.get("description", f"Test {name} agent")
        tools = kwargs.get("tools", '["Read", "Grep"]')
        body = kwargs.get("body", f"You are {name}.")

        content = f"""---
name: {name}
description: {description}
tools: {tools}
model: {model}
---

{body}"""
        filepath = agents_dir / f"{name}.md"
        filepath.write_text(content)
        return filepath

    async def test_load_all_basic(self, tmp_path):
        """Load all SubAgents from filesystem."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)
        self._create_agent_file(agents_dir, "architect")
        self._create_agent_file(agents_dir, "reviewer")

        loader = FileSystemSubAgentLoader(
            base_path=tmp_path,
            tenant_id="test-tenant",
        )
        result = await loader.load_all()

        assert result.count == 2
        names = [l.subagent.name for l in result.subagents]
        assert "architect" in names
        assert "reviewer" in names

    async def test_load_maps_fields_correctly(self, tmp_path):
        """Verify field mapping from markdown to SubAgent domain entity."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)
        self._create_agent_file(
            agents_dir,
            "architect",
            description="Architecture specialist",
            model="opus",
            tools='["Read", "Grep", "Glob"]',
            body="You are an architect.",
        )

        loader = FileSystemSubAgentLoader(
            base_path=tmp_path,
            tenant_id="t1",
            project_id="p1",
        )
        result = await loader.load_all()
        sa = result.subagents[0].subagent

        assert sa.name == "architect"
        assert sa.display_name == "Architect"
        assert sa.tenant_id == "t1"
        assert sa.project_id == "p1"
        assert sa.system_prompt == "You are an architect."
        assert sa.trigger.description == "Architecture specialist"
        assert sa.model == AgentModel.CLAUDE_SONNET  # opus maps to CLAUDE_SONNET
        assert sa.allowed_tools == ["read", "grep", "glob"]  # lowercased
        assert sa.source == SubAgentSource.FILESYSTEM
        assert sa.file_path is not None
        assert sa.id.startswith("fs-")

    async def test_load_model_mapping(self, tmp_path):
        """Verify model name mapping."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)

        for model_name, _expected_enum in [
            ("opus", AgentModel.CLAUDE_SONNET),
            ("sonnet", AgentModel.CLAUDE_SONNET),
            ("gpt-4", AgentModel.GPT4),
            ("deepseek", AgentModel.DEEPSEEK),
            ("gemini", AgentModel.GEMINI),
            ("inherit", AgentModel.INHERIT),
            ("unknown-model", AgentModel.INHERIT),
        ]:
            safe_name = model_name.replace("-", "").replace(".", "")
            self._create_agent_file(agents_dir, f"agent-{safe_name}", model=model_name)

        loader = FileSystemSubAgentLoader(
            base_path=tmp_path,
            tenant_id="t1",
        )
        result = await loader.load_all()

        for loaded in result.subagents:
            model_name = loaded.markdown.model_raw
            safe_name = model_name.replace("-", "").replace(".", "")
            expected = MODEL_MAPPING.get(model_name.lower(), AgentModel.INHERIT)
            assert loaded.subagent.model == expected, (
                f"Model '{model_name}' should map to {expected}, got {loaded.subagent.model}"
            )

    async def test_load_caches_results(self, tmp_path):
        """Second load_all() returns cached results."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)
        self._create_agent_file(agents_dir, "agent1")

        loader = FileSystemSubAgentLoader(base_path=tmp_path, tenant_id="t1")

        result1 = await loader.load_all()
        assert result1.count == 1

        # Add another file after first load
        self._create_agent_file(agents_dir, "agent2")

        # Should return cached result (still 1)
        result2 = await loader.load_all()
        assert result2.count == 1

        # Force reload should pick up new file
        result3 = await loader.load_all(force_reload=True)
        assert result3.count == 2

    async def test_load_handles_parse_errors(self, tmp_path):
        """Invalid files are reported as errors, not crashes."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)

        self._create_agent_file(agents_dir, "good-agent")
        (agents_dir / "bad-agent.md").write_text("No frontmatter here")

        loader = FileSystemSubAgentLoader(base_path=tmp_path, tenant_id="t1")
        result = await loader.load_all()

        assert result.count == 1
        assert result.subagents[0].subagent.name == "good-agent"
        assert len(result.errors) == 1

    async def test_load_empty_directory(self, tmp_path):
        """Empty directory returns empty result."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)

        loader = FileSystemSubAgentLoader(base_path=tmp_path, tenant_id="t1")
        result = await loader.load_all()

        assert result.count == 0
        assert len(result.errors) == 0

    async def test_invalidate_cache(self, tmp_path):
        """Cache invalidation forces reload."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)
        self._create_agent_file(agents_dir, "agent1")

        loader = FileSystemSubAgentLoader(base_path=tmp_path, tenant_id="t1")
        result1 = await loader.load_all()
        assert result1.count == 1

        self._create_agent_file(agents_dir, "agent2")
        loader.invalidate_cache()

        result2 = await loader.load_all()
        assert result2.count == 2


# =============================================================================
# SubAgentSource Tests
# =============================================================================


class TestSubAgentSource:
    """Tests for SubAgentSource enum."""

    def test_values(self):
        assert SubAgentSource.FILESYSTEM == "filesystem"
        assert SubAgentSource.DATABASE == "database"

    def test_str(self):
        assert str(SubAgentSource.FILESYSTEM) == "filesystem"
        assert str(SubAgentSource.DATABASE) == "database"


# =============================================================================
# SubAgent Domain Model Extension Tests
# =============================================================================


class TestSubAgentSourceField:
    """Tests for SubAgent source and file_path fields."""

    def test_default_source_is_database(self):
        """New SubAgents default to DATABASE source."""
        sa = SubAgent.create(
            tenant_id="t1",
            name="test",
            display_name="Test",
            system_prompt="prompt",
            trigger_description="desc",
        )
        assert sa.source == SubAgentSource.DATABASE
        assert sa.file_path is None

    def test_filesystem_source(self):
        """SubAgent can be created with FILESYSTEM source."""
        sa = SubAgent(
            id="fs-test",
            tenant_id="t1",
            name="test",
            display_name="Test",
            system_prompt="prompt",
            trigger=AgentTrigger(description="desc"),
            source=SubAgentSource.FILESYSTEM,
            file_path="/path/to/test.md",
        )
        assert sa.source == SubAgentSource.FILESYSTEM
        assert sa.file_path == "/path/to/test.md"

    def test_to_dict_includes_source(self):
        """to_dict includes source and file_path."""
        sa = SubAgent(
            id="fs-test",
            tenant_id="t1",
            name="test",
            display_name="Test",
            system_prompt="prompt",
            trigger=AgentTrigger(description="desc"),
            source=SubAgentSource.FILESYSTEM,
            file_path="/path/to/test.md",
        )
        d = sa.to_dict()
        assert d["source"] == "filesystem"
        assert d["file_path"] == "/path/to/test.md"

    def test_from_dict_with_source(self):
        """from_dict correctly parses source field."""
        data = {
            "id": "test-id",
            "tenant_id": "t1",
            "name": "test",
            "display_name": "Test",
            "system_prompt": "prompt",
            "trigger": {"description": "desc"},
            "source": "filesystem",
            "file_path": "/path/to/test.md",
        }
        sa = SubAgent.from_dict(data)
        assert sa.source == SubAgentSource.FILESYSTEM
        assert sa.file_path == "/path/to/test.md"

    def test_from_dict_without_source_defaults_to_database(self):
        """from_dict without source field defaults to DATABASE."""
        data = {
            "id": "test-id",
            "tenant_id": "t1",
            "name": "test",
            "display_name": "Test",
            "system_prompt": "prompt",
            "trigger": {"description": "desc"},
        }
        sa = SubAgent.from_dict(data)
        assert sa.source == SubAgentSource.DATABASE
        assert sa.file_path is None

    def test_record_execution_preserves_source(self):
        """record_execution preserves source and file_path."""
        sa = SubAgent(
            id="fs-test",
            tenant_id="t1",
            name="test",
            display_name="Test",
            system_prompt="prompt",
            trigger=AgentTrigger(description="desc"),
            source=SubAgentSource.FILESYSTEM,
            file_path="/path/to/test.md",
        )
        updated = sa.record_execution(100.0, True)
        assert updated.source == SubAgentSource.FILESYSTEM
        assert updated.file_path == "/path/to/test.md"


# =============================================================================
# SubAgentService Merge Tests
# =============================================================================


class TestSubAgentService:
    """Tests for SubAgentService merge logic."""

    def _make_subagent(
        self, name: str, source: SubAgentSource = SubAgentSource.DATABASE
    ) -> SubAgent:
        return SubAgent(
            id=f"{source.value}-{name}",
            tenant_id="t1",
            name=name,
            display_name=name.title(),
            system_prompt=f"Prompt for {name}",
            trigger=AgentTrigger(description=f"Desc for {name}"),
            source=source,
        )

    def test_merge_no_overlap(self):
        """No name overlap: all agents included."""
        db = [self._make_subagent("db-agent", SubAgentSource.DATABASE)]
        fs = [self._make_subagent("fs-agent", SubAgentSource.FILESYSTEM)]

        service = SubAgentService()
        result = service.merge(db, fs)

        assert len(result) == 2
        names = {a.name for a in result}
        assert names == {"db-agent", "fs-agent"}

    def test_merge_db_overrides_fs(self):
        """DB agent overrides FS agent with same name."""
        db = [self._make_subagent("architect", SubAgentSource.DATABASE)]
        fs = [self._make_subagent("architect", SubAgentSource.FILESYSTEM)]

        service = SubAgentService()
        result = service.merge(db, fs)

        assert len(result) == 1
        assert result[0].source == SubAgentSource.DATABASE

    def test_merge_partial_overlap(self):
        """Mixed: some overlap, some unique."""
        db = [
            self._make_subagent("shared", SubAgentSource.DATABASE),
            self._make_subagent("db-only", SubAgentSource.DATABASE),
        ]
        fs = [
            self._make_subagent("shared", SubAgentSource.FILESYSTEM),
            self._make_subagent("fs-only", SubAgentSource.FILESYSTEM),
        ]

        service = SubAgentService()
        result = service.merge(db, fs)

        assert len(result) == 3
        names = {a.name for a in result}
        assert names == {"shared", "db-only", "fs-only"}

        # shared should be DB version
        shared = next(a for a in result if a.name == "shared")
        assert shared.source == SubAgentSource.DATABASE

    def test_merge_empty_db(self):
        """Empty DB: all FS agents returned."""
        fs = [
            self._make_subagent("a", SubAgentSource.FILESYSTEM),
            self._make_subagent("b", SubAgentSource.FILESYSTEM),
        ]

        service = SubAgentService()
        result = service.merge([], fs)

        assert len(result) == 2

    def test_merge_empty_fs(self):
        """Empty FS: all DB agents returned."""
        db = [
            self._make_subagent("a", SubAgentSource.DATABASE),
        ]

        service = SubAgentService()
        result = service.merge(db, [])

        assert len(result) == 1

    def test_merge_both_empty(self):
        """Both empty: empty result."""
        service = SubAgentService()
        result = service.merge([], [])

        assert len(result) == 0

    async def test_load_filesystem_subagents(self, tmp_path):
        """SubAgentService loads from filesystem via loader."""
        agents_dir = tmp_path / ".memstack" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "test.md").write_text(
            "---\nname: test\ndescription: Test agent\ntools: [Read]\nmodel: opus\n---\n\nPrompt."
        )

        loader = FileSystemSubAgentLoader(
            base_path=tmp_path,
            tenant_id="t1",
        )
        service = SubAgentService(filesystem_loader=loader)
        result = await service.load_filesystem_subagents()

        assert len(result) == 1
        assert result[0].name == "test"
        assert result[0].source == SubAgentSource.FILESYSTEM

    async def test_load_filesystem_no_loader(self):
        """Without filesystem loader, returns empty list."""
        service = SubAgentService()
        result = await service.load_filesystem_subagents()
        assert result == []


# =============================================================================
# Integration: Real .memstack/agents/ files
# =============================================================================


@pytest.mark.unit
class TestRealAgentFiles:
    """Test loading the actual .memstack/agents/ files in the repo."""

    async def test_load_real_agents_if_present(self):
        """Load real agent files from the repo root if they exist."""
        repo_root = Path.cwd()
        agents_dir = repo_root / ".memstack" / "agents"

        if not agents_dir.exists():
            pytest.skip("No .memstack/agents/ directory in repo root")

        loader = FileSystemSubAgentLoader(
            base_path=repo_root,
            tenant_id="test-tenant",
            project_id="test-project",
        )
        result = await loader.load_all()

        # Should load some agents (we know there are 13)
        assert result.count > 0
        assert len(result.errors) == 0

        # Verify all have required fields
        for loaded in result.subagents:
            sa = loaded.subagent
            assert sa.name
            assert sa.display_name
            assert sa.system_prompt
            assert sa.trigger.description
            assert sa.source == SubAgentSource.FILESYSTEM
            assert sa.tenant_id == "test-tenant"


# =============================================================================
# SubAgentValidator Tests
# =============================================================================


class TestSubAgentValidator:
    """Tests for all 11 validation checks in SubAgentValidator."""

    def setup_method(self):
        self.validator = SubAgentValidator()

    @staticmethod
    def _make_markdown(**overrides: object) -> SubAgentMarkdown:
        """Build a valid SubAgentMarkdown, overriding specific fields."""
        defaults: dict[str, object] = {
            "frontmatter": {},
            "content": "Valid system prompt",
            "name": "test-agent",
            "description": "Test description",
            "tools": [],
            "model_raw": "sonnet",
        }
        defaults.update(overrides)
        return SubAgentMarkdown(**defaults)  # type: ignore[arg-type]

    # -- identity checks --

    def test_valid_agent_passes(self):
        """All fields valid, no errors or warnings."""
        result = self.validator.validate(self._make_markdown())
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_empty_name_error(self):
        """Empty name must produce an error."""
        result = self.validator.validate(self._make_markdown(name=""))
        assert result.valid is False
        assert any("name must not be empty" in e for e in result.errors)

    def test_long_name_error(self):
        """Name > 100 characters must produce an error."""
        result = self.validator.validate(self._make_markdown(name="x" * 101))
        assert result.valid is False
        assert any("name must be 1-100 characters" in e for e in result.errors)

    def test_empty_description_warning(self):
        """Empty description is a warning, not an error."""
        result = self.validator.validate(self._make_markdown(description=""))
        assert result.valid is True
        assert any("description is empty" in w for w in result.warnings)

    # -- safety constraints --

    def test_prompt_exceeds_max_length(self):
        """Prompt > 50,000 chars must error."""
        result = self.validator.validate(self._make_markdown(content="x" * 50_001))
        assert result.valid is False
        assert any("maximum length" in e for e in result.errors)

    def test_restricted_tool_plugin_manager(self):
        """plugin_manager is a restricted tool."""
        result = self.validator.validate(self._make_markdown(tools=["read", "plugin_manager"]))
        assert result.valid is False
        assert any("restricted tools" in e for e in result.errors)

    def test_restricted_tool_env_var_set(self):
        """env_var_set is a restricted tool."""
        result = self.validator.validate(self._make_markdown(tools=["env_var_set"]))
        assert result.valid is False
        assert any("restricted tools" in e for e in result.errors)

    def test_allow_spawn_no_tools_warning(self):
        """allow_spawn=True with no tools is a warning."""
        result = self.validator.validate(self._make_markdown(allow_spawn=True, tools=[]))
        assert result.valid is True
        assert any("allow_spawn" in w for w in result.warnings)

    def test_unrecognized_model_warning(self):
        """Unrecognized model produces a warning."""
        result = self.validator.validate(self._make_markdown(model_raw="unknown-model-xyz"))
        assert result.valid is True
        assert any("unrecognized model" in w for w in result.warnings)

    def test_known_model_no_warning(self):
        """Known model produces no warning."""
        result = self.validator.validate(self._make_markdown(model_raw="sonnet"))
        assert result.warnings == []

    # -- numeric range checks --

    def test_temperature_below_range(self):
        """temperature < 0.0 must error."""
        result = self.validator.validate(self._make_markdown(temperature=-0.1))
        assert result.valid is False
        assert any("temperature" in e for e in result.errors)

    def test_temperature_above_range(self):
        """temperature > 2.0 must error."""
        result = self.validator.validate(self._make_markdown(temperature=2.1))
        assert result.valid is False
        assert any("temperature" in e for e in result.errors)

    def test_temperature_at_bounds(self):
        """temperature 0.0 and 2.0 are both valid."""
        for temp in (0.0, 2.0):
            result = self.validator.validate(self._make_markdown(temperature=temp))
            assert result.valid is True, f"temperature={temp} should be valid"

    def test_max_iterations_below_range(self):
        """max_iterations < 1 must error."""
        result = self.validator.validate(self._make_markdown(max_iterations=0))
        assert result.valid is False
        assert any("max_iterations" in e for e in result.errors)

    def test_max_iterations_above_range(self):
        """max_iterations > 50 must error."""
        result = self.validator.validate(self._make_markdown(max_iterations=51))
        assert result.valid is False
        assert any("max_iterations" in e for e in result.errors)

    def test_max_iterations_at_bounds(self):
        """max_iterations 1 and 50 are both valid."""
        for val in (1, 50):
            result = self.validator.validate(self._make_markdown(max_iterations=val))
            assert result.valid is True, f"max_iterations={val} should be valid"

    def test_max_tokens_below_range(self):
        """max_tokens < 1 must error."""
        result = self.validator.validate(self._make_markdown(max_tokens=0))
        assert result.valid is False
        assert any("max_tokens" in e for e in result.errors)

    def test_max_tokens_above_range(self):
        """max_tokens > 1,000,000 must error."""
        result = self.validator.validate(self._make_markdown(max_tokens=1_000_001))
        assert result.valid is False
        assert any("max_tokens" in e for e in result.errors)

    def test_max_retries_below_range(self):
        """max_retries < 0 must error."""
        result = self.validator.validate(self._make_markdown(max_retries=-1))
        assert result.valid is False
        assert any("max_retries" in e for e in result.errors)

    def test_max_retries_above_range(self):
        """max_retries > 10 must error."""
        result = self.validator.validate(self._make_markdown(max_retries=11))
        assert result.valid is False
        assert any("max_retries" in e for e in result.errors)

    # -- mode validation --

    def test_invalid_mode_error(self):
        """Direct SubAgentMarkdown with invalid mode must error."""
        result = self.validator.validate(self._make_markdown(mode="invalid"))
        assert result.valid is False
        assert any("mode" in e for e in result.errors)

    # -- compound checks --

    def test_multiple_errors_collected(self):
        """Multiple errors are all collected."""
        result = self.validator.validate(
            self._make_markdown(
                name="",
                tools=["plugin_manager"],
                temperature=-1.0,
            )
        )
        assert result.valid is False
        assert len(result.errors) >= 3

    def test_errors_and_warnings_mixed(self):
        """Agent with both errors and warnings."""
        result = self.validator.validate(
            self._make_markdown(
                name="",
                description="",
                model_raw="unknown-xyz",
            )
        )
        assert result.valid is False
        assert len(result.errors) >= 1
        assert len(result.warnings) >= 1


# =============================================================================
# AgentOverrideResolver Tests
# =============================================================================


class TestAgentOverrideResolver:
    """Tests for 3-tier SubAgent merge in AgentOverrideResolver."""

    def setup_method(self):
        self.resolver = AgentOverrideResolver()

    @staticmethod
    def _make_subagent(name: str, source: SubAgentSource = SubAgentSource.FILESYSTEM) -> SubAgent:
        """Create a lightweight SubAgent for testing."""
        return SubAgent(
            id=f"test-{name}",
            tenant_id="t1",
            name=name,
            display_name=name.title(),
            system_prompt=f"Prompt for {name}",
            trigger=AgentTrigger(description=f"Desc for {name}"),
            source=source,
        )

    def test_resolve_empty_all_tiers(self):
        """All empty dicts returns empty."""
        result = self.resolver.resolve({}, {}, {})
        assert result == {}

    def test_resolve_global_only(self):
        """Global has 2 agents, others empty."""
        g = {
            "a": self._make_subagent("a"),
            "b": self._make_subagent("b"),
        }
        result = self.resolver.resolve({}, {}, g)
        assert len(result) == 2
        assert set(result.keys()) == {"a", "b"}

    def test_resolve_tenant_overrides_global(self):
        """Same name in global and tenant: tenant wins."""
        g_agent = self._make_subagent("shared", SubAgentSource.FILESYSTEM)
        t_agent = self._make_subagent("shared", SubAgentSource.DATABASE)
        result = self.resolver.resolve({}, {"shared": t_agent}, {"shared": g_agent})
        assert result["shared"] is t_agent

    def test_resolve_project_overrides_tenant(self):
        """Same name in tenant and project: project wins."""
        t_agent = self._make_subagent("shared")
        p_agent = self._make_subagent("shared", SubAgentSource.DATABASE)
        result = self.resolver.resolve({"shared": p_agent}, {"shared": t_agent}, {})
        assert result["shared"] is p_agent

    def test_resolve_project_overrides_all(self):
        """Same name in all 3 tiers: project wins."""
        g_agent = self._make_subagent("shared")
        t_agent = self._make_subagent("shared")
        p_agent = self._make_subagent("shared")
        result = self.resolver.resolve(
            {"shared": p_agent}, {"shared": t_agent}, {"shared": g_agent}
        )
        assert result["shared"] is p_agent

    def test_resolve_no_overlap(self):
        """Different names across tiers are all preserved."""
        g = {"g-agent": self._make_subagent("g-agent")}
        t = {"t-agent": self._make_subagent("t-agent")}
        p = {"p-agent": self._make_subagent("p-agent")}
        result = self.resolver.resolve(p, t, g)
        assert set(result.keys()) == {"g-agent", "t-agent", "p-agent"}

    def test_resolve_partial_overlap(self):
        """Some overlap, some unique: correct merge."""
        g = {
            "shared": self._make_subagent("shared"),
            "g-only": self._make_subagent("g-only"),
        }
        t = {
            "shared": self._make_subagent("shared"),
            "t-only": self._make_subagent("t-only"),
        }
        p_shared = self._make_subagent("shared")
        p = {"shared": p_shared}
        result = self.resolver.resolve(p, t, g)
        assert len(result) == 3
        assert set(result.keys()) == {"shared", "g-only", "t-only"}
        assert result["shared"] is p_shared

    def test_log_overrides_called(self, caplog):
        """Override logging is emitted for agents in multiple tiers."""
        g = {"shared": self._make_subagent("shared")}
        t = {"shared": self._make_subagent("shared")}
        with caplog.at_level(logging.INFO):
            self.resolver.resolve({}, t, g)
        assert any("shared" in record.message for record in caplog.records)
        assert any("tenant" in record.message for record in caplog.records)

    def test_resolve_preserves_agent_identity(self):
        """Winning SubAgent is the exact instance from the winning tier."""
        g_agent = self._make_subagent("a")
        t_agent = self._make_subagent("a")
        p_agent = self._make_subagent("a")
        result = self.resolver.resolve({"a": p_agent}, {"a": t_agent}, {"a": g_agent})
        assert result["a"] is p_agent
        assert result["a"] is not t_agent
        assert result["a"] is not g_agent
