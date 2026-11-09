"""Catalog projection, update hints, review decisions, and rejected executors."""

import pytest
from memstack_plugin_sdk.contract import ContractError, parse_contribution

from src.infrastructure.plugins.v2.marketplace_governance_v2 import (
    CatalogProjectionRowV2,
    MarketplaceReviewQueueV2,
    project_catalog_v2,
    projection_row_from_package_v2,
    update_available_v2,
)


def test_projection_filters_revoked_rows_and_permissions() -> None:
    rows = (
        CatalogProjectionRowV2(
            plugin_id="sample.notes", version="1.0.0", permissions=("tools.execute",), revoked=False
        ),
        CatalogProjectionRowV2(
            plugin_id="sample.secret", version="1.0.0", permissions=("storage.write",), revoked=True
        ),
    )
    assert [row.plugin_id for row in project_catalog_v2(rows, query="notes")] == ["sample.notes"]
    assert project_catalog_v2(rows, permission="storage.write") == ()


def test_update_hint_and_review_decision() -> None:
    rows = (
        CatalogProjectionRowV2(
            plugin_id="sample.notes", version="1.2.0", permissions=("tools.execute",), revoked=False
        ),
    )
    hints = update_available_v2({"sample.notes": "1.0.0"}, rows)
    assert hints[0]["available_version"] == "1.2.0"
    queue = MarketplaceReviewQueueV2()
    submitted = queue.submit(plugin_id="sample.notes", version="1.2.0", digest="sha256:abc", note="")
    assert submitted.status == "pending"
    assert queue.decide(submitted.review_id, "approved").status == "approved"


def test_projection_reads_permissions_from_a_package_row() -> None:
    row = projection_row_from_package_v2(
        type(
            "Package",
            (),
            {
                "plugin_id": "sample.notes",
                "version": "1.0.0",
                "revoked": False,
                "manifest": {"manifests": [{"permissions": ["tools.execute"]}]},
            },
        )()
    )
    assert row.permissions == ("tools.execute",)


def test_unimplemented_executors_fail_closed() -> None:
    with pytest.raises(ContractError, match="unimplemented"):
        parse_contribution(
            {
                "schema": "memstack.plugin.contributions/1",
                "channels": [{"type": "slack"}],
            }
        )
