"""request_env_var accepts an object context and rejects a string."""

import pytest

from src.infrastructure.agent.tools.env_var_tools import _validate_request_env_inputs

pytestmark = pytest.mark.unit


def _validate(context: object) -> str | None:
    return _validate_request_env_inputs(
        tenant_id="tenant-1",
        project_id="project-1",
        fields=[{"variable_name": "API_TOKEN"}],
        context=context,
        save_to_project=False,
        hitl_handler=object(),
        session_factory=object(),
        repository=None,
        encryption_service=object(),
    )


def test_string_context_is_rejected() -> None:
    assert _validate("please store this") == "Invalid context payload"


def test_object_context_passes_validation() -> None:
    assert _validate({"purpose": "install"}) is None
