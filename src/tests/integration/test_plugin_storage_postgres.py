"""Postgres round-trip for plugin storage and the review queue.

The test skips unless PLUGIN_STORAGE_POSTGRES_URL is set. CI provides that URL
from the backend job's Postgres service. Local runs use it when Docker is up.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from src.infrastructure.plugins.v2.marketplace_governance_v2 import SqlMarketplaceReviewQueueV2
from src.infrastructure.plugins.v2.plugin_namespace_store_v2 import (
    NamespaceKeyV2,
    NamespaceRecordV2,
    SqlPluginNamespaceStoreV2,
)

pytestmark = pytest.mark.integration


def _migration(name: str):
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_postgres_storage_and_review_survive_a_new_session() -> None:
    url = os.environ.get("PLUGIN_STORAGE_POSTGRES_URL")
    if not url:
        pytest.skip("PLUGIN_STORAGE_POSTGRES_URL is not set")
    engine = create_engine(url)
    namespace = _migration("p8b1c2d3e4f5_add_plugin_namespace_kv_v2.py")
    review = _migration("f2a3b4c5d6e8_add_plugin_review_requests_v2.py")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            if "platform_plugin_namespace_kv_v2" not in inspect(connection).get_table_names():
                namespace.upgrade()
            if "platform_plugin_review_requests_v2" not in inspect(connection).get_table_names():
                review.upgrade()
    with Session(engine) as first:
        store = SqlPluginNamespaceStoreV2(first)
        store.put(
            NamespaceKeyV2(
                plugin_id="sample.notes",
                tenant_id="tenant-a",
                project_id="project-a",
                item_key="note",
            ),
            NamespaceRecordV2(schema_version=1, document={"text": "postgres"}),
        )
        submitted = SqlMarketplaceReviewQueueV2(first).submit(
            plugin_id="sample.notes",
            version="1.2.0",
            digest="sha256:abc",
            note="postgres",
        )
        first.commit()
        review_id = submitted.review_id
    with Session(engine) as second:
        found = SqlPluginNamespaceStoreV2(second).get(
            NamespaceKeyV2(
                plugin_id="sample.notes",
                tenant_id="tenant-a",
                project_id="project-a",
                item_key="note",
            )
        )
        assert found is not None and found.document == {"text": "postgres"}
        assert SqlMarketplaceReviewQueueV2(second).list()[0].review_id == review_id
        second.execute(
            text(
                "DELETE FROM platform_plugin_namespace_kv_v2 WHERE plugin_id = 'sample.notes'"
            )
        )
        second.execute(
            text("DELETE FROM platform_plugin_review_requests_v2 WHERE review_id = :review_id"),
            {"review_id": review_id},
        )
        second.commit()
