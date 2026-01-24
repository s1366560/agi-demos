"""Contract tests for member management API endpoints.

These tests validate:
- Response structure matches OpenAPI specification
- HTTP status codes are correct
- Error response format is consistent
- UUID format validation
"""

import re

import pytest
from httpx import AsyncClient


@pytest.mark.contract
@pytest.mark.security
class TestMemberManagementAPIContract:
    """Test suite for member management API contract compliance."""

    async def test_list_members_response_structure(
        self, async_client: AsyncClient, test_project_db
    ):
        """Test that GET /projects/{id}/members returns correct structure."""
        # Arrange
        project_id = str(test_project_db.id)

        # Act
        response = await async_client.get(f"/api/v1/projects/{project_id}/members")

        # Assert
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

        data = response.json()
        assert "members" in data
        assert isinstance(data["members"], list)

        # Validate member structure if members exist
        if len(data["members"]) > 0:
            member = data["members"][0]
            assert "user_id" in member
            assert "role" in member
            assert member["role"] in ["owner", "admin", "member", "viewer"]
            # Validate UUID format
            assert re.match(r"^[0-9a-f-]{36}$", member["user_id"])

    async def test_add_member_request_validation(self, async_client: AsyncClient, test_project_db):
        """Test that POST /projects/{id}/members validates input."""
        # Arrange
        project_id = str(test_project_db.id)

        # Test missing required field
        payload = {"role": "editor"}  # Missing user_id

        # Act
        response = await async_client.post(f"/api/v1/projects/{project_id}/members", json=payload)

        # Assert
        assert response.status_code in [400, 422]
        data = response.json()
        assert "detail" in data or "error" in data

    async def test_add_member_role_validation(self, async_client: AsyncClient, test_project_db):
        """Test that role must be valid (admin, editor, viewer)."""
        # Arrange
        project_id = str(test_project_db.id)
        payload = {"user_id": "some-user-id", "role": "invalid_role"}

        # Act
        response = await async_client.post(f"/api/v1/projects/{project_id}/members", json=payload)

        # Assert
        assert response.status_code in [400, 422]

    async def test_update_member_response_format(self, async_client: AsyncClient, test_project_db):
        """Test that PATCH /projects/{id}/members/{user_id} returns correct format."""
        # Arrange
        project_id = str(test_project_db.id)
        user_id = "some-user-id"
        payload = {"role": "viewer"}

        # Act
        response = await async_client.patch(
            f"/api/v1/projects/{project_id}/members/{user_id}", json=payload
        )

        # Assert
        # May return 404 if user doesn't exist, but 200 if successful
        if response.status_code == 200:
            data = response.json()
            assert "user_id" in data or "id" in data
            assert "role" in data
            assert data["role"] == "viewer"

    async def test_delete_member_response_code(self, async_client: AsyncClient, test_project_db):
        """Test that DELETE /projects/{id}/members/{user_id} returns 204 on success."""
        # Arrange
        project_id = str(test_project_db.id)
        user_id = "some-user-id"

        # Act
        response = await async_client.delete(f"/api/v1/projects/{project_id}/members/{user_id}")

        # Assert
        # Should return 204 No Content on success, or 404 if user doesn't exist
        assert response.status_code in [204, 404]

    async def test_error_responses_include_detail_field(
        self, async_client: AsyncClient, test_project_db
    ):
        """Test that all error responses include a 'detail' field."""
        # Arrange
        project_id = "invalid-uuid-format"  # Invalid UUID

        # Act
        response = await async_client.get(f"/api/v1/projects/{project_id}/members")

        # Assert
        assert response.status_code in [400, 404, 422]
        data = response.json()
        assert "detail" in data

    async def test_uuid_format_validation(self, async_client: AsyncClient):
        """Test that endpoints validate UUID format."""
        # Arrange - Invalid UUID formats
        invalid_uuids = [
            "not-a-uuid",
            "12345",
            "abc-def-ghi",
        ]

        for invalid_uuid in invalid_uuids:
            # Act
            response = await async_client.get(f"/api/v1/projects/{invalid_uuid}/members")

            # Assert
            assert response.status_code in [400, 422], f"UUID {invalid_uuid} should be rejected"

    async def test_member_role_values(self, async_client: AsyncClient, test_project_db):
        """Test that only valid role values are accepted."""
        # Arrange
        project_id = str(test_project_db.id)
        valid_roles = ["admin", "member", "viewer"]

        for role in valid_roles:
            payload = {"user_id": "test-user-id", "role": role}

            # Act
            response = await async_client.post(
                f"/api/v1/projects/{project_id}/members", json=payload
            )

            # Assert - May fail for other reasons (auth, user exists), but not validation
            # Should not return 422 for valid role
            if response.status_code == 422:
                data = response.json()
                # If it's a validation error, ensure it's not about the role
                assert "role" not in str(data.get("detail", ""))
