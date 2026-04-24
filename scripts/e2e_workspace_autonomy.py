#!/usr/bin/env python3
"""Run workspace autonomy E2E scenarios against a local API server.

The script intentionally uses only stdlib HTTP calls so it can run in a
developer checkout without extra dependencies. It creates fresh workspaces and
agent definitions, then verifies that the central blackboard autonomy loop can
decompose, dispatch, reconcile, and complete goals.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_USERNAME = "admin@memstack.ai"
DEFAULT_PASSWORD = "adminpassword"


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__(f"{method} {path} failed with HTTP {status}: {body[:500]}")
        self.method = method
        self.path = path
        self.status = status
        self.body = body


@dataclass
class ApiClient:
    base_url: str
    token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:  # noqa: ANN401
        url = self.base_url.rstrip("/") + path
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme not in {"http", "https"}:
            raise ValueError(f"Unsupported URL scheme for E2E API call: {parsed_url.scheme}")
        if query:
            url += "?" + urllib.parse.urlencode(
                {key: value for key, value in query.items() if value is not None}
            )
        headers: dict[str, str] = {}
        data: bytes | None = None
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body).encode("utf-8")
        elif form_body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urllib.parse.urlencode(form_body).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ApiError(method, path, exc.code, body) from exc
        if not raw:
            return None
        return json.loads(raw)


def log(message: str) -> None:
    print(message, flush=True)


def _pick_first(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not items:
        raise RuntimeError(f"No {label} available for E2E")
    return items[0]


def login(client: ApiClient, username: str, password: str) -> None:
    payload = client.request(
        "POST",
        "/api/v1/auth/token",
        form_body={"username": username, "password": password},
    )
    client.token = payload["access_token"]


def pick_scope(client: ApiClient) -> tuple[str, str]:
    tenants_payload = client.request("GET", "/api/v1/tenants/")
    tenant = _pick_first(tenants_payload.get("tenants", []), "tenant")
    tenant_id = tenant["id"]
    projects_payload = client.request(
        "GET",
        "/api/v1/projects/",
        query={"tenant_id": tenant_id, "page_size": 100},
    )
    project = _pick_first(projects_payload.get("projects", []), "project")
    return tenant_id, project["id"]


def _ollama_chat_model(base_url: str = "http://localhost:11434") -> str | None:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    for model in payload.get("models", []):
        name = str(model.get("name") or model.get("model") or "")
        lowered = name.lower()
        if name and "embedding" not in lowered and "reranker" not in lowered:
            return name
    return None


def _ignore_missing_mapping(
    client: ApiClient,
    tenant_id: str,
    provider_id: str,
) -> None:
    try:
        client.request(
            "DELETE",
            f"/api/v1/llm-providers/tenants/{tenant_id}/providers/{provider_id}",
            query={"operation_type": "llm"},
        )
    except ApiError as exc:
        if exc.status != 404:
            raise


def configure_llm_provider(client: ApiClient, tenant_id: str) -> str | None:
    providers = client.request(
        "GET",
        "/api/v1/llm-providers/",
        query={"include_inactive": "true"},
    )
    ollama = next(
        (
            provider
            for provider in providers
            if str(provider.get("provider_type", "")).lower() == "ollama"
            and provider.get("is_active", True)
        ),
        None,
    )
    if ollama:
        chat_model = _ollama_chat_model(str(ollama.get("base_url") or "http://localhost:11434"))
        if chat_model:
            provider_id = ollama["id"]
            client.request(
                "PUT",
                f"/api/v1/llm-providers/{provider_id}",
                json_body={"llm_model": chat_model, "llm_small_model": chat_model},
            )
            client.request(
                "POST",
                f"/api/v1/llm-providers/tenants/{tenant_id}/providers/{provider_id}",
                query={"operation_type": "llm", "priority": -100},
            )
            return f"{ollama.get('name') or 'ollama'} ({chat_model})"
        _ignore_missing_mapping(client, tenant_id, ollama["id"])

    fallback = next(
        (
            provider
            for provider in providers
            if str(provider.get("provider_type", "")).lower() != "ollama"
            and provider.get("is_active", True)
        ),
        None,
    )
    if not fallback:
        return None
    provider_id = fallback["id"]
    client.request(
        "POST",
        f"/api/v1/llm-providers/tenants/{tenant_id}/providers/{provider_id}",
        query={"operation_type": "llm", "priority": -100},
    )
    return str(fallback.get("name") or fallback.get("provider_type") or provider_id)


def create_worker_definition(client: ApiClient, project_id: str, suffix: str) -> str:
    name = f"e2e-autonomy-worker-{suffix}"
    body = {
        "name": name,
        "display_name": f"E2E Autonomy Worker {suffix}",
        "project_id": project_id,
        "system_prompt": (
            "You are a deterministic workspace worker used for autonomy E2E tests. "
            "When assigned a workspace execution task, do not delegate, browse, inspect files, "
            "run terminal commands, or call MCP tools. Use the identifiers in the "
            "[workspace-task-binding] block, then call workspace_report_complete exactly once "
            "as your first tool action. Do not emit free-form analysis before the tool call. "
            "The assigned E2E task is complete when your report contains the deliverable package; "
            "do not modify repository files. "
            "Your summary must include concrete deliverables, acceptance checks, and artifact "
            "references. For development tasks, include API contract, implementation sketch, "
            "test cases, and review notes in the summary."
        ),
        "trigger_description": "Use for bounded workspace execution tasks in E2E tests.",
        "trigger_examples": ["Complete a workspace execution task and report evidence."],
        "trigger_keywords": ["e2e", "workspace", "implementation"],
        "temperature": 0.0,
        "max_tokens": 2048,
        "max_iterations": 20,
        "allowed_tools": ["workspace_report_complete"],
        "allowed_skills": [],
        "allowed_mcp_servers": [],
        "can_spawn": False,
        "discoverable": True,
        "metadata": {"e2e_workspace_autonomy": True},
    }
    created = client.request("POST", "/api/v1/agent/definitions", json_body=body)
    return created["id"]


def create_workspace(client: ApiClient, tenant_id: str, project_id: str, suffix: str) -> str:
    workspace = client.request(
        "POST",
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
        json_body={
            "name": f"E2E Autonomy {suffix}",
            "description": "Temporary workspace for central blackboard autonomy E2E.",
            "metadata": {"e2e_workspace_autonomy": True, "suffix": suffix},
        },
    )
    return workspace["id"]


def bind_worker(
    client: ApiClient,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    agent_id: str,
    suffix: str,
) -> str:
    binding = client.request(
        "POST",
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents",
        json_body={
            "agent_id": agent_id,
            "display_name": f"E2E Worker {suffix}",
            "description": "Completes assigned E2E workspace tasks and reports evidence.",
            "config": {"e2e_workspace_autonomy": True},
            "is_active": True,
            "label": "e2e-worker",
            "theme_color": "#2563eb",
        },
    )
    return binding["id"]


def root_metadata(scenario: str) -> dict[str, Any]:
    return {
        "autonomy_schema_version": 1,
        "task_role": "goal_root",
        "goal_origin": "human_defined",
        "goal_source_refs": [f"api:e2e:{scenario}"],
        "goal_formalization_reason": "E2E test root task created by automation.",
        "root_goal_policy": {
            "mutable_by_agent": True,
            "completion_requires_external_proof": False,
        },
        "goal_health": "healthy",
        "remediation_status": "none",
    }


def create_root_task(
    client: ApiClient,
    workspace_id: str,
    *,
    title: str,
    description: str,
    scenario: str,
) -> str:
    task = client.request(
        "POST",
        f"/api/v1/workspaces/{workspace_id}/tasks",
        json_body={
            "title": title,
            "description": description,
            "metadata": root_metadata(scenario),
        },
    )
    return task["id"]


def tick(client: ApiClient, workspace_id: str) -> dict[str, Any]:
    return client.request(
        "POST",
        f"/api/v1/workspaces/{workspace_id}/autonomy/tick",
        json_body={"force": True},
    )


def list_tasks(client: ApiClient, workspace_id: str) -> list[dict[str, Any]]:
    return client.request(
        "GET",
        f"/api/v1/workspaces/{workspace_id}/tasks",
        query={"limit": 500},
    )


def get_plan(client: ApiClient, workspace_id: str) -> dict[str, Any]:
    return client.request(
        "GET",
        f"/api/v1/workspaces/{workspace_id}/plan",
        query={"outbox_limit": 50, "event_limit": 100},
    )


def _status(task: dict[str, Any]) -> str:
    value = task.get("status")
    return str(value.get("value") if isinstance(value, dict) else value)


def _role(task: dict[str, Any]) -> str:
    metadata = task.get("metadata") or {}
    return str(metadata.get("task_role") or "")


def summarize_state(
    tasks: list[dict[str, Any]],
    plan_snapshot: dict[str, Any],
    root_task_id: str,
) -> dict[str, Any]:
    root = next((task for task in tasks if task["id"] == root_task_id), None)
    children = [
        task
        for task in tasks
        if _role(task) == "execution_task"
        and (task.get("metadata") or {}).get("root_goal_task_id") == root_task_id
    ]
    plan = plan_snapshot.get("plan") or {}
    nodes = plan.get("nodes") or []
    events = plan_snapshot.get("events") or []
    return {
        "root_status": _status(root) if root else "missing",
        "child_count": len(children),
        "child_statuses": sorted({_status(task) for task in children}),
        "done_children": sum(1 for task in children if _status(task) == "done"),
        "reported_children": sum(
            1 for task in children if (task.get("metadata") or {}).get("last_worker_report_summary")
        ),
        "plan_status": plan.get("status"),
        "plan_node_count": len(nodes),
        "dag_edge_count": sum(len(node.get("depends_on") or []) for node in nodes),
        "reconciled": any(
            event.get("event_type") == "root_auto_completed_plan_reconciled" for event in events
        ),
    }


def is_scenario_done(
    state: dict[str, Any],
    *,
    min_children: int,
    min_plan_nodes: int,
    require_dag: bool,
) -> bool:
    child_count = state["child_count"]
    if not (
        state["root_status"] == "done"
        and child_count >= min_children
        and state["done_children"] == child_count
        and state["reported_children"] == child_count
        and state["plan_status"] == "completed"
        and state["plan_node_count"] >= min_plan_nodes
    ):
        return False
    return not (require_dag and state["dag_edge_count"] <= 0)


def wait_for_completion(
    client: ApiClient,
    workspace_id: str,
    root_task_id: str,
    *,
    scenario: str,
    min_children: int,
    min_plan_nodes: int,
    require_dag: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_tick_at = 0.0
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now - last_tick_at >= 20.0:
            outcome = tick(client, workspace_id)
            log(
                f"[{scenario}] tick: triggered={outcome.get('triggered')} "
                f"reason={outcome.get('reason')}"
            )
            last_tick_at = now
        tasks = list_tasks(client, workspace_id)
        plan = get_plan(client, workspace_id)
        last_state = summarize_state(tasks, plan, root_task_id)
        log(f"[{scenario}] state: {json.dumps(last_state, ensure_ascii=False)}")
        if is_scenario_done(
            last_state,
            min_children=min_children,
            min_plan_nodes=min_plan_nodes,
            require_dag=require_dag,
        ):
            return {"state": last_state, "tasks": tasks, "plan": plan}
        time.sleep(5)
    raise RuntimeError(f"{scenario} did not complete before timeout. Last state: {last_state}")


def run_scenario(
    client: ApiClient,
    *,
    tenant_id: str,
    project_id: str,
    agent_id: str,
    suffix: str,
    title: str,
    description: str,
    min_children: int,
    min_plan_nodes: int,
    require_dag: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    workspace_id = create_workspace(client, tenant_id, project_id, suffix)
    binding_id = bind_worker(client, tenant_id, project_id, workspace_id, agent_id, suffix)
    root_task_id = create_root_task(
        client,
        workspace_id,
        title=title,
        description=description,
        scenario=suffix,
    )
    log(f"[{suffix}] workspace={workspace_id} worker_binding={binding_id} root_task={root_task_id}")
    result = wait_for_completion(
        client,
        workspace_id,
        root_task_id,
        scenario=suffix,
        min_children=min_children,
        min_plan_nodes=min_plan_nodes,
        require_dag=require_dag,
        timeout_seconds=timeout_seconds,
    )
    result["workspace_id"] = workspace_id
    result["root_task_id"] = root_task_id
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--username", default=os.getenv("E2E_USERNAME", DEFAULT_USERNAME))
    parser.add_argument("--password", default=os.getenv("E2E_PASSWORD", DEFAULT_PASSWORD))
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument(
        "--scenario",
        choices=("simple", "complex", "both"),
        default="both",
    )
    args = parser.parse_args()

    client = ApiClient(args.base_url)
    login(client, args.username, args.password)
    tenant_id, project_id = pick_scope(client)
    provider_name = configure_llm_provider(client, tenant_id)
    if provider_name:
        log(f"Using tenant LLM provider: {provider_name}")
    else:
        log("No active chat provider was selected; using existing tenant/default provider")

    unique = str(int(time.time()))
    agent_id = create_worker_definition(client, project_id, unique)
    log(f"Created worker definition: {agent_id}")

    results: dict[str, Any] = {}
    if args.scenario in {"simple", "both"}:
        results["simple"] = run_scenario(
            client,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
            suffix=f"simple-{unique}",
            title="E2E simple autonomy goal",
            description=(
                "Create a concise release-readiness checklist. Decompose it into one "
                "bounded execution task, dispatch it to the workspace worker, gather the "
                "worker evidence, and close the root goal when complete."
            ),
            min_children=1,
            min_plan_nodes=2,
            require_dag=False,
            timeout_seconds=args.timeout,
        )

    if args.scenario in {"complex", "both"}:
        results["complex"] = run_scenario(
            client,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
            suffix=f"complex-{unique}",
            title="E2E medium development task with DAG delivery",
            description=(
                "Complete an E2E simulated medium-complexity frontend development deliverable: "
                "a typed feature-flag utility for React/TypeScript. Do not modify repository "
                "files during this E2E run; complete the deliverable through worker reports. "
                "The leader must plan a DAG with at least four dependent child tasks: "
                "requirements/API contract, core implementation, tests, and documentation/review. "
                "Dispatch the executable tasks to workers. Each worker report must include "
                "concrete code snippets, test cases, artifact references, and verification notes. "
                "Close the root only after all child tasks and the durable plan are complete."
            ),
            min_children=4,
            min_plan_nodes=5,
            require_dag=True,
            timeout_seconds=args.timeout,
        )

    log("E2E PASS")
    log(json.dumps({key: value["state"] for key, value in results.items()}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"E2E FAIL: {exc}", file=sys.stderr)
        raise
