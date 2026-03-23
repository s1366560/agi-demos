"""Tests for AgentContainer multi-agent DI factory methods."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestAgentContainerMultiAgentFactories:
    """Test suite for the 9 new AgentContainer factory methods plus default_context_engine."""

    # ------------------------------------------------------------------
    # 1. No-dep singletons
    # ------------------------------------------------------------------

    # --- span_service ---

    async def test_span_service_returns_correct_type(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer
        from src.infrastructure.agent.subagent.span_service import SubAgentSpanService

        container = AgentContainer()
        result = container.span_service()
        assert isinstance(result, SubAgentSpanService)

    async def test_span_service_is_cached_singleton(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer()
        result1 = container.span_service()
        result2 = container.span_service()
        assert result1 is result2

    # --- fork_merge_service ---

    async def test_fork_merge_service_returns_correct_type(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer
        from src.infrastructure.agent.subagent.session_fork_merge_service import (
            SessionForkMergeService,
        )

        container = AgentContainer()
        result = container.fork_merge_service()
        assert isinstance(result, SessionForkMergeService)

    async def test_fork_merge_service_is_cached_singleton(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer()
        result1 = container.fork_merge_service()
        result2 = container.fork_merge_service()
        assert result1 is result2

    # --- layered_tool_policy_service ---

    async def test_layered_tool_policy_service_returns_correct_type(self) -> None:
        from src.application.services.layered_tool_policy_service import (
            LayeredToolPolicyService,
        )
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer()
        result = container.layered_tool_policy_service()
        assert isinstance(result, LayeredToolPolicyService)

    async def test_layered_tool_policy_service_is_cached_singleton(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer()
        result1 = container.layered_tool_policy_service()
        result2 = container.layered_tool_policy_service()
        assert result1 is result2

    # ------------------------------------------------------------------
    # 2. Redis-dep singletons
    # ------------------------------------------------------------------

    # --- redis_agent_namespace ---

    async def test_redis_agent_namespace_returns_correct_type(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer
        from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
            RedisAgentNamespaceAdapter,
        )

        container = AgentContainer(redis_client=MagicMock())
        result = container.redis_agent_namespace()
        assert isinstance(result, RedisAgentNamespaceAdapter)

    async def test_redis_agent_namespace_is_cached_singleton(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer(redis_client=MagicMock())
        result1 = container.redis_agent_namespace()
        result2 = container.redis_agent_namespace()
        assert result1 is result2

    async def test_redis_agent_namespace_raises_without_redis(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer()
        with pytest.raises(AssertionError):
            container.redis_agent_namespace()

    # --- redis_agent_credential_scope ---

    async def test_redis_agent_credential_scope_returns_correct_type(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer
        from src.infrastructure.adapters.secondary.cache.redis_agent_credential_scope import (
            RedisAgentCredentialScopeAdapter,
        )

        mock_settings = MagicMock()
        mock_settings.llm_encryption_key = "test-encryption-key-32chars-min!!"
        container = AgentContainer(redis_client=MagicMock(), settings=mock_settings)
        result = container.redis_agent_credential_scope()
        assert isinstance(result, RedisAgentCredentialScopeAdapter)

    async def test_redis_agent_credential_scope_is_cached_singleton(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        mock_settings = MagicMock()
        mock_settings.llm_encryption_key = "test-encryption-key-32chars-min!!"
        container = AgentContainer(redis_client=MagicMock(), settings=mock_settings)
        result1 = container.redis_agent_credential_scope()
        result2 = container.redis_agent_credential_scope()
        assert result1 is result2

    async def test_redis_agent_credential_scope_raises_without_redis(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer()
        with pytest.raises(AssertionError):
            container.redis_agent_credential_scope()

    # ------------------------------------------------------------------
    # 3. DB-dep factories
    # ------------------------------------------------------------------

    # --- message_binding_repository ---

    async def test_message_binding_repository_returns_correct_type(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer
        from src.infrastructure.adapters.secondary.persistence.sql_message_binding_repository import (
            SqlMessageBindingRepository,
        )

        container = AgentContainer(db=MagicMock())
        result = container.message_binding_repository()
        assert isinstance(result, SqlMessageBindingRepository)

    async def test_message_binding_repository_raises_without_db(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer()
        with pytest.raises(AssertionError):
            container.message_binding_repository()

    # --- default_message_router ---

    async def test_default_message_router_returns_correct_type(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer
        from src.infrastructure.agent.routing.default_message_router import (
            DefaultMessageRouter,
        )

        container = AgentContainer(db=MagicMock())
        result = container.default_message_router()
        assert isinstance(result, DefaultMessageRouter)

    async def test_default_message_router_raises_without_db(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer()
        with pytest.raises(AssertionError):
            container.default_message_router()

    # --- agent_router_service ---

    async def test_agent_router_service_returns_correct_type(self) -> None:
        from src.application.services.agent_router_service import AgentRouterService
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer(db=MagicMock())
        result = container.agent_router_service()
        assert isinstance(result, AgentRouterService)

    async def test_agent_router_service_raises_without_db(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer()
        with pytest.raises(AssertionError):
            container.agent_router_service()

    # ------------------------------------------------------------------
    # 4. Context engine
    # ------------------------------------------------------------------

    async def test_default_context_engine_returns_correct_type(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer
        from src.infrastructure.agent.context.default_context_engine import (
            DefaultContextEngine,
        )

        container = AgentContainer()
        result = container.default_context_engine()
        assert isinstance(result, DefaultContextEngine)
