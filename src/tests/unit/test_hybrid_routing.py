"""
Unit tests for Phase 2: LLM Intelligent Routing.

Tests for:
- RoutingCandidate and schema building
- LLM response parsing
- IntentRouter
- HybridRouter (keyword + LLM hybrid flow)
- SubAgentOrchestrator.match_async
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.infrastructure.agent.core.subagent_router import SubAgentMatch
from src.infrastructure.agent.routing.hybrid_router import HybridRouter, HybridRouterConfig
from src.infrastructure.agent.routing.intent_router import IntentRouter
from src.infrastructure.agent.routing.schemas import (
    LLMRoutingDecision,
    RoutingCandidate,
    build_routing_system_prompt,
    build_routing_tool_schema,
    parse_routing_response,
)
from src.infrastructure.agent.routing.subagent_orchestrator import (
    SubAgentOrchestrator,
    SubAgentOrchestratorConfig,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def candidates() -> list[RoutingCandidate]:
    return [
        RoutingCandidate(
            name="coder",
            display_name="Coder Agent",
            description="Handles coding and programming tasks",
            examples=["Write a function", "Fix the bug"],
        ),
        RoutingCandidate(
            name="researcher",
            display_name="Research Agent",
            description="Searches for information and summarizes findings",
            examples=["Search for latest AI news"],
        ),
    ]


@pytest.fixture
def sample_subagents() -> list[SubAgent]:
    return [
        SubAgent.create(
            tenant_id="t1",
            name="coder",
            display_name="Coder Agent",
            system_prompt="You are a coding assistant.",
            trigger_description="Handles coding and programming tasks",
            trigger_keywords=["code", "implement", "fix", "debug", "program"],
            trigger_examples=["Write a function", "Fix the bug"],
        ),
        SubAgent.create(
            tenant_id="t1",
            name="researcher",
            display_name="Research Agent",
            system_prompt="You are a research assistant.",
            trigger_description="Searches for information and summarizes findings",
            trigger_keywords=["search", "find", "research", "lookup"],
            trigger_examples=["Search for latest AI news"],
        ),
    ]


@pytest.fixture
def mock_llm_client():
    client = AsyncMock()
    return client


# ============================================================================
# Test Routing Schemas
# ============================================================================


@pytest.mark.unit
class TestRoutingSchemas:
    def test_routing_candidate_frozen(self):
        c = RoutingCandidate(name="test", display_name="Test", description="desc")
        with pytest.raises(AttributeError):
            c.name = "changed"

    def test_build_routing_tool_schema(self, candidates):
        schema = build_routing_tool_schema(candidates)
        assert len(schema) == 1
        func = schema[0]["function"]
        assert func["name"] == "route_to_subagent"

        # Check enum includes all candidates + "none"
        enum_values = func["parameters"]["properties"]["subagent_name"]["enum"]
        assert "coder" in enum_values
        assert "researcher" in enum_values
        assert "none" in enum_values

    def test_build_routing_tool_schema_empty(self):
        schema = build_routing_tool_schema([])
        enum_values = schema[0]["function"]["parameters"]["properties"]["subagent_name"]["enum"]
        assert enum_values == ["none"]

    def test_build_routing_system_prompt(self, candidates):
        prompt = build_routing_system_prompt(candidates)
        assert "query router" in prompt.lower()
        assert "coder" in prompt
        assert "researcher" in prompt
        assert "Write a function" in prompt
        assert "none" in prompt.lower()

    def test_parse_routing_response_with_tool_call(self):
        response = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "coder",
                            "confidence": 0.9,
                            "reasoning": "User wants to write code",
                        }),
                    }
                }
            ],
        }
        decision = parse_routing_response(response)
        assert decision.matched is True
        assert decision.subagent_name == "coder"
        assert decision.confidence == 0.9
        assert "code" in decision.reasoning.lower()

    def test_parse_routing_response_none_selection(self):
        response = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "none",
                            "confidence": 0.3,
                            "reasoning": "General question",
                        }),
                    }
                }
            ],
        }
        decision = parse_routing_response(response)
        assert decision.matched is False
        assert decision.subagent_name is None

    def test_parse_routing_response_no_tool_calls(self):
        response = {"content": "I don't know which agent to use", "tool_calls": []}
        decision = parse_routing_response(response)
        assert decision.matched is False
        assert "did not call" in decision.reasoning.lower()

    def test_parse_routing_response_invalid_json(self):
        response = {
            "tool_calls": [
                {"function": {"name": "route_to_subagent", "arguments": "not-json"}}
            ],
        }
        decision = parse_routing_response(response)
        assert decision.matched is False
        assert "parse" in decision.reasoning.lower()

    def test_parse_routing_response_low_confidence(self):
        response = {
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "coder",
                            "confidence": 0.05,
                            "reasoning": "Very uncertain",
                        }),
                    }
                }
            ],
        }
        decision = parse_routing_response(response)
        assert decision.matched is False

    def test_llm_routing_decision_defaults(self):
        d = LLMRoutingDecision()
        assert d.subagent_name is None
        assert d.confidence == 0.0
        assert d.reasoning == ""
        assert d.matched is False


# ============================================================================
# Test IntentRouter
# ============================================================================


@pytest.mark.unit
class TestIntentRouter:
    async def test_route_success(self, candidates, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "coder",
                            "confidence": 0.85,
                            "reasoning": "User wants to implement a function",
                        }),
                    }
                }
            ],
        }

        router = IntentRouter(llm_client=mock_llm_client, candidates=candidates)
        decision = await router.route("Write a Python function to sort a list")

        assert decision.matched is True
        assert decision.subagent_name == "coder"
        assert decision.confidence == 0.85
        mock_llm_client.generate.assert_called_once()

    async def test_route_no_match(self, candidates, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "none",
                            "confidence": 0.2,
                            "reasoning": "General greeting",
                        }),
                    }
                }
            ],
        }

        router = IntentRouter(llm_client=mock_llm_client, candidates=candidates)
        decision = await router.route("Hello, how are you?")
        assert decision.matched is False

    async def test_route_no_candidates(self, mock_llm_client):
        router = IntentRouter(llm_client=mock_llm_client, candidates=[])
        decision = await router.route("Write code")
        assert decision.matched is False
        assert "No candidates" in decision.reasoning
        mock_llm_client.generate.assert_not_called()

    async def test_route_no_llm_client(self, candidates):
        router = IntentRouter(llm_client=None, candidates=candidates)
        decision = await router.route("Write code")
        assert decision.matched is False
        assert "No LLM client" in decision.reasoning

    async def test_route_llm_failure(self, candidates, mock_llm_client):
        mock_llm_client.generate.side_effect = Exception("API error")
        router = IntentRouter(llm_client=mock_llm_client, candidates=candidates)
        decision = await router.route("Write code")
        assert decision.matched is False
        assert "failed" in decision.reasoning.lower()

    async def test_route_with_context(self, candidates, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "coder",
                            "confidence": 0.9,
                            "reasoning": "Continuation of coding task",
                        }),
                    }
                }
            ],
        }

        router = IntentRouter(llm_client=mock_llm_client, candidates=candidates)
        decision = await router.route(
            "Now add error handling",
            conversation_context="user: Write a function\nassistant: Here is the code...",
        )
        assert decision.matched is True

        # Verify context was included in the message
        call_args = mock_llm_client.generate.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        user_msg = messages[-1]["content"]
        assert "Recent context" in user_msg

    async def test_update_candidates(self, mock_llm_client):
        router = IntentRouter(llm_client=mock_llm_client)
        assert len(router._candidates) == 0

        new_candidates = [
            RoutingCandidate(name="writer", display_name="Writer", description="Writes")
        ]
        router.update_candidates(new_candidates)
        assert len(router._candidates) == 1
        assert "writer" in router._system_prompt


# ============================================================================
# Test HybridRouter
# ============================================================================


@pytest.mark.unit
class TestHybridRouter:
    def test_sync_match_keyword_only(self, sample_subagents):
        """Sync match() should use keyword-only routing."""
        router = HybridRouter(subagents=sample_subagents)
        result = router.match("fix the code bug")
        assert result.subagent is not None
        assert result.subagent.name == "coder"
        assert "Keyword" in result.match_reason

    def test_sync_match_no_match(self, sample_subagents):
        router = HybridRouter(subagents=sample_subagents)
        result = router.match("hello world")
        assert result.subagent is None

    async def test_async_fast_path_high_keyword_confidence(self, sample_subagents, mock_llm_client):
        """High keyword confidence should skip LLM call."""
        config = HybridRouterConfig(keyword_skip_threshold=0.4)
        router = HybridRouter(
            subagents=sample_subagents,
            llm_client=mock_llm_client,
            config=config,
        )
        result = await router.match_async("code implement fix debug program")
        assert result.subagent is not None
        assert result.subagent.name == "coder"
        # LLM should NOT be called (fast path)
        mock_llm_client.generate.assert_not_called()

    async def test_async_llm_fallback(self, sample_subagents, mock_llm_client):
        """Low keyword confidence should trigger LLM routing."""
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "coder",
                            "confidence": 0.85,
                            "reasoning": "User wants to build a REST API",
                        }),
                    }
                }
            ],
        }

        config = HybridRouterConfig(keyword_skip_threshold=0.99)
        router = HybridRouter(
            subagents=sample_subagents,
            llm_client=mock_llm_client,
            config=config,
        )
        result = await router.match_async("Build a REST API with FastAPI")
        assert result.subagent is not None
        assert result.subagent.name == "coder"
        assert "LLM routing" in result.match_reason
        mock_llm_client.generate.assert_called_once()

    async def test_async_llm_no_match(self, sample_subagents, mock_llm_client):
        """LLM returns no match when query is too general."""
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "none",
                            "confidence": 0.2,
                            "reasoning": "General greeting",
                        }),
                    }
                }
            ],
        }

        router = HybridRouter(
            subagents=sample_subagents,
            llm_client=mock_llm_client,
        )
        result = await router.match_async("Hello, how are you today?")
        assert result.subagent is None

    async def test_async_llm_failure_falls_back_to_keyword(
        self, sample_subagents, mock_llm_client
    ):
        """If LLM call fails, should gracefully fall back to keyword result."""
        mock_llm_client.generate.side_effect = Exception("API timeout")

        router = HybridRouter(
            subagents=sample_subagents,
            llm_client=mock_llm_client,
        )
        result = await router.match_async("code fix debug")
        # Should still get keyword match despite LLM failure
        assert result.subagent is not None
        assert result.subagent.name == "coder"

    async def test_async_no_llm_client(self, sample_subagents):
        """Without LLM client, should behave same as keyword-only."""
        router = HybridRouter(subagents=sample_subagents)
        result = await router.match_async("code fix")
        assert result.subagent is not None

    async def test_async_llm_routing_disabled(self, sample_subagents, mock_llm_client):
        """LLM routing can be disabled via config."""
        config = HybridRouterConfig(enable_llm_routing=False)
        router = HybridRouter(
            subagents=sample_subagents,
            llm_client=mock_llm_client,
            config=config,
        )
        result = await router.match_async("Build a REST API")
        mock_llm_client.generate.assert_not_called()

    def test_delegated_methods(self, sample_subagents):
        """Delegated methods should work through to keyword router."""
        router = HybridRouter(subagents=sample_subagents)

        # list_subagents
        agents = router.list_subagents()
        assert len(agents) == 2

        # get_subagent
        assert router.get_subagent("coder") is not None
        assert router.get_subagent("nonexistent") is None

        # get_subagent_config
        coder = router.get_subagent("coder")
        config = router.get_subagent_config(coder)
        assert "system_prompt" in config

        # filter_tools
        tools = {"tool_a": {}, "tool_b": {}}
        filtered = router.filter_tools(coder, tools)
        assert len(filtered) == 2  # wildcard "*" returns all

    async def test_async_with_conversation_context(self, sample_subagents, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "researcher",
                            "confidence": 0.8,
                            "reasoning": "Continuing research task",
                        }),
                    }
                }
            ],
        }

        config = HybridRouterConfig(keyword_skip_threshold=0.99)
        router = HybridRouter(
            subagents=sample_subagents,
            llm_client=mock_llm_client,
            config=config,
        )
        result = await router.match_async(
            "Can you look up the performance benchmarks?",
            conversation_context="user: Find info about React performance",
        )
        assert result.subagent is not None
        assert result.subagent.name == "researcher"


# ============================================================================
# Test SubAgentOrchestrator.match_async
# ============================================================================


@pytest.mark.unit
class TestSubAgentOrchestratorAsync:
    async def test_match_async_with_hybrid_router(self, sample_subagents, mock_llm_client):
        """match_async should use HybridRouter's match_async when available."""
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_subagent",
                        "arguments": json.dumps({
                            "subagent_name": "coder",
                            "confidence": 0.9,
                            "reasoning": "Coding task",
                        }),
                    }
                }
            ],
        }

        config = HybridRouterConfig(keyword_skip_threshold=0.99)
        router = HybridRouter(
            subagents=sample_subagents,
            llm_client=mock_llm_client,
            config=config,
        )
        orchestrator = SubAgentOrchestrator(
            router=router,
            config=SubAgentOrchestratorConfig(default_confidence_threshold=0.5),
        )
        result = await orchestrator.match_async("Build a REST API")
        assert result.matched is True
        assert result.subagent.name == "coder"

    async def test_match_async_fallback_to_sync(self, sample_subagents):
        """match_async with plain SubAgentRouter should use sync match()."""
        from src.infrastructure.agent.core.subagent_router import SubAgentRouter

        router = SubAgentRouter(subagents=sample_subagents)
        orchestrator = SubAgentOrchestrator(
            router=router,
            config=SubAgentOrchestratorConfig(default_confidence_threshold=0.3),
        )
        result = await orchestrator.match_async("code fix debug")
        assert result.matched is True

    async def test_match_async_no_router(self):
        """match_async without router returns no match."""
        orchestrator = SubAgentOrchestrator(router=None)
        result = await orchestrator.match_async("anything")
        assert result.matched is False
        assert "No router" in result.match_reason
