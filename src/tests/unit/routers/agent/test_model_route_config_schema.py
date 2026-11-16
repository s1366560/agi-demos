"""Conversation model selection preserves explicit provider identity at HTTP ingress."""

import pytest
from pydantic import ValidationError

from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    CreateConversationRequest,
    UpdateConversationConfigRequest,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("schema", [CreateConversationRequest, UpdateConversationConfigRequest])
def test_model_route_schema_accepts_exact_identity_and_clear(schema):
    def parse(selection):
        return schema.model_validate(
            {"project_id": "p", "agent_config": selection}
            if schema is CreateConversationRequest
            else selection
        )

    selection = {
        "llm_model_override": " shared ",
        "llm_route_override": {"provider_id": " provider-a ", "model_id": " shared "},
    }
    parsed = parse(selection)
    route = (
        parsed.agent_config["llm_route_override"]
        if schema is CreateConversationRequest
        else parsed.llm_route_override.model_dump()
    )
    assert route == {"provider_id": "provider-a", "model_id": "shared"}
    parse({"llm_model_override": None, "llm_route_override": None})
    for bad in (
        {"provider_id": "", "model_id": "shared"},
        {"provider_id": "p", "model_id": "wrong"},
        {"provider_id": "p", "model_id": "shared", "extra": "no"},
    ):
        with pytest.raises(ValidationError):
            parse({**selection, "llm_route_override": bad})
