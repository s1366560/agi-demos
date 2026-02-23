#!/usr/bin/env python3
"""Test HITL database access."""

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
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)


async def test():
    """Test HITL database access."""
    request_id = "clar_10298c05"

    print(f"Testing HITL request lookup: {request_id}")

    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)
        hitl_request = await repo.get_by_id(request_id)

        if hitl_request:
            print("✓ Found HITL request:")
            print(f"  ID: {hitl_request.id}")
            print(f"  Type: {hitl_request.request_type}")
            print(f"  Status: {hitl_request.status}")
            print(f"  Tenant: {hitl_request.tenant_id}")
            print(f"  Project: {hitl_request.project_id}")
            print(f"  Conversation: {hitl_request.conversation_id}")
        else:
            print(f"✗ HITL request {request_id} not found")

            # Try raw SQL
            from sqlalchemy import text
            result = await session.execute(
                text("SELECT id, request_type, status FROM hitl_requests WHERE id = :id"),
                {"id": request_id}
            )
            row = result.fetchone()
            if row:
                print(f"  But raw SQL found: {row}")
            else:
                print("  Raw SQL also didn't find it")


if __name__ == "__main__":
    asyncio.run(test())
