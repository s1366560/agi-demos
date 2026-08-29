from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, status

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import Conversation

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _conversation_v2_runtime(test_app: FastAPI) -> AsyncIterator[None]:
    """Exercise deletion through the production generation route and CRUD Provider."""
    await initialize_plugin_runtime_v2(test_app)
    assert "agent" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


async def test_delete_conversation_commits_before_returning_no_content(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    conversation = Conversation(
        id="conversation-delete-commit",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Delete me",
        status="active",
    )
    test_db.add(conversation)
    await test_db.commit()
    conversation_id = conversation.id

    response = await authenticated_async_client.delete(
        f"/api/v1/agent/conversations/{conversation_id}",
        params={"project_id": test_project_db.id},
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    test_db.expire_all()
    assert await test_db.get(Conversation, conversation_id) is None


async def test_get_and_title_update_use_generation_owned_conversation_crud(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    conversation = Conversation(
        id="conversation-v2-title",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Before",
        status="active",
    )
    test_db.add(conversation)
    await test_db.commit()
    conversation_id = conversation.id

    get_response = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation_id}",
        params={"project_id": test_project_db.id},
    )
    update_response = await authenticated_async_client.patch(
        f"/api/v1/agent/conversations/{conversation_id}/title",
        params={"project_id": test_project_db.id},
        json={"title": "After"},
    )

    assert get_response.status_code == status.HTTP_200_OK
    assert get_response.json()["id"] == conversation_id
    assert update_response.status_code == status.HTTP_200_OK
    assert update_response.json()["title"] == "After"
    test_db.expire_all()
    persisted = await test_db.get(Conversation, conversation_id)
    assert persisted is not None
    assert persisted.title == "After"
