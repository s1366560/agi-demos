#!/usr/bin/env python3
"""Fail-closed live HTTP/Core/Ray gate for the Avernet Agent Runtime bridge."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

_PROVIDER_EVENT_NAMESPACE = uuid.UUID("3f0936e7-2634-44a6-b299-0d5ba2819652")
_WORKSPACE_PROVIDER_ID = "memstack-workspace-agent-runtime"
_DEFAULT_TIMEOUT_SECONDS = 180.0
_DEFAULT_POLL_SECONDS = 0.5
_DEFAULT_ABORT_DELAY_SECONDS = 0.25

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class LiveAgentE2EError(RuntimeError):
    """A release-grade live check could not be completed."""

    def __init__(self, blockers: list[dict[str, str]]) -> None:
        super().__init__("live Agent E2E is blocked")
        self.blockers = blockers


@dataclass(frozen=True, slots=True)
class LiveAgentE2EConfig:
    """Non-secret scope plus environment-only credentials for one live run."""

    api_base_url: str
    core_base_url: str
    ray_dashboard_url: str
    provider_webhook_token: str
    core_service_token: str
    tenant_id: str
    project_id: str
    workspace_id: str
    user_id: str
    agent_id: str
    provider_id: str
    task_id: str | None
    abort_message: str
    evidence_output: Path
    run_id: str
    conversation_id: str
    group_id: str
    session_id: str
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    poll_seconds: float = _DEFAULT_POLL_SECONDS
    abort_delay_seconds: float = _DEFAULT_ABORT_DELAY_SECONDS

    @classmethod
    def from_environment(
        cls,
        *,
        evidence_output: Path,
        environ: Mapping[str, str] = os.environ,
    ) -> LiveAgentE2EConfig:
        aliases = {
            "core_base_url": ("WORKSPACE_E2E_CORE_BASE_URL", "WORKSPACE_CORE_BASE_URL"),
            "provider_webhook_token": (
                "WORKSPACE_E2E_PROVIDER_WEBHOOK_TOKEN",
                "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN",
            ),
            "core_service_token": (
                "WORKSPACE_E2E_CORE_SERVICE_TOKEN",
                "WORKSPACE_CORE_SERVICE_TOKEN",
            ),
        }
        direct = {
            "tenant_id": "WORKSPACE_E2E_TENANT_ID",
            "project_id": "WORKSPACE_E2E_PROJECT_ID",
            "workspace_id": "WORKSPACE_E2E_WORKSPACE_ID",
            "user_id": "WORKSPACE_E2E_USER_ID",
            "agent_id": "WORKSPACE_E2E_AGENT_ID",
            "provider_id": "WORKSPACE_E2E_PROVIDER_ID",
            "group_id": "WORKSPACE_E2E_GROUP_ID",
            "session_id": "WORKSPACE_E2E_SESSION_ID",
            "abort_message": "WORKSPACE_E2E_ABORT_MESSAGE",
        }
        values: dict[str, str] = {}
        missing: list[str] = []
        for field_name, variable_names in aliases.items():
            value = next(
                (environ[name].strip() for name in variable_names if environ.get(name, "").strip()),
                "",
            )
            if not value:
                missing.append(" or ".join(variable_names))
            values[field_name] = value
        for field_name, variable_name in direct.items():
            value = environ.get(variable_name, "").strip()
            if not value:
                missing.append(variable_name)
            values[field_name] = value
        if missing:
            raise LiveAgentE2EError(
                [
                    {
                        "code": "missing_environment",
                        "detail": f"required environment is unset: {name}",
                    }
                    for name in missing
                ]
            )
        if values["provider_id"] != _WORKSPACE_PROVIDER_ID:
            raise LiveAgentE2EError(
                [
                    {
                        "code": "invalid_provider_identity",
                        "detail": (f"WORKSPACE_E2E_PROVIDER_ID must be {_WORKSPACE_PROVIDER_ID}"),
                    }
                ]
            )

        run_id = environ.get("WORKSPACE_E2E_RUN_ID", "").strip() or f"live-{uuid.uuid4()}"
        conversation_id = environ.get("WORKSPACE_E2E_CONVERSATION_ID", "").strip()
        if not conversation_id:
            conversation_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"workspace:{values['workspace_id']}:agent:{values['agent_id']}",
                )
            )
        return cls(
            **values,
            task_id=environ.get("WORKSPACE_E2E_TASK_ID", "").strip() or None,
            api_base_url=environ.get("WORKSPACE_E2E_API_BASE_URL", "http://127.0.0.1:8000").strip(),
            ray_dashboard_url=environ.get(
                "WORKSPACE_E2E_RAY_DASHBOARD_URL", "http://127.0.0.1:8265"
            ).strip(),
            evidence_output=evidence_output,
            run_id=run_id,
            conversation_id=conversation_id,
            timeout_seconds=_positive_float(
                environ.get("WORKSPACE_E2E_TIMEOUT_SECONDS"),
                default=_DEFAULT_TIMEOUT_SECONDS,
                name="WORKSPACE_E2E_TIMEOUT_SECONDS",
            ),
            poll_seconds=_positive_float(
                environ.get("WORKSPACE_E2E_POLL_SECONDS"),
                default=_DEFAULT_POLL_SECONDS,
                name="WORKSPACE_E2E_POLL_SECONDS",
            ),
            abort_delay_seconds=_positive_float(
                environ.get("WORKSPACE_E2E_ABORT_DELAY_SECONDS"),
                default=_DEFAULT_ABORT_DELAY_SECONDS,
                name="WORKSPACE_E2E_ABORT_DELAY_SECONDS",
            ),
        )


def _positive_float(raw: str | None, *, default: float, name: str) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise LiveAgentE2EError(
            [{"code": "invalid_environment", "detail": f"{name} must be numeric"}]
        ) from error
    if not value > 0:
        raise LiveAgentE2EError(
            [{"code": "invalid_environment", "detail": f"{name} must be positive"}]
        )
    return value


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _provider_correlation_id(request_id: str) -> str:
    return str(uuid.uuid5(_PROVIDER_EVENT_NAMESPACE, f"correlation:{request_id}"))


def _provider_payload(
    config: LiveAgentE2EConfig,
    *,
    method: str,
    request_id: str,
    message: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    extensions = {
        "tenant_id": config.tenant_id,
        "project_id": config.project_id,
        "workspace_id": config.workspace_id,
        "user_id": config.user_id,
        "conversation_id": config.conversation_id,
    }
    if config.task_id is not None:
        extensions["task_id"] = config.task_id
    return {
        "type": "req",
        "id": request_id,
        "method": method,
        "run_id": run_id,
        "session_id": config.session_id,
        "bcn_group_id": config.group_id,
        "to_bot": {
            "provider_id": config.provider_id,
            "provider_bot_ref": config.agent_id,
        },
        "message": {"content": [{"type": "text", "text": message}]},
        "limit": 200 if method == "chat.history" else None,
        "timeout_ms": int(config.timeout_seconds * 1000),
        "extensions": extensions,
    }


async def _json_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
    params: Mapping[str, str] | None = None,
) -> tuple[int, object]:
    response = await client.request(method, url, headers=headers, json=payload, params=params)
    body: object
    try:
        body = cast("object", response.json())
    except json.JSONDecodeError:
        body = {}
    return response.status_code, body


def _as_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return cast("Mapping[str, Any]", value)


def _as_mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [cast("Mapping[str, Any]", item) for item in items if isinstance(item, Mapping)]


async def _workspace_projection_preflight(
    config: LiveAgentE2EConfig,
    client: httpx.AsyncClient,
    core_headers: Mapping[str, str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    checks: dict[str, Any] = {}
    blockers: list[dict[str, str]] = []
    scope_path = (
        f"{config.core_base_url.rstrip('/')}/api/v1/tenants/{config.tenant_id}"
        f"/projects/{config.project_id}/workspaces/{config.workspace_id}"
    )
    scope_headers = {
        **core_headers,
        "X-MemStack-User-ID": config.user_id,
        "X-MemStack-User-Is-Superuser": "false",
    }
    raw_workspace: object
    try:
        status, raw_workspace = await _json_request(
            client,
            "GET",
            scope_path,
            headers=scope_headers,
        )
    except httpx.HTTPError:
        status = 0
        raw_workspace = cast("object", {})
    workspace = _as_mapping(raw_workspace)
    workspace_projection_ok = (
        status == 200
        and workspace.get("id") == config.workspace_id
        and workspace.get("tenant_id") == config.tenant_id
        and workspace.get("project_id") == config.project_id
    )
    checks["workspace_projection"] = {
        "ok": workspace_projection_ok,
        "status": status,
    }
    if not workspace_projection_ok:
        blockers.append(
            {
                "code": "workspace_projection",
                "detail": "Workspace Core scope does not match the requested live projection",
            }
        )

    raw_agents: object
    try:
        status, raw_agents = await _json_request(
            client,
            "GET",
            f"{scope_path}/agents",
            headers=scope_headers,
            params={"active_only": "true", "limit": "100", "offset": "0"},
        )
    except httpx.HTTPError:
        status = 0
        raw_agents = cast("object", [])
    agents = _as_mapping_list(raw_agents)
    agent_projection_ok = status == 200 and any(
        item.get("workspace_id") == config.workspace_id
        and item.get("agent_id") == config.agent_id
        and item.get("is_active") is True
        for item in agents
    )
    checks["agent_projection"] = {
        "ok": agent_projection_ok,
        "status": status,
    }
    if not agent_projection_ok:
        blockers.append(
            {
                "code": "agent_projection",
                "detail": "Workspace Core has no matching active Agent projection",
            }
        )

    projection_scope_ok = (
        config.group_id == config.workspace_id and config.session_id == config.workspace_id
    )
    checks["workspace_projection_scope"] = {
        "ok": projection_scope_ok,
        "groupMatchesWorkspace": config.group_id == config.workspace_id,
        "sessionMatchesWorkspace": config.session_id == config.workspace_id,
    }
    if not projection_scope_ok:
        blockers.append(
            {
                "code": "workspace_projection_scope",
                "detail": "BCS group and session must match the migrated Workspace projection",
            }
        )
    return checks, blockers


async def _preflight(
    config: LiveAgentE2EConfig,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    checks: dict[str, Any] = {}
    probes = (
        ("api_health", f"{config.api_base_url.rstrip('/')}/health", None),
        ("core_health", f"{config.core_base_url.rstrip('/')}/health", None),
    )
    for name, url, headers in probes:
        raw_body: object
        try:
            status, raw_body = await _json_request(client, "GET", url, headers=headers)
        except httpx.HTTPError:
            status = 0
            raw_body = cast("object", {})
        body = _as_mapping(raw_body)
        valid = status == 200 and body.get("status") == "ok"
        if name == "core_health":
            valid = valid and str(body.get("version", "")).startswith("memstack-workspace-core/")
        checks[name] = {"ok": valid, "status": status}
        if not valid:
            blockers.append({"code": name, "detail": f"{name} did not return its live contract"})

    core_headers = {"Authorization": f"Bearer {config.core_service_token}"}
    raw_capabilities: object
    try:
        status, raw_capabilities = await _json_request(
            client,
            "GET",
            f"{config.core_base_url.rstrip('/')}/internal/v1/capabilities/workspace-public-api",
            headers=core_headers,
        )
    except httpx.HTTPError:
        status = 0
        raw_capabilities = cast("object", {})
    capabilities = _as_mapping(raw_capabilities)
    complete = status == 200 and capabilities.get("complete") is True
    checks["core_capabilities"] = {
        "ok": complete,
        "status": status,
        "implementedRouteCount": capabilities.get("implemented_route_count"),
        "requiredRouteCount": capabilities.get("required_route_count"),
    }
    if not complete:
        blockers.append(
            {
                "code": "core_capabilities",
                "detail": "Workspace Core did not declare a complete public API contract",
            }
        )

    projection_checks, projection_blockers = await _workspace_projection_preflight(
        config,
        client,
        core_headers,
    )
    checks.update(projection_checks)
    blockers.extend(projection_blockers)

    jobs_body: object
    try:
        status, jobs_body = await _json_request(
            client,
            "GET",
            f"{config.ray_dashboard_url.rstrip('/')}/api/jobs/",
        )
    except httpx.HTTPError:
        status = 0
        jobs_body = cast("object", {})
    jobs = _as_mapping_list(jobs_body)
    running_jobs = [
        item
        for item in jobs
        if item.get("status") == "RUNNING"
        and "src.agent_actor_worker" in str(item.get("entrypoint", ""))
    ]
    checks["ray_actor_worker"] = {
        "ok": status == 200 and bool(running_jobs),
        "status": status,
        "runningJobCount": len(running_jobs),
    }
    if not checks["ray_actor_worker"]["ok"]:
        blockers.append(
            {
                "code": "ray_actor_worker",
                "detail": "Ray has no running src.agent_actor_worker driver",
            }
        )
    if blockers:
        raise LiveAgentE2EError(blockers)
    return checks


async def _provider_call(
    config: LiveAgentE2EConfig,
    client: httpx.AsyncClient,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    status, raw_body = await _json_request(
        client,
        "POST",
        f"{config.api_base_url.rstrip('/')}/internal/v1/workspace-core/provider",
        headers={"Authorization": f"Bearer {config.provider_webhook_token}"},
        payload=payload,
    )
    body = _as_mapping(raw_body)
    if status != 200 or body.get("ok") is not True:
        method = str(payload.get("method", "provider request"))
        raise LiveAgentE2EError(
            [
                {
                    "code": "provider_request_failed",
                    "detail": f"{method} failed with HTTP {status}",
                }
            ]
        )
    return body


async def _wait_for_terminal(
    config: LiveAgentE2EConfig,
    client: httpx.AsyncClient,
    request_id: str,
    *,
    expected_status: str = "completed",
    expected_provider_state: str = "final",
    expected_legacy_event_type: str = "complete",
    clock: Clock,
    sleep: Sleep,
) -> Mapping[str, Any]:
    correlation_id = _provider_correlation_id(request_id)
    deadline = clock() + config.timeout_seconds
    path = (
        f"{config.core_base_url.rstrip('/')}/internal/v1/runtime-correlations/"
        f"{correlation_id}/terminal"
    )
    while clock() < deadline:
        status, raw_body = await _json_request(
            client,
            "GET",
            path,
            headers={
                "Authorization": f"Bearer {config.core_service_token}",
                "X-MemStack-Tenant-ID": config.tenant_id,
            },
            params={"project_id": config.project_id, "workspace_id": config.workspace_id},
        )
        if status == 404:
            await sleep(config.poll_seconds)
            continue
        body = _as_mapping(raw_body)
        report_data = _as_mapping(body.get("report"))
        legacy_data = _as_mapping(report_data.get("legacy_event"))
        valid = (
            status == 200
            and body.get("persisted") is True
            and body.get("status") == expected_status
            and bool(body.get("outbox_id"))
            and bool(body.get("terminal_message_id"))
            and bool(body.get("terminal_event_id"))
            and report_data.get("provider_state") == expected_provider_state
            and legacy_data.get("event_type") == expected_legacy_event_type
        )
        if not valid:
            raise LiveAgentE2EError(
                [
                    {
                        "code": "terminal_contract",
                        "detail": f"terminal proof failed its durable contract with HTTP {status}",
                    }
                ]
            )
        return body
    raise LiveAgentE2EError(
        [{"code": "terminal_timeout", "detail": "terminal proof was not durable before timeout"}]
    )


async def _history(
    config: LiveAgentE2EConfig,
    client: httpx.AsyncClient,
    request_id: str,
) -> list[Mapping[str, Any]]:
    body = await _provider_call(
        config,
        client,
        _provider_payload(config, method="chat.history", request_id=request_id),
    )
    messages = _as_mapping_list(body.get("messages"))
    if not messages:
        raise LiveAgentE2EError(
            [{"code": "history_empty", "detail": "chat.history returned no durable messages"}]
        )
    return messages


async def run_live_agent_e2e(
    config: LiveAgentE2EConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Clock = time.perf_counter,
    sleep: Sleep = asyncio.sleep,
) -> dict[str, Any]:
    """Exercise real HTTP/Core/Ray paths and emit evidence only after every gate passes."""

    if config.evidence_output.exists():
        raise LiveAgentE2EError(
            [{"code": "evidence_exists", "detail": "evidence output already exists"}]
        )
    timeout = httpx.Timeout(config.timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        preflight = await _preflight(config, client)
        first_id = f"{config.run_id}-initial"
        followup_id = f"{config.run_id}-followup"
        abort_id = f"{config.run_id}-abort"

        _ = await _provider_call(
            config,
            client,
            _provider_payload(
                config,
                method="chat.send",
                request_id=first_id,
                message=f"Workspace live E2E {config.run_id}: reply with a short acknowledgement.",
            ),
        )
        first_terminal = await _wait_for_terminal(
            config, client, first_id, clock=clock, sleep=sleep
        )
        _ = await _provider_call(
            config,
            client,
            _provider_payload(
                config,
                method="chat.inject",
                request_id=f"{config.run_id}-inject",
                message=f"Durable injected context for {config.run_id}.",
            ),
        )
        followup_payload = _provider_payload(
            config,
            method="chat.send",
            request_id=followup_id,
            message=f"Workspace live E2E follow-up {config.run_id}: acknowledge the context.",
        )
        _ = await _provider_call(config, client, followup_payload)
        followup_terminal = await _wait_for_terminal(
            config, client, followup_id, clock=clock, sleep=sleep
        )
        history_before = await _history(config, client, f"{config.run_id}-history-before")
        _ = await _provider_call(config, client, followup_payload)
        await sleep(config.poll_seconds)
        history_after = await _history(config, client, f"{config.run_id}-history-after")
        if history_after != history_before:
            raise LiveAgentE2EError(
                [
                    {
                        "code": "duplicate_side_effect",
                        "detail": "duplicate chat.send changed durable Agent history",
                    }
                ]
            )

        _ = await _provider_call(
            config,
            client,
            _provider_payload(
                config,
                method="chat.send",
                request_id=abort_id,
                message=config.abort_message,
            ),
        )
        await sleep(config.abort_delay_seconds)
        abort = await _provider_call(
            config,
            client,
            _provider_payload(
                config,
                method="chat.abort",
                request_id=f"{abort_id}-request",
                run_id=abort_id,
            ),
        )
        ray_cancelled = abort.get("ray_cancelled") is True
        local_cancelled = abort.get("local_worker_cancelled") is True
        if not (ray_cancelled or local_cancelled):
            raise LiveAgentE2EError(
                [
                    {
                        "code": "active_abort_not_observed",
                        "detail": "chat.abort did not cancel an active Ray or local execution",
                    }
                ]
            )
        abort_terminal = await _wait_for_terminal(
            config,
            client,
            abort_id,
            expected_status="aborted",
            expected_provider_state="aborted",
            expected_legacy_event_type="cancelled",
            clock=clock,
            sleep=sleep,
        )

    evidence = {
        "schemaVersion": "workspace-live-agent-e2e-v1",
        "ok": True,
        "evidenceClass": "live-http-core-ray" if transport is None else "transport-contract",
        "liveEvidence": transport is None,
        "runId": config.run_id,
        "scope": {
            "tenantId": config.tenant_id,
            "projectId": config.project_id,
            "workspaceId": config.workspace_id,
            "conversationId": config.conversation_id,
            "agentId": config.agent_id,
            "taskId": config.task_id,
        },
        "preflight": preflight,
        "terminalProofs": [
            {
                "correlationId": first_terminal["correlation_id"],
                "outboxId": first_terminal["outbox_id"],
                "reportSha256": first_terminal["report_hash"],
            },
            {
                "correlationId": followup_terminal["correlation_id"],
                "outboxId": followup_terminal["outbox_id"],
                "reportSha256": followup_terminal["report_hash"],
            },
            {
                "correlationId": abort_terminal["correlation_id"],
                "outboxId": abort_terminal["outbox_id"],
                "reportSha256": abort_terminal["report_hash"],
            },
        ],
        "injectionBeforeFollowup": True,
        "history": {
            "messageCount": len(history_after),
            "contentSha256": _canonical_hash(history_after),
            "duplicateDeliveryStable": True,
        },
        "abort": {
            "activeCancellationObserved": True,
            "rayCancelled": ray_cancelled,
            "localWorkerCancelled": local_cancelled,
        },
        "credentialMaterialRecorded": False,
    }
    config.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.evidence_output.with_name(f".{config.evidence_output.name}.tmp")
    try:
        _ = temporary.write_text(
            f"{json.dumps(evidence, sort_keys=True, separators=(',', ':'))}\n",
            encoding="utf-8",
        )
        os.replace(temporary, config.evidence_output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--evidence-output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = LiveAgentE2EConfig.from_environment(evidence_output=args.evidence_output)
        evidence = asyncio.run(run_live_agent_e2e(config))
    except (LiveAgentE2EError, httpx.HTTPError, OSError) as error:
        blockers = (
            error.blockers
            if isinstance(error, LiveAgentE2EError)
            else [{"code": "live_request_failed", "detail": type(error).__name__}]
        )
        print(
            json.dumps(
                {"ok": False, "evidenceClass": "none", "blockers": blockers},
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "evidenceClass": evidence["evidenceClass"],
                "historyMessageCount": evidence["history"]["messageCount"],
                "terminalProofCount": len(evidence["terminalProofs"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
