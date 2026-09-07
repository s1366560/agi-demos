"""Legacy admission authority is explicit, scoped, and survives JSON transport."""

from dataclasses import replace

import pytest

from src.domain.model.cron.legacy_admission import LegacyCronAdmissionIdentity

pytestmark = pytest.mark.unit


def identity() -> LegacyCronAdmissionIdentity:
    return LegacyCronAdmissionIdentity(
        admission_id="admission",
        tenant_id="tenant",
        project_id="project",
        job_id="job",
        run_id="run",
        message_id="message",
        conversation_id="conversation",
        owner_epoch=0,
        token="private-admission-token",
    )


def test_admission_identity_round_trips_without_token_in_repr() -> None:
    value = identity()
    assert LegacyCronAdmissionIdentity.from_wire(value.to_wire()) == value
    assert value.token not in repr(value)


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "conversation_id", "message_id"])
def test_admission_identity_rejects_mismatched_request_scope(field: str) -> None:
    scope = {
        "tenant_id": "tenant",
        "project_id": "project",
        "conversation_id": "conversation",
        "message_id": "message",
    }
    scope[field] = "other"
    assert not identity().matches_request(**scope)


def test_admission_identity_rejects_unknown_or_malformed_wire_data() -> None:
    for value in [
        {},
        {**identity().to_wire(), "owner_epoch": True},
        {**identity().to_wire(), "token": ""},
    ]:
        with pytest.raises(ValueError):
            LegacyCronAdmissionIdentity.from_wire(value)
    assert replace(identity(), token="different").token_hash != identity().token_hash
