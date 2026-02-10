"""Unit tests for billing API endpoints."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.infrastructure.adapters.secondary.persistence.models import (
    Invoice,
    Memory,
    Project,
    UserTenant,
)


class TestGetBillingInfo:
    """Tests for GET /tenants/{tenant_id}/billing"""

    @pytest.mark.asyncio
    async def test_get_billing_success_admin(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test getting billing info as admin."""
        # Create user-tenant relationship with admin role
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="admin"
        )
        test_db.add(user_tenant)

        # Add some test data (Project doesn't have storage_used field)
        project = Project(
            id="proj_billing_1",
            tenant_id=test_tenant["id"],
            name="Billing Test Project",
            description="Test",
            owner_id=test_user.id,
        )
        test_db.add(project)

        memory = Memory(
            id="mem_billing_1",
            project_id=project.id,
            title="Test Memory",
            content="Test content",
            author_id=test_user.id,
        )
        test_db.add(memory)

        # Add invoice
        invoice = Invoice(
            id="inv_123",
            tenant_id=test_tenant["id"],
            amount=2999,
            currency="USD",
            status="paid",
            period_start=datetime.now(timezone.utc) - timedelta(days=30),
            period_end=datetime.now(timezone.utc),
        )
        test_db.add(invoice)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/billing")

        assert response.status_code == 200
        data = response.json()
        assert "tenant" in data
        assert "usage" in data
        assert "invoices" in data

        # Verify tenant info
        assert data["tenant"]["id"] == test_tenant["id"]
        assert "plan" in data["tenant"]

        # Verify usage stats
        assert data["usage"]["projects"] >= 1
        assert data["usage"]["memories"] >= 1
        assert "storage" in data["usage"]

        # Verify invoices
        assert len(data["invoices"]) >= 1
        assert data["invoices"][0]["id"] == invoice.id

    @pytest.mark.asyncio
    async def test_get_billing_success_owner(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test getting billing info as owner."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="owner"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/billing")

        assert response.status_code == 200
        data = response.json()
        assert "tenant" in data
        assert "usage" in data

    @pytest.mark.asyncio
    async def test_get_billing_access_denied_member(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test that member role cannot access billing info."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="member"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/billing")

        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_billing_access_denied_viewer(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test that viewer role cannot access billing info."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="viewer"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/billing")

        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_billing_no_tenant_access(self, test_db, client, test_tenant):
        """Test billing access when user has no tenant relationship."""
        response = client.get(f"/tenants/{test_tenant['id']}/billing")

        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_billing_tenant_not_found(self, test_db, client, test_user):
        """Test billing info for non-existent tenant."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id="nonexistent_tenant", role="admin"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        response = client.get("/tenants/nonexistent_tenant/billing")

        assert response.status_code == 404
        assert "Tenant not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_billing_usage_calculation(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test that usage statistics are calculated correctly."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="admin"
        )
        test_db.add(user_tenant)

        # Create multiple projects
        for i in range(3):
            project = Project(
                id=f"proj_usage_{i}",
                tenant_id=test_tenant["id"],
                name=f"Project {i}",
                description="Test",
                owner_id=test_user.id,
            )
            test_db.add(project)

            # Add memories to each project
            for j in range(2):
                memory = Memory(
                    id=f"mem_usage_{i}_{j}",
                    project_id=project.id,
                    title=f"Memory {i}-{j}",
                    content="Content",
                    author_id=test_user.id,
                )
                test_db.add(memory)

        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/billing")

        assert response.status_code == 200
        data = response.json()
        assert data["usage"]["projects"] == 3
        assert data["usage"]["memories"] == 6
        # Storage will be 0 since Project model doesn't have storage_used field
        assert data["usage"]["storage"] == 0

    @pytest.mark.asyncio
    async def test_get_billing_invoices_limit(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test that only recent 12 invoices are returned."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="admin"
        )
        test_db.add(user_tenant)

        # Create 15 invoices
        for i in range(15):
            invoice = Invoice(
                id=f"inv_{i}",
                tenant_id=test_tenant["id"],
                amount=1000 + i * 100,
                currency="USD",
                status="paid",
                period_start=datetime.now(timezone.utc) - timedelta(days=30 + i),
                period_end=datetime.now(timezone.utc) - timedelta(days=29 + i),
            )
            test_db.add(invoice)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/billing")

        assert response.status_code == 200
        data = response.json()
        # Should only return 12 invoices
        assert len(data["invoices"]) == 12


class TestListInvoices:
    """Tests for GET /tenants/{tenant_id}/invoices"""

    @pytest.mark.asyncio
    async def test_list_invoices_success_admin(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test listing invoices as admin."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="admin"
        )
        test_db.add(user_tenant)

        # Create test invoices
        for i in range(3):
            invoice = Invoice(
                id=f"inv_list_{i}",
                tenant_id=test_tenant["id"],
                amount=1000 * (i + 1),
                currency="USD",
                status="paid" if i < 2 else "pending",
                period_start=datetime.now(timezone.utc) - timedelta(days=30 * (i + 1)),
                period_end=datetime.now(timezone.utc) - timedelta(days=30 * i),
            )
            test_db.add(invoice)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/invoices")

        assert response.status_code == 200
        data = response.json()
        assert "invoices" in data
        assert len(data["invoices"]) == 3

        # Verify invoice structure
        invoice = data["invoices"][0]
        assert "id" in invoice
        assert "amount" in invoice
        assert "currency" in invoice
        assert "status" in invoice
        assert "period_start" in invoice
        assert "period_end" in invoice

    @pytest.mark.asyncio
    async def test_list_invoices_success_owner(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test listing invoices as owner."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="owner"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/invoices")

        assert response.status_code == 200
        data = response.json()
        assert "invoices" in data

    @pytest.mark.asyncio
    async def test_list_invoices_access_denied_member(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test that member cannot list invoices."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="member"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/invoices")

        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_invoices_empty(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test listing invoices when none exist."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="admin"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/invoices")

        assert response.status_code == 200
        data = response.json()
        assert data["invoices"] == []

    @pytest.mark.asyncio
    async def test_list_invoices_ordering(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test that invoices are ordered by created_at descending."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="admin"
        )
        test_db.add(user_tenant)

        # Create invoices with different timestamps
        base_time = datetime.now(timezone.utc)
        for i in range(3):
            invoice = Invoice(
                id=f"inv_order_{i}",
                tenant_id=test_tenant["id"],
                amount=1000,
                currency="USD",
                status="paid",
                period_start=base_time - timedelta(days=10 * i),
                period_end=base_time - timedelta(days=10 * i - 1),
            )
            test_db.add(invoice)
        await test_db.commit()

        response = client.get(f"/tenants/{test_tenant['id']}/invoices")

        assert response.status_code == 200
        data = response.json()
        assert len(data["invoices"]) == 3
        # Most recent should be first
        assert data["invoices"][0]["id"] == "inv_order_0"


class TestUpgradePlan:
    """Tests for POST /tenants/{tenant_id}/upgrade"""

    @pytest.mark.asyncio
    async def test_upgrade_to_pro_success(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test successful upgrade to Pro plan."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="owner"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        plan_data = {"plan": "pro"}
        response = client.post(f"/tenants/{test_tenant['id']}/upgrade", json=plan_data)

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["tenant"]["plan"] == "pro"
        assert data["tenant"]["storage_limit"] == 100 * 1024 * 1024 * 1024  # 100GB

    @pytest.mark.asyncio
    async def test_upgrade_to_free_success(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test downgrading to Free plan."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="owner"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        plan_data = {"plan": "free"}
        response = client.post(f"/tenants/{test_tenant['id']}/upgrade", json=plan_data)

        assert response.status_code == 200
        data = response.json()
        assert data["tenant"]["plan"] == "free"
        assert data["tenant"]["storage_limit"] == 10 * 1024 * 1024 * 1024  # 10GB

    @pytest.mark.asyncio
    async def test_upgrade_to_enterprise_success(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test successful upgrade to Enterprise plan."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="owner"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        plan_data = {"plan": "enterprise"}
        response = client.post(f"/tenants/{test_tenant['id']}/upgrade", json=plan_data)

        assert response.status_code == 200
        data = response.json()
        assert data["tenant"]["plan"] == "enterprise"
        assert data["tenant"]["storage_limit"] == 1024 * 1024 * 1024 * 1024  # 1TB

    @pytest.mark.asyncio
    async def test_upgrade_access_denied_admin(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test that admin cannot upgrade plan (only owner)."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="admin"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        plan_data = {"plan": "pro"}
        response = client.post(f"/tenants/{test_tenant['id']}/upgrade", json=plan_data)

        assert response.status_code == 403
        assert "Only owner can upgrade plan" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_upgrade_access_denied_member(
        self, test_db, client, test_tenant_in_db, test_user, test_tenant
    ):
        """Test that member cannot upgrade plan."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id=test_tenant["id"], role="member"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        plan_data = {"plan": "pro"}
        response = client.post(f"/tenants/{test_tenant['id']}/upgrade", json=plan_data)

        assert response.status_code == 403
        assert "Only owner can upgrade plan" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_upgrade_tenant_not_found(self, test_db, client, test_user):
        """Test upgrading non-existent tenant."""
        user_tenant = UserTenant(
            id=str(uuid.uuid4()), user_id=test_user.id, tenant_id="nonexistent_tenant", role="owner"
        )
        test_db.add(user_tenant)
        await test_db.commit()

        plan_data = {"plan": "pro"}
        response = client.post("/tenants/nonexistent_tenant/upgrade", json=plan_data)

        assert response.status_code == 404
        assert "Tenant not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_upgrade_no_access(self, test_db, client, test_tenant):
        """Test upgrade when user has no tenant relationship."""
        plan_data = {"plan": "pro"}
        response = client.post(f"/tenants/{test_tenant['id']}/upgrade", json=plan_data)

        assert response.status_code == 403
        assert "Only owner can upgrade plan" in response.json()["detail"]
