"""Nonterminal history survives later revisions and rejects raw SQL resurrection."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from src.domain.model.project_schema.commands import ReplaceProjectSchema
from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands import (
    _admit,
    _advance_head,
)
from src.tests.integration.project_schema_command_support import (
    SCOPE,
    activated,
    replacement,
    schema_command_pg as _schema_command_pg,
    schema_storage_pg as _schema_storage_pg,
)

pytestmark = pytest.mark.integration
schema_storage_pg = _schema_storage_pg
schema_command_pg = _schema_command_pg


def remove_entity_and_mapping(value):
    for key, kind in (("entity_types", "entity_type"), ("mappings", "mapping")):
        value["tombstones"].extend(
            {"id": item["id"], "kind": kind, "deleted_revision": value["revision"]}
            for item in value[key]
        )
        value[key] = []


async def test_nonterminal_tombstones_remain_unchanged_in_later_cas(schema_command_pg):
    engine, sessions = schema_command_pg
    authority, initial = await activated(sessions)
    deleted = await authority.replace(SCOPE, replacement(initial, remove_entity_and_mapping))
    later = await authority.replace(
        SCOPE,
        replacement(deleted, lambda value: value["edge_types"][0].update(description="later")),
    )
    assert later.to_dict()["document"]["tombstones"] == deleted.to_dict()["document"]["tombstones"]
    async with engine.connect() as connection:
        assert (
            await connection.scalar(sa.text("SELECT count(*) FROM project_schema_tombstones")) == 2
        )
        assert (
            await connection.scalar(
                sa.text("SELECT max(deleted_revision) FROM project_schema_tombstones")
            )
            == 2
        )


@pytest.mark.parametrize(
    "defect", ["omitted_tombstone", "resurrection", "changed_kind", "missing_new_tombstones"]
)
async def test_database_transition_checks_do_not_trust_only_the_domain_caller(
    schema_command_pg, defect
):
    _engine, sessions = schema_command_pg
    authority, initial = await activated(sessions)
    if defect == "missing_new_tombstones":
        previous = initial
        value = initial.to_dict()["document"]
        value["revision"] = 2
        value["entity_types"] = []
        value["mappings"] = []
    else:
        previous = await authority.replace(SCOPE, replacement(initial, remove_entity_and_mapping))
        value = previous.to_dict()["document"]
        value["revision"] += 1
        if defect == "omitted_tombstone":
            value["tombstones"] = []
        elif defect == "resurrection":
            value["tombstones"] = []
            value["entity_types"] = initial.to_dict()["document"]["entity_types"]
        else:
            value["tombstones"][0]["kind"] = "edge_type"
    # A standalone snapshot cannot prove history; bypass the Python successor
    # helper deliberately, and require the database to reject the transition.
    document = ProjectSchemaDocument.from_json(json.dumps(value))
    command = ReplaceProjectSchema(
        document=document, expected_revision=previous.to_dict()["revision"], change_id=str(uuid4())
    )
    with pytest.raises(DBAPIError, match="project_schema_(tombstone|member_identity)"):
        async with sessions() as db, db.begin():
            await _admit(
                db,
                SCOPE,
                document=document,
                change_id=command.change_id,
                expected_revision=command.expected_revision,
                request_json=command.request_json(SCOPE),
                source_kind="mutation",
            )
            await _advance_head(db, SCOPE, document=document, exists=True)
    actual = await authority.read(SCOPE)
    assert actual is not None and actual.to_dict() == previous.to_dict()["document"]
