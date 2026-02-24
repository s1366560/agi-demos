#!/usr/bin/env python3
"""Test script for Agent Chat functionality."""

import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

# Set required env vars
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "memstack")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "your_password_here")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "your_password_here")
os.environ.setdefault("LLM_PROVIDER", "dashscope")
os.environ.setdefault("RAY_ADDRESS", "ray://localhost:10001")

from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory


async def test_chat():
    """Test the chat functionality."""
    print("=" * 60)
    print("Testing Agent Chat Flow")
    print("=" * 60)

    # Test Ray connection
    print("\n1. Testing Ray connection...")
    try:
        import ray

        ray.init(address="ray://localhost:10001", namespace="memstack", ignore_reinit_error=True)
        print(f"   ✓ Ray connected: {ray.is_initialized()}")
        print(f"   ✓ Cluster resources: {ray.cluster_resources()}")
        ray.shutdown()
    except Exception as e:
        print(f"   ✗ Ray connection failed: {e}")
        return

    # Test database connection
    print("\n2. Testing database connection...")
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlConversationRepository,
        )

        async with async_session_factory() as db:
            repo = SqlConversationRepository(db)
            conversation = await repo.find_by_id("822fed4e-b7f9-447d-9bbf-b1600d685e49")
            if conversation:
                print(f"   ✓ Found conversation: {conversation.id}")
                print(f"   ✓ Project ID: {conversation.project_id}")
                print(f"   ✓ User ID: {conversation.user_id}")
            else:
                print("   ✗ Conversation not found")
                return
    except Exception as e:
        print(f"   ✗ Database error: {e}")
        import traceback

        traceback.print_exc()
        return

    # Test Agent Service
    print("\n3. Testing Agent Service...")
    try:
        from src.application.services.agent_service import AgentService
        from src.configuration.factories import create_llm_client, create_native_graph_adapter
        from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
            SqlAgentExecutionRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlConversationRepository,
        )

        async with async_session_factory() as db:
            # Create minimal container dependencies
            graph_service = await create_native_graph_adapter()
            conversation_repo = SqlConversationRepository(db)
            execution_repo = SqlAgentExecutionRepository(db)

            _settings = get_settings()
            llm = await create_llm_client("d06da862-1bb1-44fe-93a0-153f58578e07")  # tenant_id

            import redis.asyncio as aioredis

            from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
                SqlAgentExecutionEventRepository,
            )

            event_repo = SqlAgentExecutionEventRepository(db)

            # Create Redis client for event bus
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            redis_client = aioredis.from_url(redis_url)

            agent_service = AgentService(
                conversation_repository=conversation_repo,
                execution_repository=execution_repo,
                graph_service=graph_service,
                llm=llm,
                neo4j_client=graph_service.client,
                agent_execution_event_repository=event_repo,
                redis_client=redis_client,
            )

            print("   ✓ AgentService created")

            # Test stream_chat_v2
            print("\n4. Testing stream_chat_v2...")
            print("   Sending test message...")

            events = []
            async for event in agent_service.stream_chat_v2(
                conversation_id="822fed4e-b7f9-447d-9bbf-b1600d685e49",
                user_message="Hello, what can you do?",
                project_id="a0b13a4d-a0dd-418d-81dd-af48c722773e",
                user_id="b3e0d371-c11c-4a37-9c12-cf351675a630",
                tenant_id="d06da862-1bb1-44fe-93a0-153f58578e07",
            ):
                events.append(event)
                event_type = event.get("type", "unknown")
                print(f"   Event: {event_type}")
                if event_type == "error":
                    print(f"   Error data: {event.get('data', {})}")
                if len(events) > 20:
                    print("   (More events...)")
                    break

            print(f"\n   ✓ Received {len(events)} events")

    except Exception as e:
        print(f"   ✗ Agent Service error: {e}")
        import traceback

        traceback.print_exc()
        return

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_chat())
