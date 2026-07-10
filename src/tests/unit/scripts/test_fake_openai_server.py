import json

from fastapi.testclient import TestClient

from scripts.fake_openai_server import E2E_AGENT_RESPONSE, app


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
    assert content == {
        "goal_achieved": True,
        "reason": "The deterministic E2E response was delivered.",
    }
    assert payload["choices"][0]["finish_reason"] == "stop"


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
