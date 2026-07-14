import json

import pytest
from fastapi.testclient import TestClient

from scripts.fake_openai_server import (
    E2E_AGENT_RESPONSE,
    E2E_EMBEDDING_DIMENSIONS,
    app,
)


def test_fake_openai_lists_the_deterministic_model() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "id": "memstack-e2e",
            "object": "model",
            "owned_by": "memstack-e2e",
        }
    ]


def test_fake_openai_returns_non_streaming_chat_completion() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "memstack-e2e", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200
    payload = response.json()
    content = json.loads(payload["choices"][0]["message"]["content"])
    assert content["goal_achieved"] is True
    assert content["missed_entities"] == []
    assert {entity["name"] for entity in content["entities"]} == {
        "Ariadne Vale",
        "Deterministic Graph Labs",
    }
    assert content["relationships"] == [
        {
            "from_entity": "Ariadne Vale",
            "to_entity": "Deterministic Graph Labs",
            "relationship_type": "FOUNDED",
            "fact": "Ariadne Vale founded Deterministic Graph Labs.",
            "confidence": 1.0,
        }
    ]
    assert payload["choices"][0]["finish_reason"] == "stop"


def test_fake_openai_returns_structured_auto_broker_tool_call() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "memstack-e2e",
                "messages": [{"role": "user", "content": "route this"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "route_request", "parameters": {}},
                    }
                ],
            },
        )

    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    tool_call = choice["message"]["tool_calls"][0]
    assert tool_call["function"]["name"] == "route_request"
    assert json.loads(tool_call["function"]["arguments"]) == {
        "tier": "medium",
        "require_vision": False,
        "require_tools": False,
        "category": "analysis",
        "rationale": "Deterministic E2E routing verdict.",
    }


def test_fake_openai_returns_openai_compatible_sse_stream() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "memstack-e2e",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    data_lines = [
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    chunks = [json.loads(line) for line in data_lines]
    assert chunks[0]["choices"][0]["delta"]["content"] == E2E_AGENT_RESPONSE
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert response.text.rstrip().endswith("data: [DONE]")


def test_fake_openai_returns_deterministic_batch_embeddings_and_counts_usage() -> None:
    with TestClient(app) as client:
        before = client.get("/_e2e/stats").json()
        first = client.post(
            "/v1/embeddings",
            json={"model": "memstack-e2e", "input": ["Ariadne Vale", "Graph Labs"]},
        )
        second = client.post(
            "/v1/embeddings",
            json={"model": "memstack-e2e", "input": "Ariadne Vale"},
        )
        after = client.get("/_e2e/stats").json()

    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert [item["index"] for item in first_data] == [0, 1]
    assert len(first_data[0]["embedding"]) == E2E_EMBEDDING_DIMENSIONS
    assert first_data[0]["embedding"] == second_data[0]["embedding"]
    assert sum(value != 0.0 for value in first_data[0]["embedding"]) == 1
    assert after["embedding_requests"] == before["embedding_requests"] + 2


@pytest.mark.parametrize("invalid_input", [None, 7, ["valid", 7]])
def test_fake_openai_rejects_invalid_embedding_input(invalid_input: object) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/embeddings",
            json={"model": "memstack-e2e", "input": invalid_input},
        )

    assert response.status_code == 400
