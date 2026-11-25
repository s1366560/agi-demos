"""Check the installed Agent review's authorization between two real, isolated QA projects."""

import json
import os
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_signed_agent_cannot_review_another_projects_run():
    accounts_path = os.getenv("MEMSTACK_QA_SIDEBAR_ACCOUNTS")
    if not accounts_path:
        pytest.skip("two dedicated Agent QA projects required")
    projects = json.loads(Path(accounts_path).read_bytes())["agent"]
    base = "/platform-plugins/v2/optional-business"
    with ExitStack() as stack:
        owners = []
        for platform in ("web", "desktop"):
            account = json.loads(Path(projects[platform]).read_bytes())
            client = stack.enter_context(
                httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30)
            )
            login = client.post(
                "/auth/token", data={"username": account["email"], "password": account["password"]}
            )
            login.raise_for_status()
            client.headers["authorization"] = "Bearer " + login.json()["access_token"]
            scope = {key: account[key] for key in ("tenant_id", "project_id")}
            owners.append((client, scope))
        reader, scope = owners[0]
        other, other_scope = owners[1]
        assert (
            scope["tenant_id"] != other_scope["tenant_id"]
            and scope["project_id"] != other_scope["project_id"]
        )
        info = reader.get(
            base + "/npm/detail",
            params={
                **scope,
                "plugin_id": "memstack-agent",
                "package_name": "@memstack/agent",
                "version": json.loads(Path("plugins/business/agent/package.json").read_bytes())[
                    "version"
                ],
            },
        )
        info.raise_for_status()
        digest = info.json()["release"]["digest"]
        assert info.json()["installation"]["actual_digest"] == digest
        listing = other.get(
            "/agent/conversations", params={"project_id": other_scope["project_id"]}
        )
        listing.raise_for_status()
        run = None
        for item in listing.json()["items"]:
            latest = other.get("/agent/conversations/" + item["id"] + "/latest-run")
            latest.raise_for_status()
            if run := latest.json()["latest_run"]:
                break
        assert run
        for command, payload in (
            ("review-latest", {"conversation_id": run["conversation_id"]}),
            ("review-details", {"run_id": run["id"], "view": "summary"}),
            (
                "review-details",
                {"run_id": run["id"], "view": "changes", "expected_revision": run["revision"]},
            ),
        ):
            response = reader.post(
                base + "/memstack-agent/commands",
                json={
                    **scope,
                    "expected_digest": digest,
                    "command_id": command,
                    "payload": payload,
                },
            )
            assert response.status_code == 403


def test_installed_dashboard_cannot_open_another_tenants_trace():
    path = os.getenv("MEMSTACK_QA_SIDEBAR_ACCOUNTS")
    if not path:
        pytest.skip("two dedicated Agent QA tenants required")
    accounts = json.loads(Path(path).read_bytes())["agent"]
    with ExitStack() as stack:
        tenants = []
        for target in ("web", "desktop"):
            owner = json.loads(Path(accounts[target]).read_bytes())
            client = stack.enter_context(
                httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=20)
            )
            token = client.post(
                "/auth/token", data={"username": owner["email"], "password": owner["password"]}
            )
            token.raise_for_status()
            client.headers["authorization"] = "Bearer " + token.json()["access_token"]
            tenants.append((client, owner["tenant_id"]))
        reader, tenant = tenants[0]
        other, foreign = tenants[1]
        query = {
            "tenant_id": tenant,
            "plugin_id": "memstack-agent",
            "package_name": "@memstack/agent",
            "version": "1.6.0",
        }
        release = reader.get("/tenant-packages/npm/detail", params=query)
        release.raise_for_status()
        data = other.get(f"/agent/trace/runs/tenant/{foreign}")
        data.raise_for_status()
        run = next(entry for entry in data.json()["runs"] if entry["trace_id"])
        cmd = {
            "tenant_id": tenant,
            "expected_digest": release.json()["release"]["digest"],
            "command_id": "dashboard-trace",
            "payload": {"conversation_id": run["conversation_id"], "trace_id": run["trace_id"]},
        }
        denied = reader.post("/tenant-packages/memstack-agent/commands", json=cmd)
        assert denied.status_code == 404
        denied = reader.post(
            "/tenant-packages/memstack-agent/commands", json={**cmd, "tenant_id": foreign}
        )
        assert denied.status_code in {403, 404}


def _assert_signed_project_context(command):
    for view, key in (
        ("stats", "memory_count"),
        ("trending", "entities"),
        ("recent-skills", "skills"),
        ("templates", "templates"),
        ("commands", "commands"),
        ("lifecycle", "lifecycle_state"),
    ):
        response = command("chat-project-context", {"view": view})
        response.raise_for_status()
        assert key in response.json()
        if view == "commands":
            assert all(
                row["scope"] in ("system", "tenant", "project")
                for row in response.json()["skills"]
            )
        if view == "lifecycle":
            assert isinstance(response.json()["pool_managed"], bool)
            assert set(response.json()["allowed_actions"]) <= {
                "stop",
                "restart",
                "pause",
                "resume",
            }
    # The signed input cannot select a different project or supply an actor ID.
    rejected = command(
        "chat-lifecycle-control", {"action": "stop", "project_id": "not-the-signed-project"}
    )
    assert rejected.status_code == 400 and "project_id" in rejected.json()["detail"]
    welcome = command("chat-welcome", {})
    welcome.raise_for_status()
    assert isinstance(welcome.json()["complete"], bool)


def _assert_workbench_conversations(client, command, project_id):
    api_params = {"project_id": project_id, "limit": 10}
    unbound = client.get("/agent/conversations", params={**api_params, "unbound_only": "true"})
    grouped = client.get(
        "/agent/conversations", params={**api_params, "group_by_workspace": "true"}
    )
    for response in (unbound, grouped):
        response.raise_for_status()
    expected = list(
        dict.fromkeys(
            row["id"] for response in (unbound, grouped) for row in response.json()["items"]
        )
    )
    sidebar = command("chat-list", {"workbench": True, "limit": 10})
    sidebar.raise_for_status()
    assert [row["id"] for row in sidebar.json()["items"]] == expected


def test_installed_composer_roundtrips_scoped_preferences():
    accounts_path = os.getenv("MEMSTACK_QA_SIDEBAR_ACCOUNTS")
    if not accounts_path:
        pytest.skip("dedicated installed Agent QA project required")
    credentials = json.loads(Path(accounts_path).read_bytes())["agent"]["web"]
    account = json.loads(Path(credentials).read_bytes())
    scope = {key: account[key] for key in ("tenant_id", "project_id")}
    api = "/platform-plugins/v2/optional-business"
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=45) as client:
        login = client.post(
            "/auth/token", data={"username": account["email"], "password": account["password"]}
        )
        login.raise_for_status()
        client.headers["authorization"] = "Bearer " + login.json()["access_token"]
        version = json.loads(Path("plugins/business/agent/package.json").read_bytes())["version"]
        listing = client.get(
            api + "/npm/detail",
            params={
                **scope,
                "plugin_id": "memstack-agent",
                "package_name": "@memstack/agent",
                "version": version,
            },
        )
        listing.raise_for_status()
        detail = listing.json()
        digest = detail["release"]["digest"]
        assert digest == detail["installation"]["actual_digest"]

        def command(name, payload):
            return client.post(
                api + "/memstack-agent/commands",
                json={
                    **scope,
                    "expected_digest": digest,
                    "command_id": name,
                    "payload": payload,
                },
            )

        roster = command("chat-models", {})
        roster.raise_for_status()
        catalog = roster.json()
        assert set(catalog) == {"models", "default_model"}
        _assert_signed_project_context(command)
        _assert_workbench_conversations(client, command, scope["project_id"])
        created = command("chat-create", {"title": "Composer setting roundtrip"})
        created.raise_for_status()
        conversation = {"conversation_id": created.json()["id"]}
        try:
            for view, key in (("tasks", "tasks"), ("context-window", "conversation_id")):
                response = command("chat-project-context", {"view": view, **conversation})
                response.raise_for_status()
                assert key in response.json()
            changes = [
                ("approval_mode", "auto_edit"),
                ("reasoning_effort", "low"),
                ("mode", "plan"),
                ("llm_overrides", {"temperature": 0.73, "top_p": 0.83, "max_tokens": 64}),
            ]
            if catalog["models"]:
                changes.append(("llm_model_override", catalog["models"][0]))
            for key, value in changes:
                updated = command("chat-composer-save", {**conversation, key: value})
                updated.raise_for_status()
                assert updated.json()[key] == value
            restored = command("chat-composer-read", conversation)
            restored.raise_for_status()
            assert all(restored.json()[key] == value for key, value in changes)
            assert (
                command(
                    "chat-composer-save", {**conversation, "llm_model_override": "unknown-qa-model"}
                ).status_code
                == 403
            )
        finally:
            cleanup = client.delete(
                "/agent/conversations/" + conversation["conversation_id"],
                params={"project_id": scope["project_id"]},
            )
            cleanup.raise_for_status()
