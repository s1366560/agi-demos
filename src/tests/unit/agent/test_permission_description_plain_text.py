"""Static tool descriptions remain text through HITL persistence and projection."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.model.agent.hitl.hitl_types import HITLType
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.adapters.secondary.persistence.sql_conversation_session_projection_reader import (
    SqlConversationSessionProjectionReader,
)
from src.infrastructure.agent.hitl import coordinator
from src.infrastructure.agent.hitl.hitl_strategies import PermissionStrategy


@pytest.mark.unit
@pytest.mark.parametrize(
    "description",
    [
        "Write content if it doesn't exist; mode='append'.",
        "Keep literal &amp; and <img src=x onerror=alert(1)> as text.",
    ],
)
async def test_permission_description_persists_and_projects_without_html_encoding(
    test_db,
    test_engine,
    test_user,
    test_project_db,
    monkeypatch,
    description,
):
    conversation = Conversation(
        id="plain-permission-conversation",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Plain description",
        current_mode="build",
    )
    test_db.add(conversation)
    await test_db.commit()
    request = PermissionStrategy().create_request(
        conversation_id=conversation.id,
        request_data={
            "tool_name": "write",
            "action": "execute",
            "description": description,
            "risk_level": "medium",
            "allow_remember": False,
        },
    )
    monkeypatch.setattr(
        coordinator,
        "async_session_factory",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )
    await coordinator._persist_hitl_request(
        request_id=request.request_id,
        hitl_type=HITLType.PERMISSION,
        conversation_id=conversation.id,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        message_id=None,
        timeout_seconds=60,
        type_data=request.type_specific_data,
        created_at=datetime.now(UTC),
    )
    reader = SqlConversationSessionProjectionReader(test_db, workspace_authority=None)
    pending, blocked = await reader._load_pending_hitl(
        conversation=SimpleNamespace(
            id=conversation.id, tenant_id=test_project_db.tenant_id, project_id=test_project_db.id
        ),
        user_id=test_user.id,
        now=datetime.now(UTC),
    )
    assert blocked and len(pending) == 1
    assert pending[0].question == description
    assert pending[0].permission.description == description


def test_permission_history_preserves_declared_text_without_decoding_old_entities():
    from src.infrastructure.adapters.primary.web.routers.agent.permission_history_projection import (
        permission_history_item,
    )

    description = "Don't decode &lt;b&gt; or encode <img>"
    result = permission_history_item(
        {"request_id": "request"},
        {},
        {
            "request": {
                "status": "completed",
                "response": "deny",
                "permission_metadata": {
                    "tool_name": "write",
                    "action": "execute",
                    "description": description,
                },
            }
        },
    )
    assert result["description"] == description
    assert result["answered"] is True
    assert result["granted"] is False
