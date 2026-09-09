"""PostgreSQL repository verification for the seeded governance samples.

Runs the same fixture rows used by the HTTP acceptance suite through the real
PostgreSQL repositories inside a private, dropped-after-use schema so JSONB
round-trips and tenant scoping are verified on the production dialect.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import Column, MetaData, String, Table, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from scripts.qa_governance_fixtures import (
    build_qa_governance_samples,
    seed_qa_governance_rows,
)
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.models import (
    AuditLog,
    DecisionRecordModel,
    Playbook,
    ReflectionVerdictRecord,
    TenantEventLogModel,
    TrustPolicyModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_audit_repository import (
    SqlAuditRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_decision_record_repository import (
    SqlDecisionRecordRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_event_log_repository import (
    SqlEventLogRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_playbook_repository import (
    SqlPlaybookRepository,
)

pytestmark = pytest.mark.integration

QA_REPO_OWNER_ID = "qa-governance-repo-owner"
OTHER_TENANT_ID = str(uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))


@pytest_asyncio.fixture(loop_scope="function")
async def governance_pg():
    schema = f"qa_governance_{uuid.uuid4().hex}"
    url = get_settings().postgres_url
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            metadata = MetaData()
            for name in ("tenants", "projects"):
                Table(name, metadata, Column("id", String, primary_key=True))
            TenantEventLogModel.__table__.to_metadata(metadata)
            DecisionRecordModel.__table__.to_metadata(metadata)
            TrustPolicyModel.__table__.to_metadata(metadata)
            AuditLog.__table__.to_metadata(metadata)
            Playbook.__table__.to_metadata(metadata)
            ReflectionVerdictRecord.__table__.to_metadata(metadata)
            await connection.run_sync(metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def seeded_pg(governance_pg):
    samples = build_qa_governance_samples(QA_REPO_OWNER_ID)
    async with governance_pg() as session:
        await session.execute(
            text("INSERT INTO tenants (id) VALUES (:id)"), {"id": samples.tenant_id}
        )
        await session.execute(
            text("INSERT INTO projects (id) VALUES (:id)"), {"id": samples.project_id}
        )
        await seed_qa_governance_rows(session, samples)
        await session.commit()
    return samples


async def test_event_log_repository_round_trips_jsonb_metadata(governance_pg, seeded_pg) -> None:
    async with governance_pg() as session:
        repository = SqlEventLogRepository(session)
        items, total = await repository.find_by_tenant(seeded_pg.tenant_id, page_size=50)

        assert total == len(seeded_pg.event_logs)
        by_id = {item.id: item for item in items}
        for spec in seeded_pg.event_logs:
            assert by_id[spec["id"]].metadata == spec["metadata"]

        types = await repository.get_event_types(seeded_pg.tenant_id)
        assert set(types) == {"user.login", "deploy.started", "gene.installed"}


async def test_event_log_repository_scopes_to_tenant(governance_pg, seeded_pg) -> None:
    async with governance_pg() as session:
        repository = SqlEventLogRepository(session)
        _items, total = await repository.find_by_tenant(OTHER_TENANT_ID, page_size=50)

        assert total == 0


async def test_decision_record_repository_returns_seeded_outcomes(governance_pg, seeded_pg) -> None:
    async with governance_pg() as session:
        repository = SqlDecisionRecordRepository(session)
        records = await repository.find_by_workspace(seeded_pg.workspace_id)

        assert {record.outcome for record in records} == {"pending", "success", "rejected"}
        approved = await repository.find_by_id(seeded_pg.decision_records[1]["id"])
        assert approved is not None
        assert approved.proposal == seeded_pg.decision_records[1]["proposal"]
        assert approved.review_comment == "Allowed once"


async def test_audit_repository_filters_seeded_actions(governance_pg, seeded_pg) -> None:
    async with governance_pg() as session:
        repository = SqlAuditRepository(session)
        entries = await repository.find_by_tenant_filtered(
            seeded_pg.tenant_id, action="trust.approval_resolved", limit=50
        )

        assert len(entries) == 2
        assert {entry.resource_id for entry in entries} == {
            seeded_pg.decision_records[1]["id"],
            seeded_pg.decision_records[2]["id"],
        }


async def test_playbook_repository_round_trips_trigger_and_steps(governance_pg, seeded_pg) -> None:
    async with governance_pg() as session:
        repository = SqlPlaybookRepository(session)
        playbooks = await repository.find_by_project(seeded_pg.project_id, limit=10)

        assert len(playbooks) == len(seeded_pg.playbooks)
        by_id = {playbook.id: playbook for playbook in playbooks}
        retry = by_id[seeded_pg.playbooks[0]["id"]]
        assert retry.trigger.description == seeded_pg.playbooks[0]["trigger"]["description"]
        assert retry.trigger.friction_kinds == ("dlq_retry_failure",)
        assert [step.instruction for step in retry.steps] == [
            step["instruction"] for step in seeded_pg.playbooks[0]["steps"]
        ]
        assert retry.hit_count == seeded_pg.playbooks[0]["hit_count"]
