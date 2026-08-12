"""Tests for the real Graph E2E verifier contract."""

import pytest

from scripts.verify_e2e_graph import (
    verify_agent_memory_recall,
    verify_backend_capability,
    verify_background_community_job,
    verify_communities,
    verify_community_search,
    verify_entities,
    verify_episode,
    verify_fixture_usage,
    verify_graph,
    verify_graph_traversal,
    verify_project_graph_cleanup,
    verify_relationships,
    verify_search,
    verify_search_modes,
    verify_stale_community_cleanup,
    verify_tenant_graph_isolation,
)

PROJECT_ID = "project-e2e"
EPISODE_ID = "episode-e2e"
PERSON_ID = "person-e2e"
ORG_ID = "organization-e2e"
PRIMARY_TENANT_ID = "tenant-primary-e2e"
SECONDARY_TENANT_ID = "tenant-secondary-e2e"
SECONDARY_PROJECT_ID = "project-secondary-e2e"


def test_verify_episode_accepts_synced_project_scoped_episode() -> None:
    verify_episode(
        {
            "uuid": EPISODE_ID,
            "name": "graph-e2e",
            "content": "Ariadne Vale founded Deterministic Graph Labs.",
            "project_id": PROJECT_ID,
            "status": "Synced",
        },
        episode_id=EPISODE_ID,
        episode_name="graph-e2e",
        content="Ariadne Vale founded Deterministic Graph Labs.",
        project_id=PROJECT_ID,
    )


@pytest.mark.parametrize("field,value", [("project_id", "other"), ("status", "Processing")])
def test_verify_episode_rejects_wrong_scope_or_incomplete_processing(
    field: str, value: str
) -> None:
    payload = {
        "uuid": EPISODE_ID,
        "name": "graph-e2e",
        "content": "Ariadne Vale founded Deterministic Graph Labs.",
        "project_id": PROJECT_ID,
        "status": "Synced",
    }
    payload[field] = value

    with pytest.raises(RuntimeError, match="episode"):
        verify_episode(
            payload,
            episode_id=EPISODE_ID,
            episode_name="graph-e2e",
            content="Ariadne Vale founded Deterministic Graph Labs.",
            project_id=PROJECT_ID,
        )


def test_verify_entities_and_relationships_accept_expected_graph() -> None:
    entity_ids = verify_entities(
        {
            "entities": [
                {
                    "uuid": PERSON_ID,
                    "name": "Ariadne Vale",
                    "entity_type": "Person",
                    "project_id": PROJECT_ID,
                },
                {
                    "uuid": ORG_ID,
                    "name": "Deterministic Graph Labs",
                    "entity_type": "Organization",
                    "project_id": PROJECT_ID,
                },
            ]
        },
        project_id=PROJECT_ID,
    )
    verify_relationships(
        {
            "relationships": [
                {
                    "relation_type": "FOUNDED",
                    "direction": "outgoing",
                    "fact": "Ariadne Vale founded Deterministic Graph Labs.",
                    "related_entity": {
                        "uuid": ORG_ID,
                        "name": "Deterministic Graph Labs",
                    },
                }
            ]
        },
        organization_id=entity_ids["Deterministic Graph Labs"],
    )


def test_verify_entities_rejects_missing_expected_entity() -> None:
    with pytest.raises(RuntimeError, match="entities"):
        verify_entities({"entities": []}, project_id=PROJECT_ID)


def test_verify_search_and_graph_accept_full_mutation_surface() -> None:
    verify_search({"results": [{"type": "entity", "name": "Ariadne Vale", "uuid": PERSON_ID}]})
    verify_graph(
        {
            "elements": {
                "nodes": [
                    {"data": {"id": "node-episode", "uuid": EPISODE_ID, "name": "graph-e2e"}},
                    {"data": {"id": "node-person", "uuid": PERSON_ID, "name": "Ariadne Vale"}},
                    {
                        "data": {
                            "id": "node-organization",
                            "uuid": ORG_ID,
                            "name": "Deterministic Graph Labs",
                        }
                    },
                ],
                "edges": [
                    {
                        "data": {
                            "source": "node-episode",
                            "target": "node-person",
                            "label": "MENTIONS",
                        }
                    },
                    {
                        "data": {
                            "source": "node-episode",
                            "target": "node-organization",
                            "label": "MENTIONS",
                        }
                    },
                    {
                        "data": {
                            "source": "node-person",
                            "target": "node-organization",
                            "label": "FOUNDED",
                        }
                    },
                ],
            }
        },
        episode_id=EPISODE_ID,
        person_id=PERSON_ID,
        organization_id=ORG_ID,
    )


def test_verify_search_modes_requires_fulltext_vector_and_hybrid_evidence() -> None:
    verify_search_modes(
        {
            "fulltext": [
                {
                    "uuid": PERSON_ID,
                    "name": "Ariadne Vale",
                    "search_type": "keyword",
                }
            ],
            "vector": [
                {
                    "uuid": PERSON_ID,
                    "name": "Ariadne Vale",
                    "search_type": "vector",
                }
            ],
            "hybrid": {
                "items": [{"uuid": PERSON_ID, "name": "Ariadne Vale"}],
                "vector_results_count": 1,
                "keyword_results_count": 2,
            },
        },
        expected_entity_id=PERSON_ID,
    )

    with pytest.raises(RuntimeError, match="vector"):
        verify_search_modes(
            {
                "fulltext": [
                    {
                        "uuid": PERSON_ID,
                        "name": "Ariadne Vale",
                        "search_type": "keyword",
                    }
                ],
                "vector": [],
                "hybrid": {
                    "items": [{"uuid": PERSON_ID, "name": "Ariadne Vale"}],
                    "vector_results_count": 0,
                    "keyword_results_count": 1,
                },
            },
            expected_entity_id=PERSON_ID,
        )


def test_verify_fixture_usage_requires_chat_and_embedding_calls() -> None:
    verify_fixture_usage(
        {"chat_requests": 2, "embedding_requests": 3},
        {"chat_requests": 5, "embedding_requests": 4},
    )

    with pytest.raises(RuntimeError, match="embedding"):
        verify_fixture_usage(
            {"chat_requests": 2, "embedding_requests": 3},
            {"chat_requests": 5, "embedding_requests": 3},
        )


def test_verify_agent_memory_recall_requires_prompt_context_and_structured_event() -> None:
    verify_agent_memory_recall(
        {
            "memory_context": (
                "<relevant_memories>\n"
                "- [entity | graph:person-e2e] Ariadne Vale founded "
                "Deterministic Graph Labs.\n"
                "</relevant_memories>"
            ),
            "emitted_events": [
                {
                    "type": "memory_recalled",
                    "data": {
                        "count": 1,
                        "search_ms": 7,
                        "memories": [
                            {
                                "content": "Ariadne Vale founded Deterministic Graph Labs.",
                                "source": "knowledge_graph",
                            }
                        ],
                    },
                }
            ],
        }
    )

    with pytest.raises(RuntimeError, match="recall event"):
        verify_agent_memory_recall(
            {
                "memory_context": "Ariadne Vale founded Deterministic Graph Labs.",
                "emitted_events": [],
            }
        )


def test_verify_stale_community_cleanup_requires_seeded_node_to_be_deleted() -> None:
    verify_stale_community_cleanup(
        {"uuid": "stale-community-e2e", "project_id": PROJECT_ID, "member_count": 0},
        None,
        stale_community_id="stale-community-e2e",
        project_id=PROJECT_ID,
    )

    with pytest.raises(RuntimeError, match="stale community"):
        verify_stale_community_cleanup(
            {"uuid": "stale-community-e2e", "project_id": PROJECT_ID, "member_count": 0},
            {"uuid": "stale-community-e2e", "project_id": PROJECT_ID, "member_count": 0},
            stale_community_id="stale-community-e2e",
            project_id=PROJECT_ID,
        )


def test_verify_project_graph_cleanup_requires_primary_deletion_and_zero_remaining_nodes() -> None:
    verify_project_graph_cleanup(
        {
            PROJECT_ID: {"deleted": 5, "remaining": 0},
            "isolation-project-e2e": {"deleted": 0, "remaining": 0},
        },
        primary_project_id=PROJECT_ID,
    )

    with pytest.raises(RuntimeError, match="primary project"):
        verify_project_graph_cleanup(
            {PROJECT_ID: {"deleted": 0, "remaining": 0}},
            primary_project_id=PROJECT_ID,
        )

    with pytest.raises(RuntimeError, match="survived cleanup"):
        verify_project_graph_cleanup(
            {PROJECT_ID: {"deleted": 5, "remaining": 1}},
            primary_project_id=PROJECT_ID,
        )


def test_verify_tenant_graph_isolation_accepts_visible_primary_and_empty_secondary_scope() -> None:
    verify_tenant_graph_isolation(
        {
            "primary_tenant": {
                "entities": [
                    {
                        "uuid": PERSON_ID,
                        "project_id": PROJECT_ID,
                        "tenant_id": PRIMARY_TENANT_ID,
                    },
                    {
                        "uuid": ORG_ID,
                        "project_id": PROJECT_ID,
                        "tenant_id": PRIMARY_TENANT_ID,
                    },
                ],
                "total": 2,
            },
            "secondary_tenant": {"entities": [], "total": 0},
            "secondary_project": {"entities": [], "total": 0},
            "cross_scope": {
                "status_code": 400,
                "detail": "Project does not belong to tenant",
            },
        },
        expected_entity_ids={PERSON_ID, ORG_ID},
        primary_tenant_id=PRIMARY_TENANT_ID,
        primary_project_id=PROJECT_ID,
        secondary_tenant_id=SECONDARY_TENANT_ID,
        secondary_project_id=SECONDARY_PROJECT_ID,
    )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("secondary_tenant", {"entities": [{"uuid": PERSON_ID}], "total": 1}, "tenant"),
        ("secondary_project", {"entities": [{"uuid": ORG_ID}], "total": 1}, "project"),
        (
            "cross_scope",
            {"status_code": 200, "detail": None},
            "tenant/project scope mismatch",
        ),
    ],
)
def test_verify_tenant_graph_isolation_rejects_leaks_or_missing_scope_guard(
    field: str,
    value: object,
    error: str,
) -> None:
    payload: dict[str, object] = {
        "primary_tenant": {
            "entities": [
                {
                    "uuid": PERSON_ID,
                    "project_id": PROJECT_ID,
                    "tenant_id": PRIMARY_TENANT_ID,
                },
                {
                    "uuid": ORG_ID,
                    "project_id": PROJECT_ID,
                    "tenant_id": PRIMARY_TENANT_ID,
                },
            ],
            "total": 2,
        },
        "secondary_tenant": {"entities": [], "total": 0},
        "secondary_project": {"entities": [], "total": 0},
        "cross_scope": {
            "status_code": 400,
            "detail": "Project does not belong to tenant",
        },
    }
    payload[field] = value

    with pytest.raises(RuntimeError, match=error):
        verify_tenant_graph_isolation(
            payload,
            expected_entity_ids={PERSON_ID, ORG_ID},
            primary_tenant_id=PRIMARY_TENANT_ID,
            primary_project_id=PROJECT_ID,
            secondary_tenant_id=SECONDARY_TENANT_ID,
            secondary_project_id=SECONDARY_PROJECT_ID,
        )


def test_verify_background_community_job_requires_completed_tracking_contract() -> None:
    verify_background_community_job(
        {
            "id": "task-e2e",
            "name": "rebuild_communities",
            "status": "Completed",
            "completed_at": "2026-08-12T00:00:00Z",
            "error": None,
        },
        task_id="task-e2e",
    )

    with pytest.raises(RuntimeError, match="background community rebuild"):
        verify_background_community_job(
            {
                "id": "task-e2e",
                "name": "rebuild_communities",
                "status": "Failed",
                "completed_at": "2026-08-12T00:00:00Z",
                "error": "fixture failure",
            },
            task_id="task-e2e",
        )


def test_verify_community_surfaces_accept_scoped_members_and_episode() -> None:
    community_id = verify_communities(
        {
            "communities": [
                {
                    "uuid": "community-e2e",
                    "project_id": PROJECT_ID,
                    "member_count": 2,
                }
            ]
        },
        project_id=PROJECT_ID,
    )
    verify_graph_traversal(
        {
            "search_type": "graph_traversal",
            "results": [{"uuid": ORG_ID, "name": "Deterministic Graph Labs"}],
        },
        expected_entity_id=ORG_ID,
    )
    verify_community_search(
        {
            "search_type": "community",
            "results": [
                {"uuid": PERSON_ID, "type": "entity"},
                {"uuid": EPISODE_ID, "type": "episode"},
            ],
        },
        person_id=PERSON_ID,
        episode_id=EPISODE_ID,
    )
    assert community_id == "community-e2e"


def test_verify_community_surfaces_reject_missing_or_cross_project_results() -> None:
    with pytest.raises(RuntimeError, match="community"):
        verify_communities(
            {
                "communities": [
                    {
                        "uuid": "community-e2e",
                        "project_id": "other-project",
                        "member_count": 2,
                    }
                ]
            },
            project_id=PROJECT_ID,
        )

    with pytest.raises(RuntimeError, match="traversal"):
        verify_graph_traversal(
            {"search_type": "graph_traversal", "results": []},
            expected_entity_id=ORG_ID,
        )


@pytest.mark.parametrize(
    ("available", "payload"),
    [
        (
            True,
            {
                "graph_backend": {
                    "status": "available",
                    "reason_code": None,
                    "retryable": False,
                    "allowed_actions": ["search", "traverse", "rebuild_communities"],
                }
            },
        ),
        (
            False,
            {
                "graph_backend": {
                    "status": "degraded",
                    "reason_code": "graph_backend_unavailable",
                    "retryable": True,
                    "allowed_actions": ["retry"],
                }
            },
        ),
    ],
)
def test_verify_backend_capability_accepts_stable_available_and_degraded_contracts(
    available: bool,
    payload: object,
) -> None:
    verify_backend_capability(payload, available=available)
