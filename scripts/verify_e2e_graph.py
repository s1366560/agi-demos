"""Verify authenticated FastAPI-to-Neo4j graph mutation and query behavior."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Mapping
from typing import cast
from urllib.parse import quote

import httpx

E2E_GRAPH_CONTENT = "Ariadne Vale founded Deterministic Graph Labs."
E2E_PERSON = "Ariadne Vale"
E2E_ORGANIZATION = "Deterministic Graph Labs"


def _require_mapping(payload: object, description: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"Graph E2E did not return {description}")
    return cast("Mapping[str, object]", payload)


def _require_string(payload: Mapping[str, object], key: str, description: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Graph E2E did not return {description}")
    return value


def verify_episode(
    payload: object,
    *,
    episode_id: str,
    episode_name: str,
    content: str,
    project_id: str,
) -> None:
    """Fail unless an episode completed processing in the expected project."""
    episode = _require_mapping(payload, "an episode object")
    expected = {
        "uuid": episode_id,
        "name": episode_name,
        "content": content,
        "project_id": project_id,
        "status": "Synced",
    }
    if any(episode.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Graph E2E episode did not round-trip as a synced project record")


def verify_entities(payload: object, *, project_id: str) -> dict[str, str]:
    """Return the two expected entity IDs after validating type and scope."""
    page = _require_mapping(payload, "an entities page")
    raw_entities = page.get("entities")
    if not isinstance(raw_entities, list):
        raise RuntimeError("Graph E2E entities response did not contain a list")

    expected_types = {E2E_PERSON: "Person", E2E_ORGANIZATION: "Organization"}
    entity_ids: dict[str, str] = {}
    for raw_entity in cast("list[object]", raw_entities):
        if not isinstance(raw_entity, Mapping):
            continue
        entity = cast("Mapping[str, object]", raw_entity)
        name = entity.get("name")
        if not isinstance(name, str) or name not in expected_types:
            continue
        if (
            entity.get("entity_type") != expected_types[name]
            or entity.get("project_id") != project_id
        ):
            raise RuntimeError("Graph E2E entities did not preserve type and project scope")
        entity_ids[name] = _require_string(entity, "uuid", "an entity id")

    if set(entity_ids) != set(expected_types):
        raise RuntimeError("Graph E2E entities did not contain both deterministic entities")
    return entity_ids


def verify_relationships(payload: object, *, organization_id: str) -> None:
    """Fail unless the deterministic FOUNDED relationship is queryable."""
    page = _require_mapping(payload, "a relationships page")
    raw_relationships = page.get("relationships")
    if not isinstance(raw_relationships, list):
        raise RuntimeError("Graph E2E relationships response did not contain a list")

    for raw_relationship in cast("list[object]", raw_relationships):
        if not isinstance(raw_relationship, Mapping):
            continue
        relationship = cast("Mapping[str, object]", raw_relationship)
        related = relationship.get("related_entity")
        if not isinstance(related, Mapping):
            continue
        related_entity = cast("Mapping[str, object]", related)
        if (
            relationship.get("relation_type") == "FOUNDED"
            and relationship.get("direction") == "outgoing"
            and relationship.get("fact") == E2E_GRAPH_CONTENT
            and related_entity.get("uuid") == organization_id
            and related_entity.get("name") == E2E_ORGANIZATION
        ):
            return
    raise RuntimeError("Graph E2E relationship did not preserve the deterministic fact")


def verify_search(payload: object) -> None:
    """Fail unless authenticated memory search returns the person entity."""
    page = _require_mapping(payload, "a search page")
    raw_results = page.get("results")
    if not isinstance(raw_results, list):
        raise RuntimeError("Graph E2E search response did not contain results")
    for raw_result in cast("list[object]", raw_results):
        if not isinstance(raw_result, Mapping):
            continue
        result = cast("Mapping[str, object]", raw_result)
        if result.get("type") == "entity" and result.get("name") == E2E_PERSON:
            return
    raise RuntimeError("Graph E2E search did not return the deterministic entity")


def verify_search_modes(payload: object, *, expected_entity_id: str) -> None:
    """Fail unless fulltext, vector, and fused hybrid paths found one entity."""
    evidence = _require_mapping(payload, "search-mode evidence")
    for mode, expected_type in (("fulltext", "keyword"), ("vector", "vector")):
        raw_items = evidence.get(mode)
        if not isinstance(raw_items, list):
            raise RuntimeError(f"Graph E2E {mode} search evidence was invalid")
        if not any(
            isinstance(raw_item, Mapping)
            and raw_item.get("uuid") == expected_entity_id
            and raw_item.get("search_type") == expected_type
            for raw_item in cast("list[object]", raw_items)
        ):
            raise RuntimeError(f"Graph E2E {mode} search did not return the deterministic entity")

    hybrid = _require_mapping(evidence.get("hybrid"), "hybrid search evidence")
    raw_hybrid_items = hybrid.get("items")
    if not isinstance(raw_hybrid_items, list) or not any(
        isinstance(raw_item, Mapping) and raw_item.get("uuid") == expected_entity_id
        for raw_item in cast("list[object]", raw_hybrid_items)
    ):
        raise RuntimeError("Graph E2E hybrid search did not return the deterministic entity")
    vector_count = hybrid.get("vector_results_count")
    keyword_count = hybrid.get("keyword_results_count")
    if (
        not isinstance(vector_count, int)
        or vector_count < 1
        or not isinstance(keyword_count, int)
        or keyword_count < 1
    ):
        raise RuntimeError("Graph E2E hybrid search did not exercise vector and fulltext fusion")


def verify_backend_capability(payload: object, *, available: bool) -> None:
    """Fail unless graph runtime availability uses the stable degradation contract."""
    capabilities = _require_mapping(payload, "search capabilities")
    backend = _require_mapping(capabilities.get("graph_backend"), "graph backend capability")
    expected = (
        {
            "status": "available",
            "reason_code": None,
            "retryable": False,
            "allowed_actions": ["search", "traverse", "rebuild_communities"],
        }
        if available
        else {
            "status": "degraded",
            "reason_code": "graph_backend_unavailable",
            "retryable": True,
            "allowed_actions": ["retry"],
        }
    )
    if any(backend.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Graph E2E backend capability did not preserve the stable contract")


def verify_communities(payload: object, *, project_id: str) -> str:
    """Return the rebuilt community ID after validating scope and membership."""
    page = _require_mapping(payload, "a communities page")
    raw_communities = page.get("communities")
    if not isinstance(raw_communities, list):
        raise RuntimeError("Graph E2E communities response did not contain a list")
    for raw_community in cast("list[object]", raw_communities):
        if not isinstance(raw_community, Mapping):
            continue
        community = cast("Mapping[str, object]", raw_community)
        member_count = community.get("member_count")
        if community.get("project_id") == project_id and isinstance(member_count, int):
            if member_count < 2:
                raise RuntimeError("Graph E2E community did not preserve its entity membership")
            return _require_string(community, "uuid", "a community id")
    raise RuntimeError("Graph E2E community did not preserve project scope")


def verify_background_community_job(payload: object, *, task_id: str) -> None:
    """Fail unless the tracked community rebuild workflow completed successfully."""
    task = _require_mapping(payload, "a background community rebuild task")
    if (
        task.get("id") != task_id
        or task.get("name") != "rebuild_communities"
        or task.get("status") != "Completed"
        or not isinstance(task.get("completed_at"), str)
        or task.get("error") is not None
    ):
        raise RuntimeError("Graph E2E background community rebuild did not complete")


def verify_graph_traversal(payload: object, *, expected_entity_id: str) -> None:
    """Fail unless traversal reaches the deterministic related entity."""
    page = _require_mapping(payload, "a graph traversal page")
    if page.get("search_type") != "graph_traversal":
        raise RuntimeError("Graph E2E traversal did not preserve its search type")
    raw_results = page.get("results")
    if not isinstance(raw_results, list):
        raise RuntimeError("Graph E2E traversal response did not contain results")
    if not any(
        isinstance(raw_result, Mapping) and raw_result.get("uuid") == expected_entity_id
        for raw_result in cast("list[object]", raw_results)
    ):
        raise RuntimeError("Graph E2E traversal did not return the related entity")


def verify_community_search(payload: object, *, person_id: str, episode_id: str) -> None:
    """Fail unless community search returns both its entity and source episode."""
    page = _require_mapping(payload, "a community search page")
    if page.get("search_type") != "community":
        raise RuntimeError("Graph E2E community search did not preserve its search type")
    raw_results = page.get("results")
    if not isinstance(raw_results, list):
        raise RuntimeError("Graph E2E community search response did not contain results")
    result_pairs = {
        (raw_result.get("uuid"), raw_result.get("type"))
        for raw_result in cast("list[object]", raw_results)
        if isinstance(raw_result, Mapping)
    }
    if not {(person_id, "entity"), (episode_id, "episode")} <= result_pairs:
        raise RuntimeError("Graph E2E community search did not return entity and episode results")


def verify_graph(
    payload: object,
    *,
    episode_id: str,
    person_id: str,
    organization_id: str,
) -> None:
    """Fail unless visualization exposes the episode, entities, and graph edges."""
    graph = _require_mapping(payload, "a graph response")
    elements = _require_mapping(graph.get("elements"), "graph elements")
    raw_nodes = elements.get("nodes")
    raw_edges = elements.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise RuntimeError("Graph E2E visualization did not contain nodes and edges")

    element_ids_by_uuid: dict[str, str] = {}
    for raw_node in cast("list[object]", raw_nodes):
        if not isinstance(raw_node, Mapping):
            continue
        raw_data = cast("Mapping[str, object]", raw_node).get("data")
        if isinstance(raw_data, Mapping):
            data = cast("Mapping[str, object]", raw_data)
            node_uuid = data.get("uuid")
            element_id = data.get("id")
            if isinstance(node_uuid, str) and isinstance(element_id, str):
                element_ids_by_uuid[node_uuid] = element_id
    if not {episode_id, person_id, organization_id} <= set(element_ids_by_uuid):
        raise RuntimeError("Graph E2E visualization did not contain all deterministic nodes")

    edge_triples: set[tuple[object, object, object]] = set()
    for raw_edge in cast("list[object]", raw_edges):
        if not isinstance(raw_edge, Mapping):
            continue
        raw_data = cast("Mapping[str, object]", raw_edge).get("data")
        if not isinstance(raw_data, Mapping):
            continue
        data = cast("Mapping[str, object]", raw_data)
        edge_triples.add((data.get("source"), data.get("target"), data.get("label")))
    required_edges = {
        (element_ids_by_uuid[episode_id], element_ids_by_uuid[person_id], "MENTIONS"),
        (
            element_ids_by_uuid[episode_id],
            element_ids_by_uuid[organization_id],
            "MENTIONS",
        ),
        (element_ids_by_uuid[person_id], element_ids_by_uuid[organization_id], "FOUNDED"),
    }
    if not required_edges <= edge_triples:
        raise RuntimeError("Graph E2E visualization did not contain all deterministic edges")


def verify_fixture_usage(before: object, after: object) -> None:
    """Prove graph ingestion used both deterministic chat and embedding APIs."""
    prior = _require_mapping(before, "fixture stats before graph ingestion")
    current = _require_mapping(after, "fixture stats after graph ingestion")
    prior_chat = prior.get("chat_requests")
    current_chat = current.get("chat_requests")
    prior_embedding = prior.get("embedding_requests")
    current_embedding = current.get("embedding_requests")
    if (
        not isinstance(prior_chat, int)
        or not isinstance(current_chat, int)
        or current_chat <= prior_chat
    ):
        raise RuntimeError("Graph E2E did not exercise deterministic chat extraction")
    if (
        not isinstance(prior_embedding, int)
        or not isinstance(current_embedding, int)
        or current_embedding <= prior_embedding
    ):
        raise RuntimeError("Graph E2E did not exercise deterministic embedding generation")


def verify_agent_memory_recall(payload: object) -> None:
    """Fail unless the production memory runtime emitted recalled graph context."""
    result = _require_mapping(payload, "an Agent memory recall result")
    memory_context = result.get("memory_context")
    if not isinstance(memory_context, str) or not (
        E2E_PERSON in memory_context or E2E_ORGANIZATION in memory_context
    ):
        raise RuntimeError("Graph E2E Agent recall did not inject deterministic memory context")

    raw_events = result.get("emitted_events")
    if not isinstance(raw_events, list):
        raise RuntimeError("Graph E2E Agent recall event list was invalid")
    for raw_event in cast("list[object]", raw_events):
        if not isinstance(raw_event, Mapping) or raw_event.get("type") != "memory_recalled":
            continue
        event = cast("Mapping[str, object]", raw_event)
        data = event.get("data")
        if not isinstance(data, Mapping):
            continue
        event_data = cast("Mapping[str, object]", data)
        count = event_data.get("count")
        memories = event_data.get("memories")
        if (
            isinstance(count, int)
            and count > 0
            and isinstance(memories, list)
            and any(
                isinstance(memory, Mapping) and memory.get("source") == "knowledge_graph"
                for memory in cast("list[object]", memories)
            )
        ):
            return
    raise RuntimeError("Graph E2E Agent recall event did not bind knowledge-graph results")


def verify_stale_community_cleanup(
    before: object,
    after: object,
    *,
    stale_community_id: str,
    project_id: str,
) -> None:
    """Fail unless a seeded project-scoped orphan community was actually deleted."""
    seeded = _require_mapping(before, "a seeded stale community")
    if (
        seeded.get("uuid") != stale_community_id
        or seeded.get("project_id") != project_id
        or seeded.get("member_count") != 0
    ):
        raise RuntimeError("Graph E2E stale community precondition was not preserved")
    if after is not None:
        raise RuntimeError("Graph E2E stale community survived the rebuild cleanup")


def verify_project_graph_cleanup(
    payload: object,
    *,
    primary_project_id: str | None,
) -> None:
    """Fail unless direct E2E graph cleanup removed every project-scoped node."""
    projects = _require_mapping(payload, "project graph cleanup evidence")
    for project_id, raw_result in projects.items():
        result = _require_mapping(raw_result, f"graph cleanup evidence for project {project_id}")
        deleted = result.get("deleted")
        remaining = result.get("remaining")
        if not isinstance(deleted, int) or deleted < 0 or not isinstance(remaining, int):
            raise RuntimeError("Graph E2E project cleanup evidence was invalid")
        if remaining != 0:
            raise RuntimeError("Graph E2E project-scoped nodes survived cleanup")

    if primary_project_id is not None:
        primary = _require_mapping(
            projects.get(primary_project_id),
            "primary project graph cleanup evidence",
        )
        deleted = primary.get("deleted")
        if not isinstance(deleted, int) or deleted < 1:
            raise RuntimeError("Graph E2E primary project cleanup did not delete graph data")


def verify_tenant_graph_isolation(
    payload: object,
    *,
    expected_entity_ids: set[str],
    primary_tenant_id: str,
    primary_project_id: str,
    secondary_tenant_id: str,
    secondary_project_id: str,
) -> None:
    """Fail unless tenant and project filters prevent every cross-scope graph leak."""
    evidence = _require_mapping(payload, "tenant graph isolation evidence")
    primary = _require_mapping(evidence.get("primary_tenant"), "primary tenant entities")
    raw_primary_entities = primary.get("entities")
    if not isinstance(raw_primary_entities, list):
        raise RuntimeError("Graph E2E primary tenant entities were invalid")

    primary_entity_ids: set[str] = set()
    for raw_entity in cast("list[object]", raw_primary_entities):
        entity = _require_mapping(raw_entity, "a primary tenant entity")
        if (
            entity.get("tenant_id") != primary_tenant_id
            or entity.get("project_id") != primary_project_id
        ):
            raise RuntimeError("Graph E2E primary tenant response crossed graph scope")
        primary_entity_ids.add(_require_string(entity, "uuid", "a primary tenant entity id"))
    if not expected_entity_ids <= primary_entity_ids:
        raise RuntimeError("Graph E2E primary tenant did not expose the deterministic entities")

    for scope_name, expected_id in (
        ("secondary_tenant", secondary_tenant_id),
        ("secondary_project", secondary_project_id),
    ):
        page = _require_mapping(evidence.get(scope_name), f"{scope_name} entities")
        if page.get("entities") != [] or page.get("total") != 0:
            scope_label = "tenant" if scope_name == "secondary_tenant" else "project"
            raise RuntimeError(
                f"Graph E2E leaked primary entities into the secondary {scope_label} {expected_id}"
            )

    mismatch = _require_mapping(evidence.get("cross_scope"), "tenant/project scope mismatch")
    if (
        mismatch.get("status_code") != 400
        or mismatch.get("detail") != "Project does not belong to tenant"
    ):
        raise RuntimeError("Graph E2E tenant/project scope mismatch was not rejected")


async def _verify_agent_memory_and_seed_stale_community(
    *,
    project_id: str,
    tenant_id: str,
) -> tuple[str, Mapping[str, object]]:
    """Exercise DefaultMemoryRuntime against Neo4j and seed one cleanup sentinel."""
    from src.configuration.factories import create_native_graph_adapter
    from src.infrastructure.agent.memory.runtime import DefaultMemoryRuntime

    graph_service = await create_native_graph_adapter(tenant_id=tenant_id)
    stale_community_id = f"stale-community-{uuid.uuid4().hex}"
    try:
        runtime = DefaultMemoryRuntime(
            llm_client=None,
            graph_service=graph_service,
            session_factory=None,
            redis_client=None,
        )
        recall = await runtime.recall_for_prompt(
            user_message=f"What organization did {E2E_PERSON} found?",
            project_id=project_id,
        )
        verify_agent_memory_recall(
            {
                "memory_context": recall.memory_context,
                "emitted_events": recall.emitted_events,
            }
        )

        seeded = await graph_service.client.execute_query(
            """
            CREATE (c:Community {
                uuid: $uuid,
                name: 'Stale Graph E2E Community',
                summary: 'Orphan sentinel for cleanup verification',
                member_count: 0,
                tenant_id: $tenant_id,
                project_id: $project_id,
                created_at: datetime()
            })
            RETURN c {
                .uuid,
                .project_id,
                member_count: coalesce(c.member_count, 0)
            } AS community
            """,
            uuid=stale_community_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if not seeded.records:
            raise RuntimeError("Graph E2E did not seed a stale community")
        raw_community = seeded.records[0]["community"]
        return stale_community_id, _require_mapping(
            cast("object", raw_community),
            "a seeded stale community",
        )
    finally:
        await graph_service.close()


async def _load_community(community_id: str) -> Mapping[str, object] | None:
    """Load one community directly from the configured Neo4j runtime."""
    from src.configuration.config import get_settings
    from src.infrastructure.graph.neo4j_client import Neo4jClient

    settings = get_settings()
    async with Neo4jClient(
        uri=settings.effective_graph_store_uri,
        user=settings.effective_graph_store_user,
        password=settings.effective_graph_store_password,
    ) as client:
        result = await client.execute_query(
            """
            MATCH (c:Community {uuid: $uuid})
            RETURN c {
                .uuid,
                .project_id,
                member_count: coalesce(c.member_count, 0)
            } AS community
            """,
            uuid=community_id,
        )
        if not result.records:
            return None
        return _require_mapping(cast("object", result.records[0]["community"]), "a community")


async def _cleanup_project_graph(
    project_ids: tuple[str, ...],
    *,
    primary_project_id: str | None,
) -> None:
    """Delete and verify only graph data owned by this verifier's temporary projects."""
    from src.configuration.factories import create_native_graph_adapter

    graph_service = await create_native_graph_adapter()
    try:
        evidence: dict[str, dict[str, int]] = {}
        for project_id in project_ids:
            deleted = await graph_service.delete_project(project_id)
            remaining = await graph_service.count_nodes(project_id=project_id)
            evidence[project_id] = {"deleted": deleted, "remaining": remaining}
        verify_project_graph_cleanup(evidence, primary_project_id=primary_project_id)
    finally:
        await graph_service.close()


async def _cleanup_e2e_fixture(
    client: httpx.Client,
    base: str,
    headers: Mapping[str, str],
    *,
    episode_name: str,
    episode_id: str | None,
    project_id: str,
    isolation_project_id: str | None,
    secondary_tenant_id: str | None,
    secondary_project_id: str | None,
    primary_graph_created: bool,
) -> None:
    """Remove HTTP and graph resources created by one verifier invocation."""
    failures: list[Exception] = []
    if episode_id is not None:
        try:
            episode_cleanup = client.delete(
                f"{base}/api/v1/episodes/by-name/{quote(episode_name, safe='')}",
                headers=headers,
            )
            _ = episode_cleanup.raise_for_status()
        except Exception as error:
            failures.append(error)

    project_ids = tuple(
        candidate
        for candidate in (project_id, isolation_project_id, secondary_project_id)
        if candidate is not None
    )
    try:
        await _cleanup_project_graph(
            project_ids,
            primary_project_id=project_id if primary_graph_created else None,
        )
    except Exception as error:
        failures.append(error)

    for cleanup_project_id in project_ids:
        try:
            project_cleanup = client.delete(
                f"{base}/api/v1/projects/{cleanup_project_id}",
                headers=headers,
            )
            _ = project_cleanup.raise_for_status()
        except Exception as error:
            failures.append(error)

    if secondary_tenant_id is not None:
        try:
            tenant_cleanup = client.delete(
                f"{base}/api/v1/tenants/{secondary_tenant_id}",
                headers=headers,
            )
            _ = tenant_cleanup.raise_for_status()
        except Exception as error:
            failures.append(error)

    if failures:
        raise RuntimeError(
            f"Graph E2E cleanup failed for {len(failures)} owned resource operation(s)"
        ) from failures[0]


def _authenticate(
    client: httpx.Client,
    api_base: str,
    *,
    username: str,
    password: str,
) -> str:
    auth = client.post(
        f"{api_base}/api/v1/auth/token",
        data={"username": username, "password": password},
    )
    _ = auth.raise_for_status()
    return _require_string(
        _require_mapping(cast("object", auth.json()), "an authentication object"),
        "access_token",
        "an access token",
    )


def _create_project(
    client: httpx.Client,
    api_base: str,
    headers: Mapping[str, str],
    tenant_id: str,
    *,
    description: str,
) -> str:
    project = client.post(
        f"{api_base}/api/v1/projects/",
        headers=headers,
        json={
            "name": f"Graph E2E {uuid.uuid4().hex[:8]}",
            "description": description,
            "tenant_id": tenant_id,
        },
    )
    _ = project.raise_for_status()
    return _require_string(
        _require_mapping(cast("object", project.json()), "a project object"),
        "id",
        "a project id",
    )


def _create_tenant(
    client: httpx.Client,
    api_base: str,
    headers: Mapping[str, str],
) -> str:
    tenant = client.post(
        f"{api_base}/api/v1/tenants/",
        headers=headers,
        json={
            "name": f"Graph E2E Tenant {uuid.uuid4().hex[:8]}",
            "description": "Deterministic cross-tenant graph isolation fixture",
        },
    )
    _ = tenant.raise_for_status()
    return _require_string(
        _require_mapping(cast("object", tenant.json()), "a tenant object"),
        "id",
        "a tenant id",
    )


def _create_isolation_scope(
    client: httpx.Client,
    api_base: str,
    headers: Mapping[str, str],
    *,
    primary_tenant_id: str,
    owned_scope: dict[str, str | None],
) -> tuple[str, str, str]:
    """Create both isolation projects while retaining partial cleanup ownership."""
    isolation_project_id = _create_project(
        client,
        api_base,
        headers,
        primary_tenant_id,
        description="Graph E2E project-isolation fixture",
    )
    owned_scope["isolation_project_id"] = isolation_project_id
    secondary_tenant_id = _create_tenant(client, api_base, headers)
    owned_scope["secondary_tenant_id"] = secondary_tenant_id
    secondary_project_id = _create_project(
        client,
        api_base,
        headers,
        secondary_tenant_id,
        description="Graph E2E cross-tenant isolation fixture",
    )
    owned_scope["secondary_project_id"] = secondary_project_id
    return isolation_project_id, secondary_tenant_id, secondary_project_id


def _authenticate_and_create_project(client: httpx.Client, api_base: str) -> tuple[str, str, str]:
    token = _authenticate(
        client,
        api_base,
        username="admin@memstack.ai",
        password="adminpassword",
    )
    headers = {"Authorization": f"Bearer {token}"}
    tenants = client.get(f"{api_base}/api/v1/tenants/", headers=headers)
    _ = tenants.raise_for_status()
    tenant_payload = cast("object", tenants.json())
    if isinstance(tenant_payload, Mapping):
        tenant_payload = cast("Mapping[str, object]", tenant_payload).get("tenants")
    if not isinstance(tenant_payload, list) or not tenant_payload:
        raise RuntimeError("Graph E2E did not return a tenant")
    tenant_id = _require_string(
        _require_mapping(cast("object", tenant_payload[0]), "a tenant object"),
        "id",
        "a tenant id",
    )
    project_id = _create_project(
        client,
        api_base,
        headers,
        tenant_id,
        description="Deterministic FastAPI-to-Neo4j E2E fixture",
    )
    return token, tenant_id, project_id


def _wait_for_synced_episode(
    client: httpx.Client,
    api_base: str,
    headers: Mapping[str, str],
    episode_name: str,
    *,
    timeout_seconds: float = 20.0,
) -> Mapping[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_episode: Mapping[str, object] | None = None
    path_name = quote(episode_name, safe="")
    while time.monotonic() < deadline:
        response = client.get(f"{api_base}/api/v1/episodes/by-name/{path_name}", headers=headers)
        _ = response.raise_for_status()
        raw_payload = cast("object", response.json())
        if isinstance(raw_payload, Mapping):
            episode = cast("Mapping[str, object]", raw_payload)
            last_episode = episode
            if episode.get("status") == "Synced":
                return episode
        time.sleep(0.25)
    if last_episode is None:
        raise RuntimeError("Graph E2E episode lookup did not return an object")
    return last_episode


async def _verify_community_and_traversal(
    client: httpx.Client,
    base: str,
    headers: Mapping[str, str],
    *,
    project_id: str,
    episode_id: str,
    entity_ids: Mapping[str, str],
    stale_community_id: str,
    stale_community_before: Mapping[str, object],
) -> None:
    rebuild_response = client.post(
        f"{base}/api/v1/graph/communities/rebuild",
        headers=headers,
        params={"project_id": project_id, "background": "false"},
    )
    _ = rebuild_response.raise_for_status()
    rebuild = _require_mapping(
        cast("object", rebuild_response.json()), "a community rebuild result"
    )
    if (
        rebuild.get("status") != "success"
        or rebuild.get("entities_processed") != 2
        or not isinstance(rebuild.get("communities_count"), int)
        or cast("int", rebuild["communities_count"]) < 1
    ):
        raise RuntimeError("Graph E2E community rebuild did not process the fixture")

    communities_response = client.get(
        f"{base}/api/v1/graph/communities/",
        headers=headers,
        params={"project_id": project_id, "limit": 20},
    )
    _ = communities_response.raise_for_status()
    community_id = verify_communities(
        cast("object", communities_response.json()), project_id=project_id
    )

    traversal_response = client.post(
        f"{base}/api/v1/search-enhanced/graph-traversal",
        headers=headers,
        json={
            "start_entity_uuid": entity_ids[E2E_PERSON],
            "max_depth": 2,
            "relationship_types": ["FOUNDED"],
            "limit": 20,
            "project_id": project_id,
        },
    )
    _ = traversal_response.raise_for_status()
    verify_graph_traversal(
        cast("object", traversal_response.json()),
        expected_entity_id=entity_ids[E2E_ORGANIZATION],
    )

    community_search_response = client.post(
        f"{base}/api/v1/search-enhanced/community",
        headers=headers,
        json={
            "community_uuid": community_id,
            "limit": 20,
            "include_episodes": True,
            "project_id": project_id,
        },
    )
    _ = community_search_response.raise_for_status()
    verify_community_search(
        cast("object", community_search_response.json()),
        person_id=entity_ids[E2E_PERSON],
        episode_id=episode_id,
    )
    verify_stale_community_cleanup(
        stale_community_before,
        await _load_community(stale_community_id),
        stale_community_id=stale_community_id,
        project_id=project_id,
    )

    background_response = client.post(
        f"{base}/api/v1/graph/communities/rebuild",
        headers=headers,
        params={"project_id": project_id, "background": "true"},
    )
    _ = background_response.raise_for_status()
    background = _require_mapping(
        cast("object", background_response.json()),
        "a background community rebuild submission",
    )
    if background.get("status") != "submitted":
        raise RuntimeError("Graph E2E background community rebuild was not submitted")
    task_id = _require_string(background, "task_id", "a background community task id")
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        task_response = client.get(f"{base}/api/v1/tasks/{task_id}", headers=headers)
        _ = task_response.raise_for_status()
        task = _require_mapping(
            cast("object", task_response.json()),
            "a background community rebuild task",
        )
        if task.get("status") in {"Completed", "Failed"}:
            verify_background_community_job(task, task_id=task_id)
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Graph E2E background community rebuild did not reach a final state")


async def _verify_agent_memory_community_and_traversal(
    client: httpx.Client,
    base: str,
    headers: Mapping[str, str],
    *,
    tenant_id: str,
    project_id: str,
    episode_id: str,
    entity_ids: Mapping[str, str],
) -> None:
    """Bind Agent recall, stale cleanup, communities, and traversal in one gate."""
    (
        stale_community_id,
        stale_community_before,
    ) = await _verify_agent_memory_and_seed_stale_community(
        project_id=project_id, tenant_id=tenant_id
    )
    await _verify_community_and_traversal(
        client,
        base,
        headers,
        project_id=project_id,
        episode_id=episode_id,
        entity_ids=entity_ids,
        stale_community_id=stale_community_id,
        stale_community_before=stale_community_before,
    )


async def _verify_search_modes(*, project_id: str, expected_entity_id: str) -> None:
    """Exercise Neo4j fulltext, vector, and hybrid search as separate paths."""
    from src.configuration.factories import create_native_graph_adapter

    graph_service = await create_native_graph_adapter()
    try:
        hybrid_search = graph_service._get_hybrid_search()
        fulltext = await hybrid_search.keyword_search(
            E2E_PERSON,
            project_id=project_id,
            limit=20,
        )
        vector = await hybrid_search.vector_search(
            E2E_PERSON,
            project_id=project_id,
            limit=20,
        )
        hybrid = await hybrid_search.search(
            E2E_PERSON,
            project_id=project_id,
            limit=20,
        )
        verify_search_modes(
            {
                "fulltext": [
                    {
                        "uuid": item.uuid,
                        "name": item.name,
                        "search_type": item.metadata.get("search_type"),
                    }
                    for item in fulltext
                ],
                "vector": [
                    {
                        "uuid": item.uuid,
                        "name": item.name,
                        "search_type": item.metadata.get("search_type"),
                    }
                    for item in vector
                ],
                "hybrid": {
                    "items": [{"uuid": item.uuid, "name": item.name} for item in hybrid.items],
                    "vector_results_count": hybrid.vector_results_count,
                    "keyword_results_count": hybrid.keyword_results_count,
                },
            },
            expected_entity_id=expected_entity_id,
        )
    finally:
        await graph_service.close()


def _verify_project_and_member_isolation(
    client: httpx.Client,
    base: str,
    admin_headers: Mapping[str, str],
    *,
    primary_tenant_id: str,
    project_id: str,
    isolation_project_id: str,
    secondary_tenant_id: str,
    secondary_project_id: str,
    expected_entity_ids: set[str],
) -> None:
    isolated = client.get(
        f"{base}/api/v1/graph/entities/",
        headers=admin_headers,
        params={"project_id": isolation_project_id, "limit": 20},
    )
    _ = isolated.raise_for_status()
    isolated_page = _require_mapping(cast("object", isolated.json()), "an isolated entities page")
    if isolated_page.get("entities") != [] or isolated_page.get("total") != 0:
        raise RuntimeError("Graph E2E leaked entities across project scope")

    tenant_evidence: dict[str, object] = {}
    for evidence_name, params in (
        (
            "primary_tenant",
            {"tenant_id": primary_tenant_id, "limit": 20},
        ),
        (
            "secondary_tenant",
            {"tenant_id": secondary_tenant_id, "limit": 20},
        ),
        (
            "secondary_project",
            {
                "tenant_id": secondary_tenant_id,
                "project_id": secondary_project_id,
                "limit": 20,
            },
        ),
    ):
        response = client.get(
            f"{base}/api/v1/graph/entities/",
            headers=admin_headers,
            params=params,
        )
        _ = response.raise_for_status()
        tenant_evidence[evidence_name] = cast("object", response.json())

    mismatch = client.get(
        f"{base}/api/v1/graph/entities/",
        headers=admin_headers,
        params={
            "tenant_id": secondary_tenant_id,
            "project_id": project_id,
            "limit": 20,
        },
    )
    mismatch_payload = _require_mapping(
        cast("object", mismatch.json()),
        "tenant/project scope mismatch response",
    )
    tenant_evidence["cross_scope"] = {
        "status_code": mismatch.status_code,
        "detail": mismatch_payload.get("detail"),
    }
    verify_tenant_graph_isolation(
        tenant_evidence,
        expected_entity_ids=expected_entity_ids,
        primary_tenant_id=primary_tenant_id,
        primary_project_id=project_id,
        secondary_tenant_id=secondary_tenant_id,
        secondary_project_id=secondary_project_id,
    )

    member_token = _authenticate(
        client,
        base,
        username="user@memstack.ai",
        password="userpassword",
    )
    denied = client.get(
        f"{base}/api/v1/graph/entities/",
        headers={"Authorization": f"Bearer {member_token}"},
        params={"project_id": project_id, "limit": 20},
    )
    if denied.status_code != 403:
        raise RuntimeError("Graph E2E member without project scope was not denied")


async def _verify_e2e_graph(api_base: str, fixture_base: str) -> None:
    """Create, query, and clean up one authenticated deterministic graph fixture."""
    base, fixture = api_base.rstrip("/"), fixture_base.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        token, tenant_id, project_id = _authenticate_and_create_project(client, base)
        headers = {"Authorization": f"Bearer {token}"}
        isolation_scope: dict[str, str | None] = {
            "isolation_project_id": None,
            "secondary_tenant_id": None,
            "secondary_project_id": None,
        }
        episode_name = f"graph-e2e-{uuid.uuid4().hex}"
        episode_id: str | None = None
        primary_graph_created = False
        try:
            isolation_project_id, secondary_tenant_id, secondary_project_id = (
                _create_isolation_scope(
                    client,
                    base,
                    headers,
                    primary_tenant_id=tenant_id,
                    owned_scope=isolation_scope,
                )
            )
            capability_response = client.get(
                f"{base}/api/v1/search-enhanced/capabilities",
                headers=headers,
            )
            _ = capability_response.raise_for_status()
            verify_backend_capability(cast("object", capability_response.json()), available=True)

            before_stats_response = client.get(f"{fixture}/_e2e/stats")
            _ = before_stats_response.raise_for_status()
            before_stats = cast("object", before_stats_response.json())
            anonymous = client.post(
                f"{base}/api/v1/episodes/",
                json={"name": episode_name, "content": E2E_GRAPH_CONTENT, "project_id": project_id},
            )
            if anonymous.status_code != 401:
                raise RuntimeError("Graph E2E anonymous episode creation was not rejected")

            created = client.post(
                f"{base}/api/v1/episodes/",
                headers=headers,
                json={"name": episode_name, "content": E2E_GRAPH_CONTENT, "project_id": project_id},
            )
            _ = created.raise_for_status()
            if created.status_code != 202:
                raise RuntimeError("Graph E2E episode creation did not preserve the 202 contract")
            episode_id = _require_string(
                _require_mapping(cast("object", created.json()), "an episode creation object"),
                "id",
                "an episode id",
            )
            episode_payload = _wait_for_synced_episode(client, base, headers, episode_name)
            verify_episode(
                episode_payload,
                episode_id=episode_id,
                episode_name=episode_name,
                content=E2E_GRAPH_CONTENT,
                project_id=project_id,
            )

            entities_response = client.get(
                f"{base}/api/v1/graph/entities/",
                headers=headers,
                params={"project_id": project_id, "limit": 20},
            )
            _ = entities_response.raise_for_status()
            entity_ids = verify_entities(
                cast("object", entities_response.json()), project_id=project_id
            )
            primary_graph_created = True
            relationships_response = client.get(
                f"{base}/api/v1/graph/entities/{entity_ids[E2E_PERSON]}/relationships",
                headers=headers,
            )
            _ = relationships_response.raise_for_status()
            verify_relationships(
                cast("object", relationships_response.json()),
                organization_id=entity_ids[E2E_ORGANIZATION],
            )

            search_response = client.post(
                f"{base}/api/v1/memory/search",
                headers=headers,
                json={"query": E2E_PERSON, "project_id": project_id, "limit": 20},
            )
            _ = search_response.raise_for_status()
            verify_search(cast("object", search_response.json()))
            await _verify_search_modes(
                project_id=project_id,
                expected_entity_id=entity_ids[E2E_PERSON],
            )

            graph_response = client.get(
                f"{base}/api/v1/graph/memory/graph",
                headers=headers,
                params={"project_id": project_id, "limit": 50},
            )
            _ = graph_response.raise_for_status()
            verify_graph(
                cast("object", graph_response.json()),
                episode_id=episode_id,
                person_id=entity_ids[E2E_PERSON],
                organization_id=entity_ids[E2E_ORGANIZATION],
            )

            await _verify_agent_memory_community_and_traversal(
                client,
                base,
                headers,
                tenant_id=tenant_id,
                project_id=project_id,
                episode_id=episode_id,
                entity_ids=entity_ids,
            )
            _verify_project_and_member_isolation(
                client,
                base,
                headers,
                primary_tenant_id=tenant_id,
                project_id=project_id,
                isolation_project_id=isolation_project_id,
                secondary_tenant_id=secondary_tenant_id,
                secondary_project_id=secondary_project_id,
                expected_entity_ids=set(entity_ids.values()),
            )

            after_stats_response = client.get(f"{fixture}/_e2e/stats")
            _ = after_stats_response.raise_for_status()
            after_stats = cast("object", after_stats_response.json())
            verify_fixture_usage(before_stats, after_stats)
        finally:
            await _cleanup_e2e_fixture(
                client,
                base,
                headers,
                episode_name=episode_name,
                episode_id=episode_id,
                project_id=project_id,
                isolation_project_id=isolation_scope["isolation_project_id"],
                secondary_tenant_id=isolation_scope["secondary_tenant_id"],
                secondary_project_id=isolation_scope["secondary_project_id"],
                primary_graph_created=primary_graph_created,
            )


def verify_e2e_graph(api_base: str, fixture_base: str) -> None:
    """Run the complete verifier under one event loop for async pool safety."""
    asyncio.run(_verify_e2e_graph(api_base, fixture_base))


if __name__ == "__main__":
    openai_base = os.getenv("OPENAI_FIXTURE_BASE") or os.getenv(
        "OPENAI_BASE_URL", "http://127.0.0.1:8010/v1"
    ).removesuffix("/v1")
    verify_e2e_graph(os.getenv("API_BASE", "http://127.0.0.1:8000"), openai_base)
    print("Deterministic FastAPI/Neo4j Graph E2E verified")
