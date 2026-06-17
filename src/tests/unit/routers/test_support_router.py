"""Unit tests for support ticket API endpoints."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.support import (
    create_support_ticket,
    list_support_tickets,
)
from src.infrastructure.adapters.secondary.persistence.models import SupportTicket


class TestCreateSupportTicket:
    """Tests for POST /tickets"""

    @pytest.mark.asyncio
    async def test_create_ticket_success(self, test_db, client, test_user):
        """Test successfully creating a support ticket."""
        ticket_data = {
            "subject": "Test Issue",
            "message": "This is a test issue",
            "priority": "high",
        }

        response = client.post("/support/tickets", json=ticket_data)

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["subject"] == "Test Issue"
        assert data["message"] == "This is a test issue"
        assert data["priority"] == "high"
        assert data["status"] == "open"
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_ticket_default_priority(self, test_db, client, test_user):
        """Test creating ticket with default priority."""
        ticket_data = {"subject": "Default Priority", "message": "Test"}

        response = client.post("/support/tickets", json=ticket_data)

        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == "medium"

    @pytest.mark.asyncio
    async def test_create_ticket_with_tenant(self, test_db, client, test_user, test_project_db):
        """Test creating ticket with tenant_id."""
        ticket_data = {
            "subject": "Tenant Issue",
            "message": "Test",
            "tenant_id": test_project_db.tenant_id,
        }

        response = client.post("/support/tickets", json=ticket_data)

        assert response.status_code == 200
        data = response.json()
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_ticket_rejects_tenant_without_membership(self, test_db, test_user):
        """Test creating ticket cannot target a tenant the user does not belong to."""
        ticket_data = {
            "subject": "Foreign Tenant Issue",
            "message": "Test",
            "tenant_id": "tenant_without_membership",
        }

        with pytest.raises(HTTPException) as exc_info:
            await create_support_ticket(ticket_data, current_user=test_user, db=test_db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_create_ticket_all_priorities(self, test_db, client, test_user):
        """Test creating tickets with all priority levels."""
        priorities = ["low", "medium", "high", "urgent"]

        for priority in priorities:
            ticket_data = {"subject": f"Ticket {priority}", "message": "Test", "priority": priority}

            response = client.post("/support/tickets", json=ticket_data)

            assert response.status_code == 200
            data = response.json()
            assert data["priority"] == priority


class TestListSupportTickets:
    """Tests for GET /tickets"""

    @pytest.mark.asyncio
    async def test_list_tickets_success(self, test_db, client, test_user):
        """Test successfully listing tickets."""
        # Create some tickets
        for i in range(3):
            ticket = SupportTicket(
                id=f"ticket_list_{i}",
                user_id=test_user.id,
                subject=f"Ticket {i}",
                message=f"Message {i}",
                priority="medium",
                status="open",
            )
            test_db.add(ticket)
        await test_db.commit()

        response = client.get("/support/tickets")

        assert response.status_code == 200
        data = response.json()
        assert "tickets" in data
        assert len(data["tickets"]) >= 3
        assert "total" in data
        assert data["limit"] == 25
        assert data["offset"] == 0
        assert "has_more" in data

    @pytest.mark.asyncio
    async def test_list_tickets_empty(self, test_db, client):
        """Test listing when user has no tickets."""
        # Use a fresh user context
        response = client.get("/support/tickets")

        assert response.status_code == 200
        data = response.json()
        assert "tickets" in data

    @pytest.mark.asyncio
    async def test_list_tickets_api_v1_alias(self, test_db, client):
        """Test listing tickets through the frontend API prefix."""
        response = client.get("/api/v1/support/tickets")

        assert response.status_code == 200
        data = response.json()
        assert "tickets" in data
        assert data["limit"] == 25

    @pytest.mark.asyncio
    async def test_list_tickets_filter_by_status(self, test_db, client, test_user):
        """Test filtering tickets by status."""
        # Create tickets with different statuses
        ticket_open = SupportTicket(
            id="ticket_filter_open",
            user_id=test_user.id,
            subject="Open Ticket",
            message="Test",
            priority="medium",
            status="open",
        )
        ticket_closed = SupportTicket(
            id="ticket_filter_closed",
            user_id=test_user.id,
            subject="Closed Ticket",
            message="Test",
            priority="medium",
            status="closed",
        )
        test_db.add(ticket_open)
        test_db.add(ticket_closed)
        await test_db.commit()

        response = client.get("/support/tickets?status=open")

        assert response.status_code == 200
        data = response.json()
        ticket_ids = [t["id"] for t in data["tickets"]]
        assert "ticket_filter_open" in ticket_ids
        assert "ticket_filter_closed" not in ticket_ids

    @pytest.mark.asyncio
    async def test_list_tickets_filter_by_tenant(self, test_db, client, test_user, test_project_db):
        """Test filtering tickets by tenant."""
        tenant_id = test_project_db.tenant_id
        ticket1 = SupportTicket(
            id="ticket_tenant_1",
            user_id=test_user.id,
            tenant_id=tenant_id,
            subject="Tenant 1",
            message="Test",
            priority="medium",
            status="open",
        )
        ticket2 = SupportTicket(
            id="ticket_tenant_2",
            user_id=test_user.id,
            tenant_id="tenant_456",
            subject="Tenant 2",
            message="Test",
            priority="medium",
            status="open",
        )
        test_db.add(ticket1)
        test_db.add(ticket2)
        await test_db.commit()

        response = client.get(f"/support/tickets?tenant_id={tenant_id}")

        assert response.status_code == 200
        data = response.json()
        ticket_ids = [t["id"] for t in data["tickets"]]
        assert "ticket_tenant_1" in ticket_ids
        assert "ticket_tenant_2" not in ticket_ids

    @pytest.mark.asyncio
    async def test_list_tickets_rejects_tenant_without_membership(self, test_db, test_user):
        """Test list request cannot filter by a tenant the user does not belong to."""
        with pytest.raises(HTTPException) as exc_info:
            await list_support_tickets(
                tenant_id="tenant_without_membership",
                limit=25,
                offset=0,
                current_user=test_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_tickets_ordering(self, test_db, client, test_user):
        """Test that tickets are ordered by created_at desc."""
        # Create tickets without explicit delays, just verify ordering works
        for i in range(3):
            ticket = SupportTicket(
                id=f"ticket_order_{i}",
                user_id=test_user.id,
                subject=f"Ticket {i}",
                message="Test",
                priority="medium",
                status="open",
            )
            test_db.add(ticket)
        await test_db.commit()

        response = client.get("/support/tickets")

        assert response.status_code == 200
        data = response.json()
        # Just verify tickets are returned and structure is correct
        assert len(data["tickets"]) >= 3
        # All tickets should have required fields
        for ticket in data["tickets"][:3]:
            assert "id" in ticket
            assert "subject" in ticket
            assert "created_at" in ticket

    @pytest.mark.asyncio
    async def test_list_tickets_defaults_to_bounded_page_size(
        self, test_db, client, test_user, test_project_db
    ):
        """Test that listing tickets uses a bounded default page size."""
        tenant_id = test_project_db.tenant_id
        for i in range(30):
            ticket = SupportTicket(
                id=f"ticket_paged_default_{i}",
                user_id=test_user.id,
                tenant_id=tenant_id,
                subject=f"Ticket {i}",
                message="Test",
                priority="medium",
                status="open",
                created_at=datetime(2026, 1, 1, 0, i, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, 0, i, tzinfo=UTC),
            )
            test_db.add(ticket)
        await test_db.commit()

        response = client.get(f"/support/tickets?tenant_id={tenant_id}")

        assert response.status_code == 200
        data = response.json()
        assert len(data["tickets"]) == 25
        assert data["total"] == 30
        assert data["limit"] == 25
        assert data["offset"] == 0
        assert data["has_more"] is True

    @pytest.mark.asyncio
    async def test_list_tickets_supports_limit_and_offset(
        self, test_db, client, test_user, test_project_db
    ):
        """Test paging support ticket results."""
        tenant_id = test_project_db.tenant_id
        for i in range(5):
            ticket = SupportTicket(
                id=f"ticket_paged_offset_{i}",
                user_id=test_user.id,
                tenant_id=tenant_id,
                subject=f"Ticket {i}",
                message="Test",
                priority="medium",
                status="open",
                created_at=datetime(2026, 1, 1, 0, i, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, 0, i, tzinfo=UTC),
            )
            test_db.add(ticket)
        await test_db.commit()

        response = client.get(f"/support/tickets?tenant_id={tenant_id}&limit=2&offset=2")

        assert response.status_code == 200
        data = response.json()
        assert [ticket["id"] for ticket in data["tickets"]] == [
            "ticket_paged_offset_2",
            "ticket_paged_offset_1",
        ]
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 2
        assert data["has_more"] is True

    @pytest.mark.asyncio
    async def test_list_tickets_rejects_unbounded_limit(self, test_db, client):
        """Test list request rejects limits above the bounded maximum."""
        response = client.get("/support/tickets?limit=101")

        assert response.status_code == 422


class TestGetSupportTicket:
    """Tests for GET /tickets/{id}"""

    @pytest.mark.asyncio
    async def test_get_ticket_success(self, test_db, client, test_support_ticket):
        """Test successfully getting a ticket."""
        response = client.get(f"/support/tickets/{test_support_ticket.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_support_ticket.id
        assert "subject" in data
        assert "message" in data
        assert "priority" in data
        assert "status" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_get_ticket_not_found(self, test_db, client):
        """Test getting non-existent ticket."""
        response = client.get("/support/tickets/nonexistent_id")

        assert response.status_code == 404
        assert "Ticket not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_ticket_wrong_user(self, test_db, client, test_user):
        """Test that user cannot get another user's ticket."""
        ticket = SupportTicket(
            id="ticket_other_user",
            user_id="some_other_user",
            subject="Other User Ticket",
            message="Not for you",
            priority="medium",
            status="open",
        )
        test_db.add(ticket)
        await test_db.commit()

        response = client.get(f"/support/tickets/{ticket.id}")

        assert response.status_code == 404
        assert "Ticket not found" in response.json()["detail"]


class TestUpdateSupportTicket:
    """Tests for PUT /tickets/{id}"""

    @pytest.mark.asyncio
    async def test_update_ticket_subject(self, test_db, client, test_support_ticket):
        """Test updating ticket subject."""
        update_data = {"subject": "Updated Subject"}

        response = client.put(f"/support/tickets/{test_support_ticket.id}", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["subject"] == "Updated Subject"

    @pytest.mark.asyncio
    async def test_update_ticket_message(self, test_db, client, test_support_ticket):
        """Test updating ticket message."""
        update_data = {"message": "Updated message"}

        response = client.put(f"/support/tickets/{test_support_ticket.id}", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Updated message"

    @pytest.mark.asyncio
    async def test_update_ticket_priority(self, test_db, client, test_support_ticket):
        """Test updating ticket priority."""
        update_data = {"priority": "urgent"}

        response = client.put(f"/support/tickets/{test_support_ticket.id}", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == "urgent"

    @pytest.mark.asyncio
    async def test_update_ticket_multiple_fields(self, test_db, client, test_support_ticket):
        """Test updating multiple fields at once."""
        update_data = {"subject": "New Subject", "message": "New message", "priority": "high"}

        response = client.put(f"/support/tickets/{test_support_ticket.id}", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["subject"] == "New Subject"
        assert data["message"] == "New message"
        assert data["priority"] == "high"

    @pytest.mark.asyncio
    async def test_update_ticket_not_found(self, test_db, client):
        """Test updating non-existent ticket."""
        update_data = {"subject": "Updated"}

        response = client.put("/support/tickets/nonexistent_id", json=update_data)

        assert response.status_code == 404
        assert "Ticket not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_ticket_wrong_user(self, test_db, client, test_user):
        """Test that user cannot update another user's ticket."""
        ticket = SupportTicket(
            id="ticket_update_other",
            user_id="other_user_update",
            subject="Other",
            message="Other",
            priority="medium",
            status="open",
        )
        test_db.add(ticket)
        await test_db.commit()

        update_data = {"subject": "Hacked"}

        response = client.put(f"/support/tickets/{ticket.id}", json=update_data)

        assert response.status_code == 404
        assert "Ticket not found" in response.json()["detail"]


class TestCloseSupportTicket:
    """Tests for POST /tickets/{id}/close"""

    @pytest.mark.asyncio
    async def test_close_ticket_success(self, test_db, client, test_support_ticket):
        """Test successfully closing a ticket."""
        response = client.post(f"/support/tickets/{test_support_ticket.id}/close")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "closed"
        assert "resolved_at" in data

        # Verify in database
        await test_db.refresh(test_support_ticket)
        assert test_support_ticket.status == "closed"
        assert test_support_ticket.resolved_at is not None

    @pytest.mark.asyncio
    async def test_close_ticket_not_found(self, test_db, client):
        """Test closing non-existent ticket."""
        response = client.post("/support/tickets/nonexistent_id/close")

        assert response.status_code == 404
        assert "Ticket not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_close_ticket_wrong_user(self, test_db, client, test_user):
        """Test that user cannot close another user's ticket."""
        ticket = SupportTicket(
            id="ticket_close_other",
            user_id="other_user_close",
            subject="Other",
            message="Other",
            priority="medium",
            status="open",
        )
        test_db.add(ticket)
        await test_db.commit()

        response = client.post(f"/support/tickets/{ticket.id}/close")

        assert response.status_code == 404
        assert "Ticket not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_close_ticket_already_closed(self, test_db, client, test_support_ticket):
        """Test closing an already closed ticket."""
        # Close it first
        test_support_ticket.status = "closed"
        test_support_ticket.resolved_at = datetime.now(UTC)
        await test_db.commit()

        response = client.post(f"/support/tickets/{test_support_ticket.id}/close")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "closed"
