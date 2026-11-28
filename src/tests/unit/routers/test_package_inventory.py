"""Tenant package operations preserve the cloud inventory scope and credential boundary."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from plugins.business.environments.backend.inventory_operations import (
    InventoryQuery,
    project_inventory_row,
)
from src.application.schemas.cluster_schemas import ClusterResponse
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


@pytest.mark.unit
def test_projected_cluster_excludes_operator_credentials_and_enforces_tenant():
    cluster = ClusterResponse(
        id="cluster",
        name="Development",
        tenant_id="tenant",
        proxy_endpoint="https://example.invalid",
        provider_config={"region": "test"},
        credentials_encrypted="fixture-only",
        created_at=datetime.now(UTC),
    )
    assert set(project_inventory_row(cluster, "tenant")) == {
        "id",
        "name",
        "status",
        "compute_provider",
        "proxy_endpoint",
        "created_at",
    }
    with pytest.raises(OptionalBusinessError, match="another tenant"):
        project_inventory_row(cluster, "another")


@pytest.mark.unit
@pytest.mark.parametrize("extra", [{"tenant_id": "another"}, {"project_id": "other"}])
def test_inventory_scope_is_owned_by_the_runtime(extra):
    with pytest.raises(ValidationError):
        InventoryQuery.model_validate({"kind": "clusters", **extra})
