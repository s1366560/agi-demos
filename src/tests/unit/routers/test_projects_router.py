from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.project import ProjectCreate
from src.application.services.graph_store_service import GraphStoreService
from src.application.services.retrieval_store_service import RetrievalStoreService
from src.infrastructure.adapters.primary.web.routers.projects import create_project, get_project
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
)
from src.infrastructure.adapters.secondary.persistence.sql_graph_store_repository import (
    SqlGraphStoreRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_retrieval_store_repository import (
    SqlRetrievalStoreRepository,
)
from src.infrastructure.graph.backend_factory import build_default_factory
from src.infrastructure.graph.registry import get_graph_backend_registry
from src.infrastructure.plugins.v2.backend_store_services import BackendStoreServicesV2
from src.infrastructure.retrieval.backend_factory import build_default_retrieval_factory
from src.infrastructure.retrieval.registry import get_retrieval_backend_registry


def _backend_store_authority(db: AsyncSession) -> SimpleNamespace:
    return SimpleNamespace(
        db=db,
        services=BackendStoreServicesV2(
            graph_service=GraphStoreService(
                repo=SqlGraphStoreRepository(db),
                registry=get_graph_backend_registry(),
                factory=build_default_factory(),
            ),
            retrieval_service=RetrievalStoreService(
                repo=SqlRetrievalStoreRepository(db),
                registry=get_retrieval_backend_registry(),
                factory=build_default_retrieval_factory(),
            ),
        ),
    )


@pytest.mark.unit
async def test_create_project_internal_error_is_sanitized(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        test_db,
        "commit",
        AsyncMock(side_effect=RuntimeError("postgres://secret-host/internal failure")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_project(
            ProjectCreate(name="Broken Project", tenant_id=test_tenant_db.id),
            current_user=test_user,
            backend_store=_backend_store_authority(test_db),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to create project"
    assert "secret-host" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_create_project_returns_effective_backend_summaries(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_user: User,
) -> None:
    response = await create_project(
        ProjectCreate(
            name="Backend Bound Project",
            tenant_id=test_tenant_db.id,
            graph_store_id="__env_neo4j__",
            retrieval_store_id="__env_memstack_pgvector__",
        ),
        current_user=test_user,
        backend_store=_backend_store_authority(test_db),
    )

    assert response.graph_store_id is None
    assert response.retrieval_store_id is None
    assert response.graph_store is not None
    assert response.graph_store.source == "env"
    assert response.graph_store.engine_type == "neo4j"
    assert response.retrieval_store is not None
    assert response.retrieval_store.source == "env"
    assert response.retrieval_store.engine_type == "memstack_pgvector"


@pytest.mark.unit
async def test_get_project_rejects_requested_tenant_mismatch(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_user: User,
) -> None:
    other_tenant = Tenant(
        id="tenant-other",
        name="Other Tenant",
        slug="other-tenant",
        description="Tenant outside the requested route scope",
        owner_id=test_user.id,
        plan="free",
        max_projects=10,
        max_users=5,
        max_storage=1073741824,
    )
    project = Project(
        id="project-other-tenant",
        tenant_id=other_tenant.id,
        name="Other Tenant Project",
        description="Should not be returned through another tenant scope",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    user_project = UserProject(
        id=str(uuid4()),
        user_id=test_user.id,
        project_id=project.id,
        role="owner",
        permissions={"read": True, "write": True, "admin": True},
    )
    test_db.add_all([other_tenant, project, user_project])
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await get_project(
            project.id,
            tenant_id=test_tenant_db.id,
            current_user=test_user,
            backend_store=_backend_store_authority(test_db),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Project not found in requested tenant"
