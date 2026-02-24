import pytest


async def _get_or_create_tenant(ac) -> str:
    """Get or create a tenant and return its ID."""
    print("\n1. Creating Tenant...")
    tenant_response = await ac.post(
        "/api/v1/tenants/",
        json={
            "name": "Integration Test Tenant",
            "description": "Tenant for project tests",
            "plan": "free",
        },
    )

    if tenant_response.status_code == 201:
        tenant_id = tenant_response.json()["id"]
        print(f"✅ Created Tenant: {tenant_id}")
        return tenant_id

    if tenant_response.status_code == 400 and "User already owns a tenant" in tenant_response.text:
        list_response = await ac.get("/api/v1/tenants/")
        if list_response.status_code == 200 and list_response.json()["tenants"]:
            tenant_id = list_response.json()["tenants"][0]["id"]
            print(f"✅ Using existing Tenant: {tenant_id}")
            return tenant_id
        pytest.fail("Failed to get existing tenant")

    pytest.fail(f"❌ Failed to get tenant: {tenant_response.status_code} - {tenant_response.text}")
    return ""  # unreachable


async def _create_project(ac, tenant_id: str) -> dict:
    """Create a project with complex config and return its data."""
    print("\n2. Creating Project with Memory Rules Config...")
    project_data = {
        "name": "Test Project",
        "description": "Integration Test Project",
        "tenant_id": tenant_id,
        "memory_rules": {
            "max_episodes": 1000,
            "retention_days": 30,
            "auto_refresh": True,
            "refresh_interval": 24,
        },
        "graph_config": {
            "max_nodes": 5000,
            "max_edges": 10000,
            "similarity_threshold": 0.7,
            "community_detection": True,
        },
        "is_public": False,
    }

    response = await ac.post("/api/v1/projects/", json=project_data)

    if response.status_code == 201:
        project = response.json()
        print(f"✅ Project created successfully: {project['id']}")
        print(f"   Memory Rules: {project['memory_rules']}")
        print(f"   Graph Config: {project['graph_config']}")
        return project

    pytest.fail(f"❌ Create Project failed: {response.status_code} - {response.text}")
    return {}  # unreachable


def _verify_project_structure(project: dict) -> None:
    """Verify the created project has the expected structure."""
    assert isinstance(project["memory_rules"], dict)
    assert project["memory_rules"]["max_episodes"] == 1000
    assert project["graph_config"]["community_detection"] is True


async def _verify_list_projects(ac, tenant_id: str) -> None:
    """Verify projects can be listed for the tenant."""
    print("\n3. Listing Projects...")
    response = await ac.get(f"/api/v1/projects/?tenant_id={tenant_id}")
    assert response.status_code == 200
    projects_list = response.json()["projects"]
    assert len(projects_list) >= 1
    print(f"✅ Listed {len(projects_list)} projects")


async def _verify_get_project(ac, project_id: str) -> None:
    """Verify a project can be retrieved by ID."""
    print("\n4. Getting Project Details...")
    response = await ac.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 200
    project_details = response.json()
    assert project_details["id"] == project_id
    print("✅ Retrieved project details")


async def _update_and_verify_project(ac, project_id: str) -> None:
    """Update a project and verify the changes."""
    print("\n5. Updating Project...")
    update_data = {"description": "Updated Description", "is_public": True}
    response = await ac.put(f"/api/v1/projects/{project_id}", json=update_data)
    assert response.status_code == 200
    updated_project = response.json()
    assert updated_project["description"] == "Updated Description"
    assert updated_project["is_public"] is True
    print("✅ Updated project")


async def _delete_and_verify_project(ac, project_id: str) -> None:
    """Delete a project and verify it is no longer accessible."""
    print("\n6. Deleting Project...")
    response = await ac.delete(f"/api/v1/projects/{project_id}")
    assert response.status_code in [200, 204]
    print("✅ Deleted project")

    response = await ac.get(f"/api/v1/projects/{project_id}")
    assert response.status_code in [403, 404]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_project_flow(authenticated_async_client, test_user):
    AC = authenticated_async_client

    tenant_id = await _get_or_create_tenant(AC)

    project = await _create_project(AC, tenant_id)
    _verify_project_structure(project)
    project_id = project["id"]

    await _verify_list_projects(AC, tenant_id)
    await _verify_get_project(AC, project_id)
    await _update_and_verify_project(AC, project_id)
    await _delete_and_verify_project(AC, project_id)

    print("\n✅ All Project Integration Tests Passed!")
