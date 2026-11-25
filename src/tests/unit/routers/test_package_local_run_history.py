"""Exercise the signed Agent commands and the device journal on the standard host."""

import pytest

from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

pytestmark = pytest.mark.unit
BASE = "/api/v1/platform-plugins/v2/optional-business"
AGENT = "/api/v1/agent"


async def assert_history_scope(client, conversation_id, headers, viewer):
    history_url = f"{AGENT}/conversations"
    detail = await client.get(
        f"{history_url}/{conversation_id}", params={"project_id": "p"}, headers=headers
    )
    assert detail.json()["execution_target"] == "local"
    assert detail.json()["tenant_id"] == "t"
    assert (
        await client.get(
            f"{history_url}/{conversation_id}", params={"project_id": "other"}, headers=headers
        )
    ).status_code == 403
    assert (
        await client.get(
            f"{history_url}/{conversation_id}", params={"project_id": "p"}, headers=viewer
        )
    ).status_code == 404
    listing = await client.get(
        history_url, params={"project_id": "p", "limit": 1, "offset": 0}, headers=headers
    )
    assert listing.json()["total"] == 1 and listing.json()["items"] == [detail.json()]


async def assert_replayed_messages(command, conversation_id, expected):
    history = await command("history", {"conversation_id": conversation_id})
    assert history["before"] is None
    messages = history["messages"]
    assert [{"role": row["role"], "content": row["content"]} for row in messages] == expected
    assert len({row["id"] for row in messages}) == len(expected)
    assert all(row["timestamp"] == row["eventTimeUs"] // 1000 for row in messages)
    assert await command("history", {"conversation_id": conversation_id}) == history


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("http", ["package-kernel"], indirect=True)
async def test_two_device_turns_share_owned_signed_history(http, publisher):  # noqa: F811
    client, keys = http
    headers = {"Authorization": "Bearer " + keys["owner"]}
    desktop = {**headers, "X-Agi-Surface": "desktop"}
    viewer = {"Authorization": "Bearer " + keys["viewer"]}
    commands = {name: "app.agent." + name for name in ("create", "list", "history")}
    body, digest = publisher[1](application_command=commands)
    scope = {"tenant_id": "t", "project_id": "p"}
    assert (await client.post(BASE + "/install", json=body, headers=headers)).is_success
    base = BASE + "/sample.notes"
    assert (await client.post(base + "/enable", json=scope, headers=headers)).is_success

    async def command(name, payload):
        response = await client.post(
            base + "/commands",
            json={**scope, "command_id": name, "expected_digest": digest, "payload": payload},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    created = await command("create", {"title": "Device", "execution_target": "local"})
    assert created["execution_target"] == "local"
    assert created in (await command("list", {}))["items"]
    conversation_id = created["id"]
    await assert_history_scope(client, conversation_id, headers, viewer)
    register = f"{AGENT}/conversations/{conversation_id}/local-runs"
    placement = {"execution_machine_id": "machine-a1"}
    expected = []
    for turn in ("first", "second"):
        registration = {
            **placement,
            "idempotency_key": "fixture-" + turn,
            "local_root_label": "project",
            "message": turn,
        }
        assert (await client.post(register, json=registration, headers=headers)).status_code == 403
        response = await client.post(register, json=registration, headers=desktop)
        response.raise_for_status()
        run = response.json()["run_id"]
        endpoint = f"{AGENT}/runs/{run}"
        events = [
            {"seq": 1, "kind": "user_message", "payload": {"text": turn}},
            {"seq": 2, "kind": "assistant_message", "payload": {"text": "Answer " + turn}},
        ]
        if turn == "second":
            stopped = await client.post(
                endpoint + "/local-stop",
                json={**placement, "expected_revision": response.json()["revision"]},
                headers=desktop,
            )
            assert stopped.json()["status"] == "cancel_requested"
        upload = {**placement, "events": events}
        response = await client.post(endpoint + "/events:batch", json=upload, headers=desktop)
        response.raise_for_status()
        assert response.json()["accepted_through_seq"] == 2
        retry = await client.post(endpoint + "/events:batch", json=upload, headers=desktop)
        assert retry.json()["idempotent"]
        settled = await client.patch(
            endpoint + "/local-terminal",
            json={
                **placement,
                "expected_revision": retry.json()["revision"],
                "status": "cancelled" if turn == "second" else "completed",
            },
            headers=desktop,
        )
        settled.raise_for_status()
        assert settled.json()["upload_state"] == "synced"
        if turn == "second":
            assert settled.json()["status"] == "cancelled"
            assert (
                await client.post(endpoint + "/events:batch", json=upload, headers=desktop)
            ).json()["idempotent"]

        assert (await client.get(endpoint + "/local-events", headers=viewer)).status_code in (
            403,
            404,
        )
        expected.extend(
            {"role": event["kind"], "content": event["payload"]["text"]} for event in events
        )

    await assert_replayed_messages(command, conversation_id, expected)
