"""Drive signed Feishu renderer updates through the established channel event bridge."""

import asyncio
import base64
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services.channels import event_bridge, timeline_renderer
from src.configuration.config import get_settings
from src.domain.model.channels.message import ChannelConfig
from src.infrastructure.adapters.secondary.channels.channel_plugin_loader import load_channel_module
from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
    ChannelSessionBindingModel,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    UserProject,
)
from src.tests.integration.signed_wasm_releases import build_upgrade_pair
from src.tests.unit.routers import test_optional_business_http_v2 as package_api

http = package_api.http
publisher = package_api.publisher
pytestmark = pytest.mark.integration
PACKAGE = Path(__file__).resolve().parents[3] / "plugins/adapters/channels/feishu"
PLUGIN = "memstack-feishu-timeline"


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    return build_upgrade_pair(
        PACKAGE,
        tmp_path_factory.mktemp("feishu-timeline-publisher"),
        '"Starting".to_owned()',
        '"Now running".to_owned()',
    )


async def _channel_bridge(db_session, monkeypatch):
    db_session.add(Project(id="second", tenant_id="t", name="Second", owner_id="owner"))
    await db_session.flush()
    db_session.add(
        UserProject(id="second-owner", user_id="owner", project_id="second", role="owner")
    )
    for project in ("p", "second"):
        db_session.add(
            ChannelConfigModel(
                id=f"cfg-{project}",
                project_id=project,
                name="Feishu",
                channel_type="feishu",
                extra_settings={"task_timeline_package": PLUGIN},
            )
        )
        db_session.add(
            Conversation(
                id=f"conv-{project}",
                project_id=project,
                tenant_id="t",
                user_id="owner",
                title="Task updates",
            )
        )
        await db_session.flush()
        db_session.add(
            ChannelSessionBindingModel(
                id=f"binding-{project}",
                project_id=project,
                channel_config_id=f"cfg-{project}",
                conversation_id=f"conv-{project}",
                channel_type="feishu",
                chat_id=f"chat-{project}",
                chat_type="p2p",
                session_key=f"session-{project}",
            )
        )
    await db_session.commit()

    @asynccontextmanager
    async def request_scope():
        yield db_session

    monkeypatch.setattr(event_bridge, "with_session", request_scope)
    monkeypatch.setattr(timeline_renderer, "with_session", request_scope)
    adapter = load_channel_module("feishu", "adapter").FeishuAdapter(
        ChannelConfig(app_id="test", app_secret="unused")
    )
    adapter.send_message = AsyncMock(return_value="sent")
    bridge = event_bridge.ChannelEventBridge(
        SimpleNamespace(
            connections={
                "cfg-" + project: SimpleNamespace(adapter=adapter) for project in ("p", "second")
            }
        )
    )

    return adapter, bridge


async def test_feishu_task_timeline_uses_only_its_bound_projects_active_release(
    http, db_session, releases, monkeypatch, tmp_path
):
    client, keys = http
    public, original, upgraded = releases
    pem = tmp_path / "publisher.pem"
    pem.write_bytes(public)
    monkeypatch.setattr(get_settings(), "plugin_marketplace_trusted_key_files", (pem,))
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (public.decode(),)
    headers = {"Authorization": "Bearer " + keys["owner"]}
    base = "/api/v1/platform-plugins/v2/optional-business"

    async def install(project, package):
        scope = {"tenant_id": "t", "project_id": project}
        result = await client.post(
            base + "/install",
            headers=headers,
            json={
                **scope,
                "approved_permissions": ["tools.execute"],
                "archive_base64": base64.b64encode(package).decode(),
            },
        )
        assert result.is_success, result.text
        result = await client.post(f"{base}/{PLUGIN}/enable", headers=headers, json=scope)
        assert result.is_success and result.json()["runtime_phase"] == "active", result.text

    adapter, bridge = await _channel_bridge(db_session, monkeypatch)

    async def post(project, *, tenant="t", claimed=None, kind="task_start", content="Review"):
        await bridge.on_agent_event(
            f"conv-{project}",
            {
                "type": kind,
                "data": {
                    "content": content,
                    "status": "completed",
                    "order_index": 1,
                    "total_tasks": 5,
                },
            },
            tenant_id=tenant,
            project_id=claimed or project,
        )

    def last(project):
        dest, message, _ = adapter.send_message.await_args.args
        assert dest == f"chat-{project}"
        assert message.card["schema"] == "2.0"
        return message.card["body"]["elements"][0]["content"]

    for project in ("p", "second"):
        await install(project, original)
        await post(project)
        assert "(2/5) **Starting:** Review" in last(project)
    await install("p", upgraded)
    await post("p")
    assert "(2/5) **Now running:** Review" in last("p")
    await post("second")
    assert "(2/5) **Starting:** Review" in last("second")
    sent = adapter.send_message.await_count
    await post("p", claimed="second")
    await post("p", tenant="unrelated")
    assert adapter.send_message.await_count == sent
    result = await client.post(
        f"{base}/{PLUGIN}/rollback", headers=headers, json={"tenant_id": "t", "project_id": "p"}
    )
    assert result.is_success, result.text
    await asyncio.gather(
        post("p", content="first"), post("p", kind="task_complete", content="second")
    )
    cards = [
        entry.args[1].card["body"]["elements"][0]["content"]
        for entry in adapter.send_message.await_args_list[-2:]
    ]
    assert "**Starting:** first" in cards[0]
    assert "**Completed:** second" in cards[1]
    result = await client.post(
        f"{base}/{PLUGIN}/disable", headers=headers, json={"tenant_id": "t", "project_id": "p"}
    )
    assert result.is_success, result.text
    await post("p")
    assert last("p") == "Review"
