"""Run one system_event and one agent_turn through the existing cron consumer.

Postgres is a private schema on the local server, not an in-memory database.
The generation Redis client is the project's Redis. LiteLLM completion is
replaced so no vendor is called. The provider row uses the real encryption
service and a tenant mapping. The project skill root is the isolated project
path, so the checkout's unrelated drone skill is not mixed into this generation.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Column, MetaData, String, Table, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.legacy_cron_admission_model import (
    LegacyCronAdmissionModel,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    Conversation,
    CronJobModel,
    CronJobRunModel,
    CronSchedulerOwnerModel,
    HITLRequest,
    Project,
    Tenant,
    TenantAgentConfig,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.persistence.llm_providers_models import (
    LLMProvider,
    TenantProviderMapping,
)
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.security.encryption_service import get_encryption_service

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[4]


def _tables() -> tuple[Any, ...]:
    return (
        User.__table__,
        Tenant.__table__,
        Project.__table__,
        UserTenant.__table__,
        UserProject.__table__,
        Conversation.__table__,
        TenantAgentConfig.__table__,
        AgentRunAuthorityModel.__table__,
        AgentExecutionEvent.__table__,
        HITLRequest.__table__,
        LLMProvider.__table__,
        TenantProviderMapping.__table__,
        CronJobModel.__table__,
        CronJobRunModel.__table__,
        CronSchedulerOwnerModel.__table__,
        LegacyCronAdmissionModel.__table__,
    )


@pytest.mark.asyncio
async def test_system_event_and_agent_turn_reach_the_scripted_supplier(  # noqa: PLR0915
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = f"qa_cron_{uuid.uuid4().hex[:8]}"
    url = get_settings().postgres_url
    database_name = make_url(url).database
    assert database_name
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(
            text(f'ALTER DATABASE "{database_name}" SET search_path TO {schema}, public')
        )
    from src.infrastructure.adapters.secondary.persistence.database import engine as shared_engine

    await shared_engine.dispose()
    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    calls: list[str] = []

    async def scripted_completion(**kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        calls.append(str(messages))
        calls.append("supplier-return:scripted-ok")
        if kwargs.get("stream"):

            async def chunks() -> Any:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="scripted-ok", tool_calls=None),
                            finish_reason="stop",
                        )
                    ],
                    usage=None,
                )

            return chunks()
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="scripted-ok", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

    from src.infrastructure.plugins.v2.agent_worker_runtime import (
        agent_worker_redis_runtime_factory_v2,
    )

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            redis_runtime_factory=agent_worker_redis_runtime_factory_v2,
        )
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        factory,
    )
    monkeypatch.setattr(
        "src.infrastructure.persistence.llm_providers_repository.async_session_factory",
        factory,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.actor.execution.async_session_factory",
        factory,
    )
    monkeypatch.setattr(
        "src.application.services.agent.runtime_bootstrapper.AgentRuntimeBootstrapper._resolve_runtime_mode",
        staticmethod(lambda **_kwargs: "local"),
    )
    monkeypatch.setattr("litellm.acompletion", scripted_completion)
    try:
        async with engine.begin() as connection:
            stubs = MetaData()
            for name in ("agent_plan_runs", "agent_plan_versions"):
                Table(name, stubs, Column("id", String, primary_key=True))
            await connection.run_sync(stubs.create_all)
            await connection.run_sync(lambda sync: [table.create(sync) for table in _tables()])
        await host.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=1,
            version=1,
            nonce="cron-scripted",
        )
        install_process_generation_host_v2(host)
        suffix = uuid.uuid4().hex[:8]
        user_id = f"user-{suffix}"
        tenant_id = f"tenant-{suffix}"
        project_id = f"project-{suffix}"
        encrypted = get_encryption_service().encrypt("scripted-test-credential")
        provider_id = uuid.uuid4()
        async with factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"{suffix}@cron.test",
                    hashed_password="not-a-credential",
                    is_active=True,
                    is_superuser=False,
                    profile={},
                )
            )
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"tenant-{suffix}",
                    slug=f"slug-{suffix}",
                    owner_id=user_id,
                    plan="free",
                    max_projects=1,
                    max_users=1,
                    max_storage=1,
                )
            )
            session.add(
                UserTenant(
                    id=f"ut-{suffix}",
                    user_id=user_id,
                    tenant_id=tenant_id,
                    role="owner",
                    permissions={},
                )
            )
            session.add(
                Project(
                    id=project_id,
                    tenant_id=tenant_id,
                    name=f"project-{suffix}",
                    owner_id=user_id,
                    memory_rules={},
                    graph_config={},
                    sandbox_type="cloud",
                    sandbox_config={},
                    is_public=False,
                )
            )
            await session.flush()
            session.add(
                UserProject(
                    id=f"up-{suffix}",
                    user_id=user_id,
                    project_id=project_id,
                    role="owner",
                    permissions={},
                )
            )
            session.add(
                LLMProvider(
                    id=provider_id,
                    name=f"scripted-{suffix}",
                    provider_type="openai",
                    operation_type="llm",
                    api_key_encrypted=encrypted,
                    base_url="http://127.0.0.1:9",
                    llm_model="scripted-test",
                    config={},
                    is_active=True,
                    is_default=False,
                    is_enabled=True,
                )
            )
            session.add(
                TenantProviderMapping(
                    tenant_id=tenant_id,
                    operation_type="llm",
                    provider_id=provider_id,
                    priority=0,
                )
            )
            session.add(
                CronJobModel(
                    id=f"system-{suffix}",
                    project_id=project_id,
                    tenant_id=tenant_id,
                    name="system",
                    enabled=True,
                    schedule_type="every",
                    schedule_config={"interval_seconds": 3600},
                    payload_type="system_event",
                    payload_config={"content": "system-marker"},
                    delivery_type="none",
                    created_by=user_id,
                )
            )
            session.add(
                CronJobModel(
                    id=f"agent-{suffix}",
                    project_id=project_id,
                    tenant_id=tenant_id,
                    name="agent",
                    enabled=True,
                    schedule_type="every",
                    schedule_config={"interval_seconds": 3600},
                    payload_type="agent_turn",
                    payload_config={"message": "agent-marker"},
                    delivery_type="none",
                    created_by=user_id,
                )
            )
            await session.commit()

        import logging

        from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
        from src.infrastructure.scheduler.job_executor import execute_cron_job

        captured: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())
                if record.exc_info and record.exc_info[1] is not None:
                    captured.append(str(record.exc_info[1]))

        handler = _Capture()
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            await execute_cron_job(f"system-{suffix}")
            await execute_cron_job(f"agent-{suffix}")
            workers = list(AgentRuntimeBootstrapper._local_chat_queue_tasks.values())
            for worker in workers:
                await worker
        finally:
            root.removeHandler(handler)
        assert any("system-marker" in call for call in calls), captured[-30:]
        assert any("agent-marker" in call for call in calls)
        assert calls.count("supplier-return:scripted-ok") >= 2
        assert not any("duplicate sources" in line for line in captured)
    finally:
        clear_process_generation_host_v2(host)
        await host.close()
        await engine.dispose()
        await shared_engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'ALTER DATABASE "{database_name}" RESET search_path'))
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()
        _ = async_session_factory
