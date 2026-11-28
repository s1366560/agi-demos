"""Install, replace and roll back the official Skill validator against real immutable workers."""

import asyncio
import base64
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plugins.business.agent.release import build_release
from src.configuration.config import get_settings
from src.tests.integration.package_http_server import serve_project_api
from src.tests.unit.infrastructure.agent.core import (
    test_project_package_subagents as agent_fixtures,
)
from src.tests.unit.routers import test_optional_business_http_v2 as project_fixtures

http = project_fixtures.http
publisher = project_fixtures.publisher
project_turn = agent_fixtures.project_turn

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]

_PACKAGE = Path(__file__).resolve().parents[3] / "plugins/business/agent"
_DOCUMENT = "---\nname: review\ndescription: Check every documented feature\n---\n# Review"


@pytest_asyncio.fixture(loop_scope="function")
async def project_cli(http, tmp_path):
    client, credentials = http
    skill_dir = tmp_path / "review"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_DOCUMENT)
    async with serve_project_api(client._transport.app) as origin:

        async def invoke():
            repo = _PACKAGE.parents[2]
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "src.cli.skill_validate",
                "--tenant",
                "t",
                "--project",
                "p",
                str(skill_dir),
                cwd=repo,
                env={
                    **os.environ,
                    "PYTHONPATH": str(repo / "sdk/memstack_cli"),
                    "MEMSTACK_API_URL": origin,
                    "MEMSTACK_API_KEY": credentials["owner"],
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            assert process.returncode in (0, 1), stderr.decode()[:500]
            return process.returncode, json.loads(stdout)["is_valid"]

        yield invoke


@pytest.fixture(scope="module")
def skill_images(tmp_path_factory):
    from src.tests.integration.test_oci_mcp_worker_docker import disposable_worker_registry

    directory = tmp_path_factory.mktemp("agent-publisher")
    shutil.copytree(
        _PACKAGE,
        directory,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "node_modules"),
    )
    with disposable_worker_registry() as (publish, registry, _):
        first = publish(directory)
        validator = directory / "skill_validation/validator.py"
        before = validator.read_text()
        after = before.replace("DESCRIPTION_MAX_LENGTH = 1024", "DESCRIPTION_MAX_LENGTH = 8")
        assert before != after
        validator.write_text(after)
        yield registry, {"1.0.0": first, "1.1.0": publish(directory)}


async def test_signed_skill_validator_upgrade_changes_project_behavior(
    http, skill_images, project_cli, project_turn, monkeypatch
):
    from types import SimpleNamespace

    from src.domain.events.agent_events import AgentTextEndEvent
    from src.infrastructure.agent.subagent.process import SubAgentProcess

    client, credentials = http
    registry, images = skill_images
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    key = Ed25519PrivateKey.generate()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (public,)
    scope = {"project_id": "p", "tenant_id": "t"}
    headers = {"Authorization": "Bearer " + credentials["owner"]}
    base = "/api/v1/platform-plugins/v2/optional-business"
    active = base + "/memstack-agent"
    request = {
        **scope,
        "tool_name": "validate_skill",
        "payload": {"content": _DOCUMENT},
    }
    worker_results = []

    def offline_processor(process, **_kwargs):
        async def run(messages, **_kwargs):
            assert "SKILL.md" in messages[0]["content"]
            (validator,) = process._tools
            result = json.loads(await validator.execute(content=_DOCUMENT))
            worker_results.append(result["is_valid"])
            yield AgentTextEndEvent(full_text=json.dumps(result))

        return SimpleNamespace(process=run)

    monkeypatch.setattr(SubAgentProcess, "_build_processor", offline_processor)

    async def delegate(run):
        async with project_turn(run, user="owner", public_key=public) as (catalog, tool_set):
            (reviewer,) = catalog.subagents.values()
            assert reviewer.display_name == "Skill format reviewer"
            tool = agent_fixtures.delegate_for(catalog, tool_set, frozenset({reviewer.id}))
            result = await agent_fixtures._execute_with_context(
                tool, agent_fixtures._context("c"), subagent_name=reviewer.name, task=_DOCUMENT
            )
            assert not result.is_error, result.output

    for version, valid in (("1.0.0", True), ("1.1.0", False)):
        raw = build_release(images[version], version, key)
        record = await client.post(
            base + "/install",
            headers=headers,
            json={
                **scope,
                "archive_base64": base64.b64encode(raw).decode(),
                "approved_permissions": [
                    "ui.slot",
                    "tools.execute",
                    "subagents.register",
                    "agent.loop.drive",
                    "app.agent.list",
                    "app.agent.create",
                    "app.agent.history",
                    "app.agent.turn",
                    "app.agent.attachments",
                    "app.agent.attachments.turn",
                    "app.agent.activity.read",
                    "app.agent.activity.receipts",
                    "app.agent.review.latest",
                    "app.agent.review.details",
                    "app.agent.composer.read",
                    "app.agent.composer.save",
                    "app.agent.composer.models",
                    "app.agent.composer.context",
                    "app.agent.composer.welcome",
                    "app.agent.lifecycle.control",
                    "app.agent.voice.authorize",
                    "ui.media.microphone",
                    "app.agent.interactions",
                    "app.agent.respond",
                    "app.agent.cancel",
                    "app.agent.rename",
                    "device.local-chat",
                ],
            },
        )
        assert record.status_code == 200, record.text
        enabled = await client.post(active + "/enable", headers=headers, json=scope)
        assert enabled.is_success and enabled.json()["runtime_phase"] == "active", enabled.text
        result = await client.post(active + "/invoke", headers=headers, json=request)
        assert result.is_success and result.json()["is_valid"] is valid, result.text
        assert await project_cli() == (0 if valid else 1, valid)
        await delegate("first" if valid else "second")
        if not valid:
            assert result.json()["errors"][0]["field"] == "description"
    rollback = await client.post(active + "/rollback", headers=headers, json=scope)
    assert rollback.is_success
    restored = await client.post(active + "/invoke", headers=headers, json=request)
    assert restored.is_success and restored.json()["is_valid"] is True, restored.text
    assert await project_cli() == (0, True)
    await delegate("third")
    assert worker_results == [True, False, True]
