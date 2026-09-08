"""Graph element identities remain structural while real provenance is preserved."""

import pytest

from src.infrastructure.adapters.primary.web.routers.graph import _rows_to_elements


@pytest.mark.unit
def test_graph_rows_keep_direction_provenance_and_deduplicate_actual_edge_ids() -> None:
    row = {
        "source_id": "element-episode",
        "source_labels": ["Episodic", "Node"],
        "source_props": {
            "id": "untrusted-property-id",
            "uuid": "episode-uuid",
            "name": "Same name",
            "content": "Captured episode content",
            "source_description": "document",
            "memory_id": "memory-uuid",
            "project_id": "project-1",
            "tenant_id": "tenant-1",
            "created_at": "2026-09-08T01:00:00Z",
            "valid_at": "2026-09-07T01:00:00Z",
            "name_embedding": [0.1],
        },
        "target_id": "element-entity",
        "target_labels": ["Entity", "Node"],
        "target_props": {"uuid": "entity-uuid", "name": "Same name"},
        "edge_id": "element-relationship",
        "edge_type": "MENTIONS",
        "edge_props": {
            "id": "untrusted-edge-id",
            "source": "wrong-source",
            "target": "wrong-target",
            "label": "wrong-label",
            "uuid": "relationship-uuid",
            "fact": "Observed fact",
            "episodes": ["episode-uuid"],
            "valid_at": "2026-09-07T01:00:00Z",
            "fact_embedding": [0.2],
        },
    }
    elements = _rows_to_elements([row, row])["elements"]
    assert len(elements["nodes"]) == 2
    assert len(elements["edges"]) == 1
    source, target = [item["data"] for item in elements["nodes"]]
    edge = elements["edges"][0]["data"]
    assert source["id"] == "element-episode"
    assert source["uuid"] == "episode-uuid"
    assert source["content"] == "Captured episode content"
    assert source["memory_id"] == "memory-uuid"
    assert source["valid_at"] == "2026-09-07T01:00:00Z"
    assert "name_embedding" not in source
    assert target["uuid"] == "entity-uuid"
    assert edge["id"] == "element-relationship"
    assert (edge["source"], edge["target"], edge["label"]) == (
        "element-episode",
        "element-entity",
        "MENTIONS",
    )
    assert edge["episodes"] == ["episode-uuid"]
    assert edge["fact"] == "Observed fact"
    assert "fact_embedding" not in edge
    assert "memory_revision" not in source


@pytest.mark.unit
def test_graph_self_loop_retains_one_directed_edge() -> None:
    props = {"uuid": "entity-uuid", "name": "Self"}
    row = {
        "source_id": "element-entity",
        "source_labels": ["Entity"],
        "source_props": props,
        "target_id": "element-entity",
        "target_labels": ["Entity"],
        "target_props": props,
        "edge_id": "self-edge",
        "edge_type": "RELATES_TO",
        "edge_props": {},
    }
    elements = _rows_to_elements([row, row])["elements"]
    assert len(elements["nodes"]) == 1
    assert len(elements["edges"]) == 1
    assert elements["edges"][0]["data"]["source"] == elements["edges"][0]["data"]["target"]
