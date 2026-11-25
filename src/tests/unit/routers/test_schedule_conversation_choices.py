from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from plugins.business.automation.backend.schedule_conversations import (
    require_schedule_conversation,
    schedule_conversations,
)
from src.infrastructure.adapters.secondary.persistence.models import Conversation, Project
from src.tests.unit.routers import test_optional_business_http_v2 as package_api

http = package_api.http
publisher = package_api.publisher
pytestmark = pytest.mark.unit


async def test_schedule_editor_lists_and_binds_only_own_project_conversations(http, db_session):
    db_session.add(Project(id="q", tenant_id="t", name="Other", owner_id="owner"))
    await db_session.flush()
    for key, user, project in (
        ("mine", "owner", "p"),
        ("other", "viewer", "p"),
        ("away", "owner", "q"),
    ):
        db_session.add(
            Conversation(
                id=key, title=key, user_id=user, project_id=project, tenant_id="t", workspace_id="w"
            )
        )
    await db_session.flush()
    ctx = SimpleNamespace(
        db=db_session,
        user=SimpleNamespace(id="owner"),
        scope=SimpleNamespace(project_id="p", tenant_id="t"),
    )
    assert await schedule_conversations(ctx, {}, None) == {
        "items": [{"id": "mine", "title": "mine", "workspaceId": "w"}]
    }
    await require_schedule_conversation(ctx, "mine")
    for key in ("away", "other"):
        with pytest.raises(HTTPException) as failure:
            await require_schedule_conversation(ctx, key)
        assert failure.value.status_code == 403
