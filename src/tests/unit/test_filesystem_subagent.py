"""
Tests for filesystem SubAgent loading system.

Tests the markdown parser, filesystem scanner, filesystem loader,
SubAgent source enum, and SubAgentService merge logic.
"""

import tempfile
from pathlib import Path

import pytest

from src.application.services.subagent_service import SubAgentService
from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.model.agent.subagent_source import SubAgentSource
from src.infrastructure.agent.subagent.filesystem_loader import (
    MODEL_MAPPING,
    FileSystemSubAgentLoader,
)
from src.infrastructure.agent.subagent.filesystem_scanner import (
    FileSystemSubAgentScanner,
)
from src.infrastructure.agent.subagent.markdown_parser import (
    SubAgentMarkdownParser,
    SubAgentParseError,
)

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
