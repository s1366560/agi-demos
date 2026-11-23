"""Exercise the graph worker through its published MCP entry point."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

WORKER = Path(__file__).parents[1] / "workers" / "graph_projection" / "worker.py"


@pytest.mark.unit
def test_worker_projects_only_relationships_with_visible_endpoints() -> None:
    edge = {"source": "b", "target": "a", "kind": "links", "fact": "", "score": 0.9}
    inputs = {
        "nodes": [
            {"uuid": "a", "name": "First", "kind": "topic"},
            {"uuid": "b", "name": "Second", "kind": "topic"},
        ],
        "edges": [edge, {**edge, "target": "absent"}],
    }
    call = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "project_graph", "arguments": inputs},
    }
    response = subprocess.run(
        [sys.executable, str(WORKER)],
        input=json.dumps(call),
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    projected = json.loads(response.stdout)["result"]["structuredContent"]
    assert projected == {
        "entities": [{"name": "First", "kind": "topic"}, {"name": "Second", "kind": "topic"}],
        "relationships": [
            {
                "source_index": 1,
                "target_index": 0,
                "relation_type": "links",
                "fact": "links",
                "score": 0.9,
            }
        ],
    }
