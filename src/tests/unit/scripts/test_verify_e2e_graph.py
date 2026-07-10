"""Tests for the real Graph E2E verifier contract."""

import pytest

from scripts.verify_e2e_graph import (
    verify_entities,
    verify_episode,
    verify_fixture_usage,
    verify_graph,
    verify_relationships,
    verify_search,
)

PROJECT_ID = "project-e2e"
EPISODE_ID = "episode-e2e"
PERSON_ID = "person-e2e"
ORG_ID = "organization-e2e"


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
