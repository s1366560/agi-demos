"""Verify authenticated FastAPI-to-Neo4j graph mutation and query behavior."""

from __future__ import annotations

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


def _authenticate_and_create_project(client: httpx.Client, api_base: str) -> tuple[str, str]:
    auth = client.post(
        f"{api_base}/api/v1/auth/token",
        data={"username": "admin@memstack.ai", "password": "adminpassword"},
    )
    _ = auth.raise_for_status()
    token = _require_string(
        _require_mapping(cast("object", auth.json()), "an authentication object"),
        "access_token",
        "an access token",
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
    project = client.post(
        f"{api_base}/api/v1/projects/",
        headers=headers,
        json={
            "name": f"Graph E2E {uuid.uuid4().hex[:8]}",
            "description": "Deterministic FastAPI-to-Neo4j E2E fixture",
            "tenant_id": tenant_id,
        },
    )
    _ = project.raise_for_status()
    project_id = _require_string(
        _require_mapping(cast("object", project.json()), "a project object"),
        "id",
        "a project id",
    )
    return token, project_id


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


def verify_e2e_graph(api_base: str, fixture_base: str) -> None:
    """Create, query, and clean up one authenticated deterministic graph fixture."""
    base = api_base.rstrip("/")
    fixture = fixture_base.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        token, project_id = _authenticate_and_create_project(client, base)
        headers = {"Authorization": f"Bearer {token}"}
        episode_name = f"graph-e2e-{uuid.uuid4().hex}"
        episode_id: str | None = None
        try:
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
            after_stats_response = client.get(f"{fixture}/_e2e/stats")
            _ = after_stats_response.raise_for_status()
            after_stats = cast("object", after_stats_response.json())
            verify_fixture_usage(before_stats, after_stats)
        finally:
            if episode_id is not None:
                _ = client.delete(
                    f"{base}/api/v1/episodes/by-name/{quote(episode_name, safe='')}",
                    headers=headers,
                )
            _ = client.delete(f"{base}/api/v1/projects/{project_id}", headers=headers)


if __name__ == "__main__":
    openai_base = os.getenv("OPENAI_FIXTURE_BASE") or os.getenv(
        "OPENAI_BASE_URL", "http://127.0.0.1:8010/v1"
    ).removesuffix("/v1")
    verify_e2e_graph(os.getenv("API_BASE", "http://127.0.0.1:8000"), openai_base)
    print("Deterministic FastAPI/Neo4j Graph E2E verified")
