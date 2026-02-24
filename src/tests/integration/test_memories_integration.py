from uuid import uuid4

import pytest


async def _get_or_create_tenant(ac) -> str:
    """Get or create a tenant and return its ID."""
    print("\n1. Getting Tenant...")
    tenant_response = await ac.post(
        "/api/v1/tenants/",
        json={
            "name": "Memory Test Tenant",
            "description": "Tenant for memory tests",
            "plan": "free",
        },
    )

    if tenant_response.status_code == 201:
        tenant_id = tenant_response.json()["id"]
        print(f"✅ Created Tenant: {tenant_id}")
        return tenant_id

    if tenant_response.status_code == 400:
        list_response = await ac.get("/api/v1/tenants/")
        if list_response.json()["tenants"]:
            tenant_id = list_response.json()["tenants"][0]["id"]
            print(f"✅ Using existing Tenant: {tenant_id}")
            return tenant_id
        pytest.fail("❌ No tenant available")

    pytest.fail(f"❌ Failed to get tenant: {tenant_response.status_code} - {tenant_response.text}")
    return ""  # unreachable, satisfies type checker


async def _get_or_create_project(ac, tenant_id: str) -> str:
    """Create a project or use an existing one. Returns project ID."""
    print("\n2. Creating Project...")
    project_data = {
        "name": f"Memory Test Project {uuid4().hex[:6]}",
        "description": "Integration Test Project for Memories",
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
        project_id = response.json()["id"]
        print(f"✅ Project Created: {project_id}")
        return project_id

    if response.status_code == 400 and "maximum number of projects" in response.text:
        print("⚠️ Tenant project limit reached, using existing project...")
        list_response = await ac.get(f"/api/v1/projects/?tenant_id={tenant_id}")
        if list_response.status_code == 200 and list_response.json()["projects"]:
            project_id = list_response.json()["projects"][0]["id"]
            print(f"✅ Using Existing Project: {project_id}")
            return project_id
        pytest.fail("❌ Failed to list projects or no projects found")

    pytest.fail(f"❌ Create Project failed: {response.status_code} - {response.text}")
    return ""  # unreachable


async def _create_memory(ac, project_id: str) -> str:
    """Create a test memory and return its ID."""
    print("\n3. Creating Memory...")
    memory_data = {
        "title": "Test Memory",
        "content": "This is a test memory content.",
        "content_type": "text",
        "project_id": project_id,
        "tags": ["test", "integration"],
        "is_public": False,
    }

    response = await ac.post("/api/v1/memories/", json=memory_data)

    if response.status_code == 201:
        memory = response.json()
        print(f"✅ Memory created successfully: {memory['id']}")
        return memory["id"]

    pytest.fail(f"❌ Create Memory failed: {response.status_code} - {response.text}")
    return ""  # unreachable


async def _verify_list_memories(ac, project_id: str) -> None:
    """Verify memories can be listed for the project."""
    print("\n4. Listing Memories...")
    response = await ac.get(f"/api/v1/memories/?project_id={project_id}")
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Listed {data['total']} memories")
        assert data["total"] >= 1
    else:
        pytest.fail(f"❌ List Memories failed: {response.status_code} - {response.text}")


async def _verify_get_memory(ac, memory_id: str) -> None:
    """Verify a memory can be retrieved by ID."""
    print("\n5. Getting Memory...")
    response = await ac.get(f"/api/v1/memories/{memory_id}")
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_flow(authenticated_async_client, test_user):
    AC = authenticated_async_client

    tenant_id = await _get_or_create_tenant(AC)
    print(f"✅ Tenant ID: {tenant_id}")

    project_id = await _get_or_create_project(AC, tenant_id)
    memory_id = await _create_memory(AC, project_id)
    await _verify_list_memories(AC, project_id)
    await _verify_get_memory(AC, memory_id)

    print("\n✅ All Memory Integration Tests Passed!")
