"""Tests for JSON type safety models and TypeDecorators."""

import pytest
from pydantic import ValidationError

from src.infrastructure.adapters.secondary.persistence.json_types import (
    AgentConfig,
    AgentModelConfig,
    GraphConfig,
    GraphNodeConfig,
    MemoryRule,
    MemoryRuleType,
    MemoryRulesConfig,
    PlanStep,
    PlanStepStatus,
    SandboxConfig,
    ToolCall,
    ToolResult,
)
from src.infrastructure.adapters.secondary.persistence.type_decorators import (
    PydanticListType,
    PydanticType,
    ValidatedJSON,
)


class TestMemoryRulesConfig:
    """Tests for MemoryRulesConfig model."""

    def test_default_values(self):
        config = MemoryRulesConfig()
        assert config.rules == []
        assert config.default_action == "include"
        assert config.max_memory_size is None

    def test_with_rules(self):
        config = MemoryRulesConfig(
            rules=[
                MemoryRule(rule_type=MemoryRuleType.EXCLUDE, pattern="secret_*"),
                MemoryRule(rule_type=MemoryRuleType.INCLUDE, field="content"),
            ],
            max_memory_size=1000,
        )
        assert len(config.rules) == 2
        assert config.rules[0].rule_type == MemoryRuleType.EXCLUDE
        assert config.max_memory_size == 1000

    def test_extra_fields_allowed(self):
        config = MemoryRulesConfig(custom_field="custom_value")
        assert config.custom_field == "custom_value"

    def test_serialization(self):
        config = MemoryRulesConfig(
            rules=[MemoryRule(rule_type=MemoryRuleType.FILTER, pattern="test")],
        )
        data = config.model_dump()
        assert "rules" in data
        assert data["rules"][0]["rule_type"] == "filter"

    def test_from_dict(self):
        data = {
            "rules": [{"rule_type": "include", "pattern": "*.txt"}],
            "default_action": "exclude",
        }
        config = MemoryRulesConfig.model_validate(data)
        assert config.default_action == "exclude"
        assert config.rules[0].pattern == "*.txt"


class TestGraphConfig:
    """Tests for GraphConfig model."""

    def test_default_values(self):
        config = GraphConfig()
        assert config.enabled is True
        assert config.similarity_threshold == 0.7
        assert config.node_types == []

    def test_with_node_types(self):
        config = GraphConfig(
            node_types=[
                GraphNodeConfig(label="Person", properties=["name", "age"]),
                GraphNodeConfig(label="Organization", indexed=True),
            ]
        )
        assert len(config.node_types) == 2
        assert config.node_types[0].label == "Person"
        assert config.node_types[1].indexed is True


class TestAgentConfig:
    """Tests for AgentConfig model."""

    def test_default_values(self):
        config = AgentConfig()
        assert config.model_config_data is None
        assert config.max_iterations == 10
        assert config.doom_loop_threshold == 3

    def test_with_model_config(self):
        config = AgentConfig(
            model_config=AgentModelConfig(provider="openai", model="gpt-4"),
            enabled_tools=["memory_search", "web_search"],
        )
        assert config.model_config_data.provider == "openai"
        assert len(config.enabled_tools) == 2

    def test_serialization_with_alias(self):
        config = AgentConfig(
            model_config=AgentModelConfig(provider="gemini"),
        )
        data = config.model_dump(by_alias=True)
        assert "model_config" in data


class TestPlanStep:
    """Tests for PlanStep model."""

    def test_default_status(self):
        step = PlanStep(index=0, description="Test step")
        assert step.status == PlanStepStatus.PENDING
        assert step.tool_name is None

    def test_completed_step(self):
        step = PlanStep(
            index=1,
            description="Execute tool",
            status=PlanStepStatus.COMPLETED,
            tool_name="test_tool",
            result="Success",
        )
        assert step.status == PlanStepStatus.COMPLETED
        assert step.result == "Success"


class TestToolModels:
    """Tests for ToolCall and ToolResult models."""

    def test_tool_call(self):
        call = ToolCall(
            tool_name="memory_search",
            tool_input={"query": "test", "limit": 10},
            call_id="call-123",
        )
        assert call.tool_name == "memory_search"
        assert call.tool_input["limit"] == 10

    def test_tool_result_success(self):
        result = ToolResult(
            tool_name="web_search",
            success=True,
            result={"items": ["result1", "result2"]},
            execution_time_ms=150,
        )
        assert result.success is True
        assert result.error is None

    def test_tool_result_failure(self):
        result = ToolResult(
            tool_name="broken_tool",
            success=False,
            error="Connection timeout",
        )
        assert result.success is False
        assert result.error == "Connection timeout"


class TestSandboxConfig:
    """Tests for SandboxConfig model."""

    def test_default_values(self):
        config = SandboxConfig()
        assert config.provider == "docker"
        assert config.memory_limit == "2g"
        assert config.timeout_seconds == 300

    def test_custom_config(self):
        config = SandboxConfig(
            provider="kubernetes",
            image="python:3.12",
            memory_limit="4g",
            environment={"DEBUG": "true"},
        )
        assert config.provider == "kubernetes"
        assert config.environment["DEBUG"] == "true"


class TestPydanticTypeDecorator:
    """Tests for PydanticType SQLAlchemy TypeDecorator."""

    def test_process_bind_param_with_model(self):
        decorator = PydanticType(AgentConfig)
        config = AgentConfig(max_iterations=5)
        result = decorator.process_bind_param(config, None)
        assert isinstance(result, dict)
        assert result["max_iterations"] == 5

    def test_process_bind_param_with_dict(self):
        decorator = PydanticType(AgentConfig)
        result = decorator.process_bind_param({"max_iterations": 15}, None)
        assert result["max_iterations"] == 15

    def test_process_bind_param_validates(self):
        decorator = PydanticType(PlanStep)
        # Missing required field 'description'
        with pytest.raises(ValidationError):
            decorator.process_bind_param({"index": 0}, None)

    def test_process_result_value(self):
        decorator = PydanticType(AgentConfig)
        result = decorator.process_result_value({"max_iterations": 20}, None)
        assert isinstance(result, AgentConfig)
        assert result.max_iterations == 20

    def test_process_none_values(self):
        decorator = PydanticType(AgentConfig)
        assert decorator.process_bind_param(None, None) is None
        assert decorator.process_result_value(None, None) is None


class TestPydanticListTypeDecorator:
    """Tests for PydanticListType SQLAlchemy TypeDecorator."""

    def test_process_bind_param_with_models(self):
        decorator = PydanticListType(PlanStep)
        steps = [
            PlanStep(index=0, description="Step 1"),
            PlanStep(index=1, description="Step 2"),
        ]
        result = decorator.process_bind_param(steps, None)
        assert len(result) == 2
        assert result[0]["index"] == 0

    def test_process_bind_param_with_dicts(self):
        decorator = PydanticListType(ToolCall)
        calls = [
            {"tool_name": "tool1", "tool_input": {}},
            {"tool_name": "tool2", "tool_input": {"key": "value"}},
        ]
        result = decorator.process_bind_param(calls, None)
        assert len(result) == 2

    def test_process_result_value(self):
        decorator = PydanticListType(ToolResult)
        data = [
            {"tool_name": "tool1", "success": True},
            {"tool_name": "tool2", "success": False, "error": "Failed"},
        ]
        result = decorator.process_result_value(data, None)
        assert len(result) == 2
        assert isinstance(result[0], ToolResult)
        assert result[1].error == "Failed"


class TestValidatedJSONDecorator:
    """Tests for ValidatedJSON SQLAlchemy TypeDecorator."""

    def test_with_validation(self):
        decorator = ValidatedJSON(AgentConfig)
        result = decorator.process_bind_param({"max_iterations": 10}, None)
        assert result["max_iterations"] == 10

    def test_without_validation(self):
        decorator = ValidatedJSON()
        result = decorator.process_bind_param({"any": "data"}, None)
        assert result["any"] == "data"

    def test_returns_dict_on_read(self):
        decorator = ValidatedJSON(AgentConfig)
        result = decorator.process_result_value({"max_iterations": 5}, None)
        # Should return dict, not model (for performance)
        assert isinstance(result, dict)
