"""Deployment policy tests for protocol-v2 publication readiness."""

from __future__ import annotations

import pytest

from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)


@pytest.mark.unit
def test_development_publication_policy_defaults_to_local_python_plane() -> None:
    policy = PlatformPluginPublicationPolicyV2.from_deployment(
        environment="development",
        required_data_plane_ids="",
        ack_deadline_seconds=30,
    )

    assert policy.required_data_plane_ids == (PYTHON_API_DATA_PLANE_ID_V2,)
    assert policy.ack_deadline_seconds == 30


@pytest.mark.unit
def test_production_publication_policy_requires_explicit_finite_roster() -> None:
    with pytest.raises(ValueError, match="explicit required data-plane roster"):
        PlatformPluginPublicationPolicyV2.from_deployment(
            environment="production",
            required_data_plane_ids="",
            ack_deadline_seconds=30,
        )


@pytest.mark.unit
def test_publication_policy_normalizes_and_deduplicates_declared_roster() -> None:
    policy = PlatformPluginPublicationPolicyV2.from_deployment(
        environment="production",
        required_data_plane_ids=" rust-server,python-api-v2,rust-server ",
        ack_deadline_seconds=45,
    )

    assert policy.required_data_plane_ids == ("rust-server", "python-api-v2")
    assert policy.ack_deadline_seconds == 45


@pytest.mark.unit
@pytest.mark.parametrize("ack_deadline_seconds", [True, 30.0, "30"])
def test_publication_policy_rejects_non_integer_deadlines(
    ack_deadline_seconds: object,
) -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("python-api-v2",),
            ack_deadline_seconds=ack_deadline_seconds,  # type: ignore[arg-type]
        )
