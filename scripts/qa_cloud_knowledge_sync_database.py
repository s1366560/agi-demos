"""QA-only PostgreSQL schema lifecycle; never target the application's database."""

from __future__ import annotations

import importlib.util
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast, override
from uuid import uuid4

import sqlalchemy as sa
from alembic.autogenerate import produce_migrations
from alembic.operations import Operations
from alembic.operations.ops import ModifyTableOps
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from scripts.qa_cloud_knowledge_sync_graph import QA_NEO4J_URI
from src.application.services.auth_service_v2 import AuthService
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.models import Base
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAPIKeyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import SqlUserRepository
from src.infrastructure.plugins.v2.protocol import parse_profile_snapshot_v2

ROOT = Path(__file__).resolve().parents[1]
QA_DATABASE = "memstack_qa_sync_20260907"
PROFILE_ID = "memstack-cloud-knowledge-sync-acceptance-v2"
PROFILE_PATH = ROOT / "shared/profiles/memstack-cloud-knowledge-sync-acceptance.v2.json"
DEPENDENCY_TABLES = (
    "users",
    "api_keys",
    "roles",
    "user_roles",
    "permissions",
    "role_permissions",
    "tenants",
    "user_tenants",
    "projects",
    "user_projects",
    "memories",
    "memory_shares",
    "memory_chunks",
    "graph_stores",
    "retrieval_stores",
    "task_logs",
)
REVISIONS = (
    "a931fc278146_add_durable_knowledge_sync_foundation.py",
    "b353e93ff302_fence_enrolled_knowledge_writes_and_.py",
)


@dataclass(frozen=True)
class QaCloudDatabase:
    database: str
    schema: str
    profile_id: str
    profile_digest: str
    created_at: str
    neo4j_uri: str

    def validate(self) -> None:
        if self.neo4j_uri != QA_NEO4J_URI:
            raise ValueError("QA metadata requires the isolated Neo4j address")
        if self.database != QA_DATABASE or self.profile_id != PROFILE_ID:
            raise ValueError("QA database/profile identity is invalid")
        if re.fullmatch(r"qa_cloud_sync_[0-9a-f]{32}", self.schema) is None:
            raise ValueError("QA schema must have its generated, isolated name")
        if re.fullmatch(r"[0-9a-f]{64}", self.profile_digest) is None:
            raise ValueError("QA profile digest is invalid")
        if datetime.fromisoformat(self.created_at).tzinfo is None:
            raise ValueError("QA creation time must include its timezone")

    def save(self, path: Path) -> None:
        self.validate()
        # Metadata contains no user password, bearer token or connection URL.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(asdict(self), stream, indent=2)
            _ = stream.write("\n")

    @classmethod
    def load(cls, path: Path) -> QaCloudDatabase:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("QA metadata must be an object")
        fields = cast("dict[str, object]", value)
        if set(fields) != set(cls.__dataclass_fields__):
            raise ValueError("QA metadata fields are invalid")
        if any(not isinstance(item, str) for item in fields.values()):
            raise ValueError("QA metadata values must be strings")
        result = cls(**cast("dict[str, str]", fields))
        result.validate()
        return result


def qa_engine(state: QaCloudDatabase) -> AsyncEngine:
    state.validate()
    # Reuse only the configured host/login; database identity is fixed here.
    url = sa.engine.make_url(get_settings().postgres_url).set(database=QA_DATABASE)
    return create_async_engine(
        url,
        poolclass=sa.pool.NullPool,
        connect_args={"server_settings": {"search_path": state.schema}},
    )


class _PublicVector(sa.types.UserDefinedType[Any]):
    cache_ok = True

    @override
    def get_col_spec(self, **_kwargs: object) -> str:
        return "public.vector"


def _bootstrap_schema(connection: sa.Connection) -> None:
    schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    connection.dialect.default_schema_name = schema
    metadata = sa.MetaData()
    for name in DEPENDENCY_TABLES:
        _ = Base.metadata.tables[name].to_metadata(metadata)
    metadata.tables["memory_chunks"].c.embedding.type = _PublicVector()
    context = MigrationContext.configure(connection)
    generated = produce_migrations(context, metadata)
    if generated.upgrade_ops is None:
        raise RuntimeError("Alembic did not produce the QA dependency bootstrap")
    operations = Operations(context)
    # The extension is a pre-existing QA-database prerequisite, not a fallback schema.
    if not connection.execute(
        sa.text(
            "SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public' AND t.typname='vector'"
        )
    ).scalar():
        raise RuntimeError("The dedicated QA database requires its existing public.vector type")
    for operation in generated.upgrade_ops.ops:
        if isinstance(operation, ModifyTableOps):
            for child in operation.ops:
                operations.invoke(child)
        else:
            operations.invoke(operation)
    with Operations.context(context):
        for filename in REVISIONS:
            path = ROOT / "alembic/versions" / filename
            spec = importlib.util.spec_from_file_location("qa_cloud_sync_migration", path)
            if spec is None or spec.loader is None:
                raise RuntimeError("Knowledge migration cannot be loaded")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade()


async def initialize_qa_database(
    metadata_path: Path, *, email: str, password: str, neo4j_uri: str
) -> QaCloudDatabase:
    if metadata_path.exists() or not email or not password:
        raise ValueError("A new metadata path and nonempty QA credentials are required")
    snapshot = parse_profile_snapshot_v2(json.loads(PROFILE_PATH.read_text()))
    if snapshot.profile_id != PROFILE_ID or snapshot.generation != 1:
        raise ValueError("The compiled Cloud QA profile template is invalid")
    state = QaCloudDatabase(
        database=QA_DATABASE,
        schema="qa_cloud_sync_" + uuid4().hex,
        profile_id=snapshot.profile_id,
        profile_digest=snapshot.digest,
        created_at=datetime.now(UTC).isoformat(),
        neo4j_uri=neo4j_uri,
    )
    engine = qa_engine(state)
    created = False
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Operations(MigrationContext.configure(sync)).execute(
                    sa.schema.CreateSchema(state.schema)
                )
            )
            await connection.run_sync(_bootstrap_schema)
        created = True
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with sessions() as db:
            service = AuthService(SqlUserRepository(db), SqlAPIKeyRepository(db))
            _ = await service.create_user(email, "Cloud synchronization QA", password)
            await db.commit()
        state.save(metadata_path)
    except BaseException:
        # Only the freshly allocated schema is owned by this failed initialization.
        if created:
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync: Operations(MigrationContext.configure(sync)).execute(
                        sa.schema.DropSchema(state.schema, cascade=True, if_exists=True)
                    )
                )
        raise
    finally:
        await engine.dispose()
    return state


async def cleanup_qa_database(metadata_path: Path, *, confirm_schema: str) -> None:
    state = QaCloudDatabase.load(metadata_path)
    if confirm_schema != state.schema:
        raise ValueError("Cleanup requires the exact schema from this run's metadata")
    engine = qa_engine(state)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Operations(MigrationContext.configure(sync)).execute(
                    sa.schema.DropSchema(state.schema, cascade=True)
                )
            )
    finally:
        await engine.dispose()
