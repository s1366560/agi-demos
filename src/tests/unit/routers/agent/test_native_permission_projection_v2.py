"""Native consent survives actual SQL hydration without becoming generic tool consent."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.conversation_session_projection_service import (
    ConversationSessionProjectionService,
)
from src.domain.model.agent.hitl.hitl_types import HITLType
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.adapters.secondary.persistence.sql_conversation_session_projection_reader import (
    SqlConversationSessionProjectionReader,
)
from src.infrastructure.agent.hitl import coordinator
from src.infrastructure.agent.hitl.hitl_strategies import PermissionStrategy
from src.tests.unit.infrastructure.agent.test_native_permission import decision

pytestmark = pytest.mark.unit


@pytest.fixture
async def native_projection_case(test_db, test_engine, test_user, test_project_db, monkeypatch):
    conversation = Conversation(
        id="native-permission-conversation",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Native permission fixture",
        current_mode="build",
    )
    test_db.add(conversation)
    await test_db.commit()
    monkeypatch.setattr(
        coordinator,
        "async_session_factory",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )
    metadata = {
        "tool_name": "computer_list_windows",
        "action": "observe_application",
        "description": "Observe the fixture application",
        "risk_level": "low",
        "allow_remember": True,
        "decision": decision(),
        "native_binding": {
            "user_id": test_user.id,
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
            "conversation_id": conversation.id,
            "run_id": "run",
            "session_id": "engine-session",
            "device_id": "device",
            "app": "ai.memstack.cua.fixture",
            "identity_digest": "fixture-identity",
            "capability": "observation",
            "tool_name": "computer_list_windows",
            "input_digest": "exact-input",
            "cloud_request_id": "cloud-request",
            "native_request_id": "native-pending",
            "native_session_id": "native-session",
            "authorization_revision": 7,
        },
        "scopes": ["once", "session", "always"],
        "actions": [{"id": "allow", "label": "Allow"}, {"id": "deny", "label": "Deny"}],
    }

    async def project(value):
        request = PermissionStrategy().create_request(
            conversation_id=conversation.id,
            request_data=value,
        )
        await coordinator._persist_hitl_request(
            request_id=request.request_id,
            hitl_type=HITLType.PERMISSION,
            conversation_id=conversation.id,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            message_id=None,
            timeout_seconds=60,
            type_data={**request.type_specific_data, "irrelevant_private_field": "do-not-project"},
            created_at=datetime.now(UTC),
        )
        reader = SqlConversationSessionProjectionReader(test_db, workspace_authority=None)
        return await reader._load_pending_hitl(
            conversation=SimpleNamespace(
                id=conversation.id,
                tenant_id=test_project_db.tenant_id,
                project_id=test_project_db.id,
            ),
            user_id=test_user.id,
            now=datetime.now(UTC),
        )

    return metadata, project


async def test_native_consent_decision_binding_and_scopes_survive_sql_hydration(
    native_projection_case,
):
    metadata, project = native_projection_case
    expected = deepcopy(metadata)
    metadata["native_binding"]["irrelevant_private_field"] = "do-not-project"
    pending, blocked = await project(metadata)
    assert blocked and len(pending) == 1
    payload = ConversationSessionProjectionService._hitl(pending[0]).model_dump(mode="json")
    assert payload["decision"] == expected["decision"]
    assert payload["native_binding"] == expected["native_binding"]
    assert payload["scopes"] == ["once", "session", "always"]
    assert payload["actions"] == expected["actions"]
    assert payload["authority_revision"] == 1
    assert payload["permission"]["tool_name"] == "computer_list_windows"
    assert "do-not-project" not in str(payload)


@pytest.mark.parametrize("field", ["user_id", "tenant_id", "project_id", "conversation_id"])
async def test_foreign_native_binding_remains_blocking_without_generic_fallback(
    native_projection_case, field
):
    metadata, project = native_projection_case
    metadata["native_binding"][field] = "foreign"
    pending, blocked = await project(metadata)
    assert blocked and pending == ()


@pytest.mark.parametrize(
    "path,value",
    [
        (("decision", "target", "id"), "different-pending"),
        (("decision", "risk", "level"), "unknown"),
        (("decision", "extra"), "untrusted"),
        (("native_binding",), None),
        (("native_binding", "tool_name"), "write"),
        (("native_binding", "authorization_revision"), True),
        (("native_binding", "authorization_revision"), 0),
        (("scopes",), ["workspace_tool"]),
        (("actions",), [{"id": "allow", "label": "Allow"}]),
    ],
)
async def test_malformed_native_consent_does_not_become_approvable_generic_permission(
    native_projection_case, path, value
):
    metadata, project = native_projection_case
    target = metadata
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    pending, blocked = await project(metadata)
    assert blocked and pending == ()
