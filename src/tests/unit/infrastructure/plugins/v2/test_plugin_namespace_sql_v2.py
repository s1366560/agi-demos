"""SQL namespace isolation and the namespace migration's upgrade/downgrade."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from src.infrastructure.adapters.secondary.persistence.platform_plugin_namespace_model_v2 import (
    PlatformPluginNamespaceRecordModelV2,
)
from src.infrastructure.plugins.v2.plugin_namespace_store_v2 import (
    NamespaceKeyV2,
    SqlPluginNamespaceStoreV2,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedOptionalBusinessRuntimeV2,
)
from src.tests.unit.infrastructure.plugins.v2.test_signed_optional_business_v2 import _package


def test_sql_store_isolates_tenants_and_projects() -> None:
    engine = create_engine("sqlite://")
    PlatformPluginNamespaceRecordModelV2.__table__.create(engine)
    with Session(engine) as session:
        store = SqlPluginNamespaceStoreV2(session)
        runtime = SignedOptionalBusinessRuntimeV2(store)
        package = _package()
        runtime.record(package)
        runtime.enable(package.plugin_id)
        first = ScopeBindingV2(tenant_id="tenant-a", project_id="project-a")
        other_project = ScopeBindingV2(tenant_id="tenant-a", project_id="project-b")
        runtime.storage_put(package.plugin_id, first, "note", {"text": "a"})
        session.commit()
        assert runtime.storage_get(package.plugin_id, first, "note") == {"text": "a"}
        assert runtime.storage_get(package.plugin_id, other_project, "note") is None
        runtime.revoke(package.plugin_id)
        try:
            runtime.storage_get(package.plugin_id, first, "note")
        except OptionalBusinessError as exc:
            assert "revoked" in str(exc)
        else:
            raise AssertionError("revoked read was allowed")
        assert store.get(
            NamespaceKeyV2(
                plugin_id=package.plugin_id,
                tenant_id="tenant-a",
                project_id="project-a",
                item_key="note",
            )
        )


def test_namespace_migration_upgrades_and_downgrades_on_sqlite() -> None:
    path = (
        Path(__file__).resolve().parents[6]
        / "alembic/versions/p8b1c2d3e4f5_add_plugin_namespace_kv_v2.py"
    )
    spec = importlib.util.spec_from_file_location("namespace_migration_v2", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        assert "platform_plugin_namespace_kv_v2" in inspect(connection).get_table_names()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "platform_plugin_namespace_kv_v2" not in inspect(connection).get_table_names()
