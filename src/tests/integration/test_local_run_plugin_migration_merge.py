"""Upgrade actual PostgreSQL installations originating on either side of the P4 merge."""

import asyncio
import os

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from src.application.services.local_run_protocol import canonical_payload
from src.infrastructure.adapters.secondary.persistence.database import initialize_database
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    Project,
    Tenant,
    User,
)
from src.tests.integration import test_package_kernel_database as disposable

database = disposable.database
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PACKAGE_KERNEL_DATABASE_TESTS") != "1",
        reason="requires disposable pgvector PostgreSQL images",
    ),
]

PRIVATE_PLUGIN_REVISION = "5f998ffc4874"
PLUGIN_HEAD = "8de32c54a61f"
P4_HEAD = "f4a5b6c7d8e9"
EVENTS = "agent_local_run_events"
INSTALLATIONS = "project_plugin_installations"


def _seed_prior_data(connection):
    # Use the common pre-merge identity and authority tables to create rows with real foreign keys.
    for model, values in (
        (User, {"id": "user", "email": "merge-qa@example.test", "hashed_password": "unused"}),
        (Tenant, {"id": "tenant", "name": "Merge QA", "slug": "merge-qa", "owner_id": "user"}),
        (Project, {"id": "project", "name": "Merge QA", "tenant_id": "tenant", "owner_id": "user"}),
        (
            Conversation,
            {
                "id": "conversation",
                "tenant_id": "tenant",
                "project_id": "project",
                "user_id": "user",
                "title": "Historical run",
            },
        ),
        (
            AgentRunAuthorityModel,
            {
                "id": "run",
                "tenant_id": "tenant",
                "project_id": "project",
                "conversation_id": "conversation",
                "run_kind": "chat",
                "message_id": "msg",
                "request_message": "first",
                "status": "running",
                "permission_profile": "read_only",
                "authorization_snapshot": {},
                "idempotency_key": "first",
            },
        ),
    ):
        connection.execute(model.__table__.insert().values(**values))
    metadata = MetaData()
    tables = set(inspect(connection).get_table_names())
    if EVENTS in tables:
        events = Table(EVENTS, metadata, autoload_with=connection, resolve_fks=False)
        payload, digest = canonical_payload({"status": "recorded"})
        connection.execute(
            events.insert().values(
                id="event",
                run_id="run",
                tenant_id="tenant",
                project_id="project",
                conversation_id="conversation",
                seq=1,
                kind="status",
                payload=payload,
                payload_sha256=digest,
            )
        )
    if INSTALLATIONS in tables:
        # Reflect the old table because 5f998 has no authorization_epoch column.
        installed = Table(INSTALLATIONS, metadata, autoload_with=connection, resolve_fks=False)
        connection.execute(
            installed.insert().values(
                project_id="project",
                plugin_id="qa-signed",
                desired="1.0.0",
                enabled=False,
                revision=7,
                generation=3,
                retention="retained",
            )
        )


def _assert_schema(connection, prior):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    assert {
        EVENTS,
        INSTALLATIONS,
        "device_plugin_grants",
        "agent_run_package_selections",
        "project_plugin_releases",
        "graph_projection_jobs",
    } <= tables
    assert "package_kernel_alembic_version" not in tables
    metadata = MetaData()
    installations = Table(INSTALLATIONS, metadata, autoload_with=connection, resolve_fks=False)
    assert installations.c.authorization_epoch.nullable is False
    assert not Table(
        "graph_projection_jobs", metadata, autoload_with=connection, resolve_fks=False
    ).c.retry_at.nullable
    assert any(
        u["column_names"] == ["run_id", "seq"] for u in inspector.get_unique_constraints(EVENTS)
    )
    assert any(
        fk["constrained_columns"] == ["run_id"]
        and fk["referred_table"] == "agent_run_authorities"
        and fk["options"].get("ondelete") == "CASCADE"
        for fk in inspector.get_foreign_keys(EVENTS)
    )
    assert {"ck_agent_local_run_events_seq_positive", "ck_agent_local_run_events_kind"} <= {
        constraint["name"] for constraint in inspector.get_check_constraints(EVENTS)
    }
    assert any(
        index["column_names"] == ["conversation_id", "seq"]
        for index in inspector.get_indexes(EVENTS)
    )
    if P4_HEAD in prior:
        events = Table(EVENTS, metadata, autoload_with=connection, resolve_fks=False)
        stored = connection.execute(select(events).where(events.c.id == "event")).mappings().one()
        assert (stored["seq"], stored["payload"], stored["payload_sha256"]) == (
            1,
            *canonical_payload({"status": "recorded"}),
        )
        for change, expected_state in (
            ({"id": "duplicate"}, "23505"),
            ({"id": "zero", "seq": 0}, "23514"),
            ({"id": "unknown", "seq": 2, "kind": "unknown"}, "23514"),
        ):
            with pytest.raises(IntegrityError) as rejected, connection.begin_nested():
                connection.execute(events.insert().values({**stored, **change}))
            assert rejected.value.orig.sqlstate == expected_state
    if PRIVATE_PLUGIN_REVISION in prior or PLUGIN_HEAD in prior:
        assert connection.execute(
            select(
                installations.c.revision,
                installations.c.generation,
                installations.c.authorization_epoch,
            ).where(installations.c.plugin_id == "qa-signed")
        ).one() == (7, 3, 0)


@pytest.mark.parametrize("database", ["pgvector/pgvector:pg16"], indirect=True)
@pytest.mark.parametrize(
    "prior",
    [(), (PRIVATE_PLUGIN_REVISION,), (P4_HEAD,), (PLUGIN_HEAD, P4_HEAD)],
    ids=["empty", "existing-plugin", "existing-local-events", "both-heads"],
)
async def test_full_database_preserves_each_prior_branch_and_converges(
    database, monkeypatch, prior
):
    disposable._isolate_cli_settings(monkeypatch)
    cfg = Config("alembic.ini")
    cfg.attributes.update(database_url=database.url, configure_logger=False)
    current = ScriptDirectory.from_config(cfg).get_current_head()
    assert current
    for revision in prior:
        await asyncio.to_thread(command.upgrade, cfg, revision)
    if prior:
        async with database.begin() as connection:
            assert set(
                await connection.scalars(text("SELECT version_num FROM alembic_version"))
            ) == set(prior)
            await connection.run_sync(_seed_prior_data)
    for _ in range(2):
        # Startup must select the full schema and the explicitly supplied engine on each attempt.
        await initialize_database(database)
        async with database.connect() as connection:
            assert list(
                await connection.scalars(text("SELECT version_num FROM alembic_version"))
            ) == [current]
            await connection.run_sync(_assert_schema, prior)
