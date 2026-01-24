import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_project_flow(authenticated_async_client, test_user):
    AC = authenticated_async_client

    # 1. Get/Create Tenant
    print("\n1. Creating Tenant...")
    tenant_response = await AC.post(
        "/api/v1/tenants/",
        json={
            "name": "Integration Test Tenant",
            "description": "Tenant for project tests",
            "plan": "free",
        },
    )

    tenant_id = ""
    if tenant_response.status_code == 201:
        tenant_id = tenant_response.json()["id"]
        print(f"✅ Created Tenant: {tenant_id}")
    elif (
        tenant_response.status_code == 400 and "User already owns a tenant" in tenant_response.text
    ):
        # List tenants
        list_response = await AC.get("/api/v1/tenants/")
        if list_response.status_code == 200 and list_response.json()["tenants"]:
            tenant_id = list_response.json()["tenants"][0]["id"]
            print(f"✅ Using existing Tenant: {tenant_id}")
        else:
            pytest.fail("Failed to get existing tenant")
    else:
        pytest.fail(
            f"❌ Failed to get tenant: {tenant_response.status_code} - {tenant_response.text}"
        )

    # 2. Create Project with complex config
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

    response = await AC.post("/api/v1/projects/", json=project_data)

    if response.status_code == 201:
        project = response.json()
        print(f"✅ Project created successfully: {project['id']}")
        print(f"   Memory Rules: {project['memory_rules']}")
        print(f"   Graph Config: {project['graph_config']}")

        # Verify structure
        assert isinstance(project["memory_rules"], dict)
        assert project["memory_rules"]["max_episodes"] == 1000
        assert project["graph_config"]["community_detection"] is True

    else:
        pytest.fail(f"❌ Create Project failed: {response.status_code} - {response.text}")

    project_id = project["id"]

    # 3. List Projects
    print("\n3. Listing Projects...")
    response = await AC.get(f"/api/v1/projects/?tenant_id={tenant_id}")
    assert response.status_code == 200
    projects_list = response.json()["projects"]
    assert len(projects_list) >= 1
    print(f"✅ Listed {len(projects_list)} projects")

    # 4. Get Project Details
    print("\n4. Getting Project Details...")
    response = await AC.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 200
    project_details = response.json()
    assert project_details["id"] == project_id
    print("✅ Retrieved project details")

    # 5. Update Project
    print("\n5. Updating Project...")
    update_data = {"description": "Updated Description", "is_public": True}
    response = await AC.put(f"/api/v1/projects/{project_id}", json=update_data)
    assert response.status_code == 200
    updated_project = response.json()
    assert updated_project["description"] == "Updated Description"
    assert updated_project["is_public"] is True
    print("✅ Updated project")

    # 6. Delete Project
    print("\n6. Deleting Project...")
    response = await AC.delete(f"/api/v1/projects/{project_id}")
    assert response.status_code in [200, 204]
    print("✅ Deleted project")

    # Verify deletion
    response = await AC.get(f"/api/v1/projects/{project_id}")
    assert response.status_code in [403, 404]
    print("\n✅ All Project Integration Tests Passed!")
