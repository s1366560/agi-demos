"""Unit tests for the Agent domain entity."""

import uuid

import pytest

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.subagent import AgentModel, AgentTrigger


def _make_agent(**overrides):
    defaults = {
        "id": "agent-1",
        "tenant_id": "tenant-1",
        "name": "test-agent",
        "display_name": "Test Agent",
        "system_prompt": "You are a test agent.",
        "trigger": AgentTrigger(description="test trigger"),
    }
    defaults.update(overrides)
    return Agent(**defaults)


@pytest.mark.unit
class TestAgent:
    def test_create_agent_defaults(self):
        agent = _make_agent()
        assert agent.id == "agent-1"
        assert agent.tenant_id == "tenant-1"
        assert agent.name == "test-agent"
        assert agent.display_name == "Test Agent"
        assert agent.system_prompt == "You are a test agent."
        assert agent.model == AgentModel.INHERIT
        assert agent.temperature == 0.7
        assert agent.max_tokens == 4096
        assert agent.max_iterations == 10
        assert agent.enabled is True
        assert agent.allowed_tools == ["*"]
        assert agent.allowed_skills == []
        assert agent.allowed_mcp_servers == []
        assert agent.can_spawn is False
        assert agent.max_spawn_depth == 3
        assert agent.agent_to_agent_enabled is False
        assert agent.discoverable is True
        assert agent.max_retries == 0
        assert agent.total_invocations == 0
        assert agent.avg_execution_time_ms == 0.0
        assert agent.success_rate == 1.0
        assert agent.project_id is None
        assert agent.metadata is None

    def test_create_agent_empty_id_raises(self):
        with pytest.raises(ValueError, match="id cannot be empty"):
            _make_agent(id="")

    def test_create_agent_empty_tenant_id_raises(self):
        with pytest.raises(ValueError, match="tenant_id cannot be empty"):
            _make_agent(tenant_id="")

    def test_create_agent_empty_name_raises(self):
        with pytest.raises(ValueError, match="name cannot be empty"):
            _make_agent(name="")

    def test_create_agent_empty_display_name_raises(self):
        with pytest.raises(ValueError, match="display_name cannot be empty"):
            _make_agent(display_name="")

    def test_create_agent_empty_system_prompt_raises(self):
        with pytest.raises(ValueError, match="system_prompt cannot be empty"):
            _make_agent(system_prompt="")

    def test_create_agent_invalid_max_tokens_raises(self):
        with pytest.raises(ValueError, match="max_tokens must be positive"):
            _make_agent(max_tokens=0)

    def test_create_agent_invalid_temperature_low_raises(self):
        with pytest.raises(ValueError, match="temperature must be between 0 and 2"):
            _make_agent(temperature=-0.1)

    def test_create_agent_invalid_temperature_high_raises(self):
        with pytest.raises(ValueError, match="temperature must be between 0 and 2"):
            _make_agent(temperature=2.1)

    def test_create_agent_invalid_max_iterations_raises(self):
        with pytest.raises(ValueError, match="max_iterations must be positive"):
            _make_agent(max_iterations=0)

    def test_create_agent_invalid_success_rate_raises(self):
        with pytest.raises(ValueError, match="success_rate must be between 0 and 1"):
            _make_agent(success_rate=1.5)

    def test_create_agent_invalid_max_retries_raises(self):
        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            _make_agent(max_retries=-1)

    def test_create_agent_invalid_max_spawn_depth_raises(self):
        with pytest.raises(ValueError, match="max_spawn_depth must be non-negative"):
            _make_agent(max_spawn_depth=-1)

    def test_is_enabled_true(self):
        agent = _make_agent()
        assert agent.is_enabled() is True

    def test_is_enabled_false(self):
        agent = _make_agent(enabled=False)
        assert agent.is_enabled() is False

    def test_has_tool_access_wildcard(self):
        agent = _make_agent()
        assert agent.has_tool_access("any_tool") is True

    def test_has_tool_access_specific_allowed(self):
        agent = _make_agent(allowed_tools=["search", "write"])
        assert agent.has_tool_access("search") is True

    def test_has_tool_access_specific_denied(self):
        agent = _make_agent(allowed_tools=["search", "write"])
        assert agent.has_tool_access("delete") is False

    def test_has_skill_access_empty_allows_all(self):
        agent = _make_agent()
        assert agent.has_skill_access("any_skill") is True

    def test_has_skill_access_specific_allowed(self):
        agent = _make_agent(allowed_skills=["s1"])
        assert agent.has_skill_access("s1") is True

    def test_has_skill_access_specific_denied(self):
        agent = _make_agent(allowed_skills=["s1"])
        assert agent.has_skill_access("s2") is False

    def test_has_mcp_access_wildcard(self):
        agent = _make_agent(allowed_mcp_servers=["*"])
        assert agent.has_mcp_access("any_server") is True

    def test_has_mcp_access_specific_denied(self):
        agent = _make_agent()
        assert agent.has_mcp_access("any_server") is False

    def test_get_filtered_tools_wildcard(self):
        agent = _make_agent()
        available = ["t1", "t2", "t3"]
        assert agent.get_filtered_tools(available) == ["t1", "t2", "t3"]

    def test_get_filtered_tools_specific(self):
        agent = _make_agent(allowed_tools=["t1", "t3"])
        available = ["t1", "t2", "t3"]
        assert agent.get_filtered_tools(available) == ["t1", "t3"]

    def test_record_execution_first_success(self):
        agent = _make_agent()
        updated = agent.record_execution(100.0, success=True)
        assert updated.total_invocations == 1
        assert updated.avg_execution_time_ms == 100.0
        assert updated.success_rate == 1.0

    def test_record_execution_first_failure(self):
        agent = _make_agent()
        updated = agent.record_execution(100.0, success=False)
        assert updated.total_invocations == 1
        assert updated.success_rate == 0.0

    def test_record_execution_running_average(self):
        agent = _make_agent()
        updated = agent.record_execution(100.0, success=True)
        updated = updated.record_execution(200.0, success=False)
        assert updated.total_invocations == 2
        assert updated.avg_execution_time_ms == 150.0
        assert updated.success_rate == 0.5

    def test_record_execution_returns_new_instance(self):
        agent = _make_agent()
        updated = agent.record_execution(100.0, success=True)
        assert updated is not agent
        assert agent.total_invocations == 0
        assert updated.total_invocations == 1

    def test_to_dict_round_trip(self):
        agent = _make_agent()
        d = agent.to_dict()
        restored = Agent.from_dict(d)
        assert restored.id == agent.id
        assert restored.tenant_id == agent.tenant_id
        assert restored.name == agent.name
        assert restored.display_name == agent.display_name
        assert restored.system_prompt == agent.system_prompt
        assert restored.model == agent.model
        assert restored.temperature == agent.temperature
        assert restored.max_tokens == agent.max_tokens

    def test_from_dict_minimal(self):
        data = {
            "id": "a1",
            "tenant_id": "t1",
            "name": "minimal",
            "system_prompt": "Hello.",
            "trigger": {"description": "minimal trigger"},
        }
        agent = Agent.from_dict(data)
        assert agent.id == "a1"
        assert agent.display_name == "minimal"
        assert agent.model == AgentModel.INHERIT
        assert agent.temperature == 0.7
        assert agent.max_tokens == 4096
        assert agent.max_iterations == 10
        assert agent.enabled is True
        assert agent.allowed_tools == ["*"]

    def test_create_factory_generates_uuid(self):
        agent = Agent.create(
            tenant_id="t1",
            name="factory-agent",
            display_name="Factory Agent",
            system_prompt="Test prompt.",
        )
        parsed = uuid.UUID(agent.id)
        assert parsed.version == 4

    def test_create_factory_defaults(self):
        agent = Agent.create(
            tenant_id="t1",
            name="factory-agent",
            display_name="Factory Agent",
            system_prompt="Test prompt.",
        )
        assert agent.trigger.description == "Default agent trigger"
        assert agent.model == AgentModel.INHERIT
        assert agent.temperature == 0.7
        assert agent.max_tokens == 4096
        assert agent.max_iterations == 10
        assert agent.enabled is True
        assert agent.allowed_tools == ["*"]
        assert agent.allowed_skills == []
        assert agent.can_spawn is False
