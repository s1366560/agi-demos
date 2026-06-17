"""Query ordering tests for project and tenant list routers."""

from sqlalchemy import select

from src.infrastructure.adapters.primary.web.routers.projects import _order_project_list_query
from src.infrastructure.adapters.primary.web.routers.tenants import _order_tenant_list_query
from src.infrastructure.adapters.secondary.persistence.models import Project, Tenant


def test_project_list_router_query_declares_deterministic_order_by() -> None:
    statement = _order_project_list_query(select(Project))

    assert "ORDER BY projects.created_at DESC, projects.id ASC" in str(statement)


def test_tenant_list_router_query_declares_deterministic_order_by() -> None:
    statement = _order_tenant_list_query(select(Tenant))

    assert "ORDER BY tenants.created_at DESC, tenants.id ASC" in str(statement)
