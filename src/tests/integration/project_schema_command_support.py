"""Dedicated PostgreSQL command fixtures; never select a user's application database."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from src.domain.model.project_schema.commands import (
    BootstrapProjectSchema,
    ProjectSchemaAction,
    ProjectSchemaScope,
    ReplaceProjectSchema,
)
from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands import (
    SqlProjectSchemaCommands,
)
from src.tests.integration.project_schema_storage_support import (
    apply_revision,
    schema_storage_pg as _schema_storage_pg,
)

SCOPE = ProjectSchemaScope(tenant_id="tenant-a", project_id="project-a", actor_id="owner")
SCHEMA_ID = "00000000-0000-4000-8000-000000000001"
schema_storage_pg = _schema_storage_pg


@dataclass
class Authorization:
    allowed: ProjectSchemaScope = SCOPE
    deny_on_call: int = 0
    calls: list[tuple[ProjectSchemaScope, ProjectSchemaAction]] = field(default_factory=list)

    async def authorize(self, scope, action):
        self.calls.append((scope, action))
        if scope != self.allowed or len(self.calls) == self.deny_on_call:
            raise ProjectSchemaError("project_schema_access_denied")


def command_revision(connection, direction):
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/1a3218f58274_fence_internal_project_schema_commands.py"
    )
    spec = importlib.util.spec_from_file_location("schema_command_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


@pytest.fixture
async def schema_command_pg(schema_storage_pg):
    engine, sessions = schema_storage_pg
    async with engine.begin() as connection:
        await connection.run_sync(apply_revision, "upgrade")
        await connection.run_sync(command_revision, "upgrade")
    yield engine, sessions


async def activated(sessions):
    authority = SqlProjectSchemaCommands(sessions=sessions, authorization=Authorization())
    receipt = await authority.bootstrap(
        SCOPE, BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
    )
    return authority, receipt


def replacement(receipt, change=None):
    value = receipt.to_dict()["document"]
    previous_revision = value["revision"]
    value["revision"] += 1
    if change is not None:
        change(value)
    return ReplaceProjectSchema(
        document=ProjectSchemaDocument.from_json(json.dumps(value)),
        expected_revision=previous_revision,
        change_id=str(uuid4()),
    )
