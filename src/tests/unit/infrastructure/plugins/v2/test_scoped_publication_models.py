"""Database constraints for exact-scope publication ownership."""

import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, create_engine, insert, select
from sqlalchemy.exc import IntegrityError

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2PublicationModel,
    PlatformPluginV2ScopeHeadModel,
)
from src.infrastructure.adapters.secondary.persistence.plugin_scope_columns_v2 import (
    ROOT_SCOPE_KEY_V2,
)
from src.infrastructure.plugins.v2.scope import scope_key_v2

pytestmark = pytest.mark.unit


def test_head_defaults_and_hierarchy_are_enforced_by_database():
    engine = create_engine("sqlite://")
    table = PlatformPluginV2ScopeHeadModel.__table__
    table.create(engine)
    try:
        with engine.begin() as connection:
            connection.execute(insert(table).values())
            row = connection.execute(select(table)).mappings().one()
            assert row["scope_key"] == scope_key_v2(ScopeV2(kind=ScopeKindV2.ROOT))
            assert row["scope_kind"] == "root"
            assert row["version_high_watermark"] == 0
            assert (row["tenant_id"], row["project_id"], row["session_id"]) == (None,) * 3
        for invalid in (
            {"scope_kind": "root", "tenant_id": "a"},
            {"scope_kind": "tenant"},
            {"scope_kind": "project", "tenant_id": "a"},
            {"scope_kind": "session", "tenant_id": "a", "project_id": "p"},
            {"scope_kind": "tenant", "tenant_id": " "},
            {"scope_kind": "unknown"},
            {"version_high_watermark": -1},
        ):
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(insert(table).values(scope_key="a" * 64, **invalid))
    finally:
        engine.dispose()


def test_ledger_scope_defaults_and_reference_constraints_preserve_retry_identity():
    tables = [
        model.__table__
        for model in (
            PlatformPluginV2PublicationModel,
            PlatformPluginV2ApplyStateModel,
            PlatformPluginV2ApplyStateEventModel,
        )
    ]
    for table in tables:
        assert table.c.scope_key.default.arg == ROOT_SCOPE_KEY_V2
        assert table.c.scope_kind.default.arg == "root"
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                assert next(iter(constraint.column_keys)) == "scope_key"
                assert next(item.target_fullname for item in constraint.elements) == (
                    "platform_plugin_v2_publications.scope_key"
                )
        assert not any(
            isinstance(constraint, UniqueConstraint) and "requested_version" in constraint.columns
            for constraint in table.constraints
        )
    publication_unique = {
        tuple(constraint.columns.keys())
        for constraint in tables[0].constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("nonce",) in publication_unique
    assert ("scope_key", "id") in publication_unique
    apply_unique = {
        tuple(constraint.columns.keys())
        for constraint in tables[1].constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert apply_unique == {("scope_key", "data_plane_id")}
