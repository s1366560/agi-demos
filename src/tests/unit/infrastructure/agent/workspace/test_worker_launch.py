"""Unit tests for src.infrastructure.agent.workspace.worker_launch (P3 M-bug)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest

from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.workspace import worker_launch as wl
from src.infrastructure.agent.workspace.code_context import (
    AgentsInstructionFile,
    WorkspaceCodeContext,
)
from src.infrastructure.workspace_core.legacy_runtime import LegacyWorkspaceRuntimeRetiredError


def _make_task(
    *,
    task_id: str = "task-1",
    workspace_id: str = "ws-1",
    title: str = "Build report",
    description: str | None = "Render quarterly stats",
    metadata: dict | None = None,
) -> WorkspaceTask:
    return WorkspaceTask(
        id=task_id,
        workspace_id=workspace_id,
        title=title,
        description=description,
        created_by="user-1",
        status=WorkspaceTaskStatus.TODO,
        metadata=metadata or {"task_role": "execution_task", "root_goal_task_id": "root-1"},
    )


class TestConversationScope:
    def test_without_attempt(self) -> None:
        assert wl._conversation_scope_for_task("t1") == "task:t1"

    def test_with_attempt(self) -> None:
        assert wl._conversation_scope_for_task("t1", "att-9") == "task:t1:attempt:att-9"


class TestConversationId:
    def test_deterministic_and_distinct_per_scope(self) -> None:
        a = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-X", task_id="t1"
        )
        b = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-X", task_id="t1"
        )
        c = wl._conversation_id_for_worker(
            workspace_id="w",
            worker_agent_id="agent-X",
            task_id="t1",
            attempt_id="att-9",
        )
        assert a == b
        assert a != c
        # UUIDv5 length
        assert len(a) == 36

    def test_distinct_per_agent(self) -> None:
        a = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-A", task_id="t1"
        )
        b = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-B", task_id="t1"
        )
        assert a != b


class TestStreamCompletionFallback:
    def test_terminal_report_metadata_must_match_current_attempt(self) -> None:
        metadata = {
            "last_worker_report_attempt_id": "attempt-1",
            "last_worker_report_type": "completed",
        }

        assert wl._terminal_report_metadata_matches_attempt(
            metadata,
            attempt_id="attempt-1",
            report_type="completed",
        )
        assert not wl._terminal_report_metadata_matches_attempt(
            metadata,
            attempt_id="attempt-2",
            report_type="completed",
        )
        assert not wl._terminal_report_metadata_matches_attempt(
            metadata,
            attempt_id="attempt-1",
            report_type="blocked",
        )


class TestBuildBrief:
    def test_includes_binding_block_and_title(self) -> None:
        task = _make_task(
            metadata={
                "task_role": "execution_task",
                "root_goal_task_id": "root-1",
                "workspace_agent_binding_id": "binding-1",
            }
        )
        brief = wl._build_worker_brief(
            workspace_id="ws-1",
            task=task,
            attempt_id=None,
            leader_agent_id="leader-1",
        )
        assert "[workspace-task-binding]" in brief
        assert "workspace_id=ws-1" in brief
        assert "workspace_task_id=task-1" in brief
        assert "workspace_agent_binding_id=binding-1" in brief
        assert "root_goal_task_id=root-1" in brief
        assert "leader_agent_id=leader-1" in brief
        assert "## Task title" in brief
        assert "Build report" in brief
        assert "Render quarterly stats" in brief
        assert "## Completion gate" in brief
        assert "## Shell execution discipline" in brief
        assert "nohup" in brief
        assert "bare background commands" in brief
        assert "logs/backend.pid" in brief
        assert "Do not assume `ss` exists" in brief
        assert "preflight:read-progress" in brief
        assert "preflight:git-status" in brief
        assert "git status --short" in brief
        assert "stage intended untracked files" in brief

    def test_omits_attempt_when_none(self) -> None:
        task = _make_task()
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id=None,
            leader_agent_id=None,
        )
        assert "attempt_id=" not in brief

    def test_includes_attempt_and_extra(self) -> None:
        task = _make_task()
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            extra_instructions="Be brief.",
        )
        assert "attempt_id=att-2" in brief
        assert "Additional instructions" not in brief
        assert "Be brief." not in brief

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            extra_instructions="Be brief.",
            preferred_language="en-US",
        )
        assert system_context["workspace_binding"]["attempt_id"] == "att-2"
        assert system_context["preferred_language"] == "en-US"
        assert system_context["additional_instructions"] == "Be brief."
        assert "workspace_root_override" not in system_context
        assert "native tool-call" in system_context["tool_protocol"]["instruction"]
        reporting = system_context["reporting"]
        assert reporting["completion_contract"]["required_verification_refs"] == [
            "preflight:read-progress",
            "preflight:git-status",
        ]
        assert "git_diff_summary" in reporting["completion_contract"]["required_change_evidence"]
        assert "workspace_report_complete" in reporting["completion_contract"]["example"]
        assert "preflight:read-progress" in " ".join(reporting["instructions"])
        assert "commit_ref" in " ".join(reporting["instructions"])
        assert "git status --short" in " ".join(reporting["instructions"])
        assert "untracked file" in " ".join(reporting["instructions"])
        quality_policy = system_context["code_quality_policy"]
        assert quality_policy["source"] == "workspace_generic_quality_gate"
        quality_instructions = " ".join(quality_policy["instructions"])
        assert "frontend/backend" in quality_instructions
        assert "hard acceptance criteria" in quality_instructions
        assert "hashes or prefixes" in quality_instructions
        assert "git diff" in quality_instructions
        assert "project_guidance:checked" in quality_instructions
        assert "preserve assertion strength" in quality_instructions
        assert "git add -A" in quality_instructions
        assert "unrelated changes" in quality_instructions
        assert (
            system_context["artifact_write_policy"]["max_single_write_chars"]
            == wl.WORKER_MAX_SINGLE_WRITE_CHARS
        )
        assert (
            system_context["artifact_write_policy"]["max_single_bash_command_chars"]
            == wl.WORKER_MAX_SINGLE_BASH_COMMAND_CHARS
        )
        assert "smaller chunks" in " ".join(system_context["artifact_write_policy"]["instructions"])
        assert "giant heredoc" in " ".join(system_context["artifact_write_policy"]["instructions"])
        shell_instructions = " ".join(system_context["shell_execution_policy"]["instructions"])
        assert "nohup" in shell_instructions
        assert "bare background command" in shell_instructions
        assert "stdin from /dev/null" in shell_instructions
        assert "worktree-local pid file" in shell_instructions
        assert "playwright install --with-deps" in shell_instructions
        assert "port is already in use" in shell_instructions
        assert "stop the stale PID" in shell_instructions
        assert "E2E_BASE_URL" in shell_instructions
        assert "empty string" in shell_instructions
        assert "ss" in shell_instructions

    def test_brief_surfaces_latest_platform_pipeline_evidence(self) -> None:
        task = _make_task()
        plan_node_metadata = {
            "iteration_phase": "review",
            "pipeline_failed_stage": "workspace-ci/deploy",
            "pipeline_failure_summary": "Drone build #83 failed with stale network cleanup",
            "latest_workspace_pipeline_evidence": {
                "id": "run-141",
                "provider": "drone",
                "status": "success",
                "commit_ref": "1b2d86b",
                "reason": "harness-native CI/CD pipeline passed",
                "metadata": {
                    "external_id": "s1366560/my-evo#141",
                    "external_url": "http://localhost:8080/s1366560/my-evo/141",
                    "drone_status": "success",
                    "deployment_status": "deployed",
                    "deploy_validation": "explicit_deploy_step_v1",
                },
            },
        }

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata=plan_node_metadata,
        )
        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata=plan_node_metadata,
        )

        assert "## Latest platform pipeline evidence" in brief
        assert "Pipeline run: `run-141`" in brief
        assert "Status: `success`" in brief
        assert "External run: `s1366560/my-evo#141`" in brief
        assert "Deployment status: `deployed`" in brief
        assert "Older pipeline_failure_summary" in brief
        assert "Drone build #83 failed" not in brief
        assert system_context["latest_workspace_pipeline_evidence"]["id"] == "run-141"

    def test_renders_repair_turn_prompt_without_worktree_override(self) -> None:
        task = _make_task()
        repair_prompt = (
            "[repair-turn]\n"
            "{\n"
            '  "repair_brief": {\n'
            '    "required_next_action": "Fix Drone deploy startup failure",\n'
            '    "failed_items": ["drone_docker_deploy_unhealthy_container"]\n'
            "  }\n"
            "}\n"
            "[/repair-turn]\n"
        )

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            extra_instructions=repair_prompt,
        )

        assert "## Repair turn instructions - highest priority" in brief
        assert "Fix Drone deploy startup failure" in brief
        assert "drone_docker_deploy_unhealthy_container" in brief
        assert "Address the listed verification failures" in brief
        assert "## Workspace checkpoint and worktree" not in brief

    def test_deploy_phase_exposes_disabled_drone_deploy_context(self) -> None:
        task = _make_task()
        workspace_metadata = {
            "sandbox_code_root": "/workspace/my-evo",
            "delivery_cicd": {
                "provider": "drone",
                "code_root": "/workspace/my-evo",
                "auto_deploy": False,
                "services": [
                    {
                        "service_id": "backend",
                        "name": "evomap-backend",
                        "start_command": "docker compose up -d backend",
                        "internal_port": 3001,
                        "health_path": "/health",
                        "required": True,
                    },
                    {
                        "service_id": "frontend",
                        "name": "evomap-frontend",
                        "start_command": "docker compose up -d frontend",
                        "internal_port": 3000,
                        "health_path": "/",
                        "required": True,
                    },
                ],
                "drone": {
                    "repo": "s1366560/my-evo",
                    "branch": "main",
                    "deploy": {
                        "enabled": False,
                        "mode": "cli",
                        "stage": "deploy",
                        "docker": {
                            "deploy_host_port": 18080,
                            "deploy_strategy": "local_build",
                            "reserved_host_ports": [3000, 3001, 5001],
                        },
                    },
                },
            },
        }

        deploy_brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-deploy",
            leader_agent_id="L",
            workspace_metadata=workspace_metadata,
            plan_node_metadata={"iteration_phase": "deploy"},
        )
        deploy_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-deploy",
            leader_agent_id="L",
            workspace_metadata=workspace_metadata,
            plan_node_metadata={"iteration_phase": "deploy"},
        )
        implement_brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-impl",
            leader_agent_id="L",
            workspace_metadata=workspace_metadata,
            plan_node_metadata={"iteration_phase": "implement"},
        )

        assert deploy_context["delivery_cicd"]["deploy"]["enabled"] is True
        assert "Deploy mode: cli" in deploy_brief
        assert "Deploy stage: `deploy`" in deploy_brief
        assert "Docker deploy host port: `18080`" in deploy_brief
        assert "Docker deploy services:" in deploy_brief
        assert "backend (evomap-backend)" in deploy_brief
        assert "port: `18080:3001`" in deploy_brief
        assert "frontend (evomap-frontend)" in deploy_brief
        assert "port: `18081:3000`" in deploy_brief
        assert "Drone step health: `http://host.docker.internal:18080/health`" in deploy_brief
        assert "Drone step health: `http://host.docker.internal:18081/`" in deploy_brief
        assert "Drone step health: `http://host.docker.internal:3001/health`" not in deploy_brief
        assert "Drone step health: `http://host.docker.internal:3000/`" not in deploy_brief
        assert "Reserved Docker host ports: 3000, 3001, 5001" in deploy_brief
        deploy_services = deploy_context["delivery_cicd"]["deploy"]["docker"]["deploy_services"]
        assert deploy_services[0]["deploy_port_mapping"] == "18080:3001"
        assert deploy_services[1]["deploy_port_mapping"] == "18081:3000"
        assert "Deploy mode: cli" not in implement_brief

    def test_includes_drone_docker_delivery_contract(self) -> None:
        task = _make_task()
        workspace_metadata = {
            "sandbox_code_root": "/workspace/my-evo",
            "delivery_cicd": {
                "provider": "drone",
                "code_root": "/workspace/my-evo",
                "auto_deploy": True,
                "services": [
                    {
                        "service_id": "my-evo-app",
                        "name": "my-evo Application",
                        "start_command": "docker run -p 8080:8080 localhost:5001/my-evo",
                        "internal_port": 8080,
                        "health_path": "/api/health",
                        "required": True,
                        "auto_open": True,
                    }
                ],
                "drone": {
                    "repo": "s1366560/my-evo",
                    "branch": "main",
                    "server_url_env": "DRONE_SERVER_URL",
                    "token_env": "DRONE_TOKEN",
                    "deploy": {
                        "enabled": True,
                        "mode": "docker",
                        "stage": "deploy",
                        "docker": {
                            "image": "localhost:5001/my-evo",
                            "registry": "localhost:5001",
                            "dockerfile": "Dockerfile",
                            "tags": ["drone-docker-e2e"],
                        },
                    },
                },
            },
        }
        node_metadata = {"iteration_phase": "deploy"}

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            workspace_metadata=workspace_metadata,
            plan_node_metadata=node_metadata,
        )
        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            workspace_metadata=workspace_metadata,
            plan_node_metadata=node_metadata,
        )

        assert "## Workspace delivery CI/CD contract" in brief
        assert "Provider: drone" in brief
        assert "Deploy mode: docker" in brief
        for expected in (
            "Docker image: `localhost:5001/my-evo`",
            "Docker image (Drone runner): `host.docker.internal:5001/my-evo`",
            "Docker image (host Docker deploy): `localhost:5001/my-evo`",
            "Docker image (deploy local tag): `my-evo:drone-docker-e2e`",
            "Docker deploy strategy: `local_build`",
            "Docker deploy local build command: "
            "`docker build -t my-evo:drone-docker-e2e -f Dockerfile .`",
            "Docker deploy host port: `18080`",
            "Docker deploy container port: `8080`",
            "Docker deploy port mapping: `18080:8080`",
            "Docker deploy health URL: `http://host.docker.internal:18080/api/health`",
            "Docker deploy health check command: "
            "`wget -qO- http://host.docker.internal:18080/api/health >/dev/null`",
            "Docker deploy dependency strategy: `compose_or_sidecars`",
            "Docker deploy dependency network: `workspace-deploy`",
            "Docker deploy network create command: "
            "`docker network inspect workspace-deploy >/dev/null 2>&1 "
            "|| docker network create workspace-deploy`",
            "Docker deploy PostgreSQL sidecar image: `postgres:16-alpine`",
            "Docker deploy PostgreSQL sidecar command: "
            "`docker run -d --name <postgres-container> --network workspace-deploy "
            "-e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=<db> "
            "postgres:16-alpine`",
            "Docker deploy PostgreSQL cleanup command: "
            "`docker rm -f <postgres-container> 2>/dev/null || true`",
            "Docker deploy PostgreSQL readiness command: "
            "`for i in $(seq 1 30); do docker exec <postgres-container> "
            "pg_isready -U postgres >/dev/null 2>&1 && break || sleep 1; done`",
            "Docker deploy Redis sidecar image: `redis:7-alpine`",
            "Docker deploy Redis sidecar command: "
            "`docker run -d --name <redis-container> --network workspace-deploy "
            "redis:7-alpine`",
            "Docker deploy Redis cleanup command: "
            "`docker rm -f <redis-container> 2>/dev/null || true`",
            "Docker daemon registry pull allowed: `false`",
            "Reserved Docker host ports: 3000, 3001, 5001, 5432, 6379, 7474, 7687, 8000, 8080",
            "Docker registry (Drone runner): `host.docker.internal:5001`",
            "Docker registry (host Docker deploy): `localhost:5001`",
            "Drone Docker socket: `/var/run/docker.sock`",
            "Drone Docker socket volume: `docker-sock`",
            "Docker deploy services:",
            "container: `my-evo-app`",
            "deploy image: `my-evo:drone-docker-e2e`",
            "port: `18080:8080`",
            "plugins/docker or docker build/push alone is image publication",
            "distinct deploy step/stage named by deploy.stage",
            "Deployment services:",
            "my-evo-app (my-evo Application)",
            "docker run -p 8080:8080 localhost:5001/my-evo",
            "health: `/api/health`",
            "Drone step health: `http://host.docker.internal:18080/api/health`",
            "do not use localhost",
            "sandbox worker may not have DRONE_TOKEN",
            "platform harness can trigger and verify Drone",
            "Do not wait for source-publish or memstack-source-publish refs to auto-sync",
            "call the required workspace_report_* contract tool",
            "verify every `steps[].commands[]` item is a string",
            'echo "label: value"',
            "Keep host.docker.internal:<port> for plugins/docker build/push settings",
            "deploy-local image path",
            "docker.allow_daemon_registry_pull is false",
            "must not docker pull or docker run images from host.docker.internal:<port>",
            "replace that daemon-side pull with a deploy-local build/load plus docker run",
            "Do not set DOCKER_HOST=tcp://docker:2376",
            "do not add a docker:dind service",
            "Do not mask deployment failures",
            "health check skipped",
            "Best-effort cleanup may be limited to cleanup-only commands",
            "Treat Drone deploy repairs as cumulative",
            "preserve prior .drone.yml fixes",
            "root build steps",
            "Do not replace the deploy step with an older partial version",
            "expects compiled artifacts such as dist/index.js",
            "Add or preserve a root build step before plugins/docker",
            "Use this exact Drone socket volume shape",
            "`volumes: [{ name: docker-sock, path: /var/run/docker.sock }]`",
            "Never mount the socket to `/var/run`",
            "Do not use list syntax such as `- DOCKER_HOST=...`",
            "http://host.docker.internal:<service-port><health-path>",
            "docker.deploy_health_check_command",
            "docker:cli deploy image in this environment does not guarantee curl",
            "docker logs <container>",
            "DATABASE_URL",
            "Docker deploy must be self-contained for app runtime dependencies",
            "sidecar containers on a named Docker network",
            "remove stale containers with `docker rm -f <app-container> "
            "<postgres-container> <redis-container> 2>/dev/null || true`",
            "docker.deploy_network_create_command",
            "Do not use `docker network rm <network> || true` followed by "
            "`docker network create <network>`",
            "Do not satisfy DATABASE_URL, REDIS_URL",
            "postgresql://postgres:postgres@<postgres-container>:5432/<db>",
            "-e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=<db> "
            "postgres:16-alpine",
            "Do not put `-c POSTGRES_PASSWORD=...` after the image",
            "docker.deploy_host_port",
            "docker.deploy_health_url",
            "inspect the project Dockerfile and application routes",
            "container-side port and health path must match",
            "Docker deploy coverage must match application image coverage",
            "only starts the backend/API container is incomplete",
            "Use docker.deploy_services as the required Docker deploy inventory",
        ):
            assert expected in brief
        assert system_context["delivery_cicd"]["provider"] == "drone"
        assert system_context["delivery_cicd"]["deploy"]["mode"] == "docker"
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["image_internal"]
            == "host.docker.internal:5001/my-evo"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["registry_internal"]
            == "host.docker.internal:5001"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["image_host_docker"]
            == "localhost:5001/my-evo"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["image_deploy_local"]
            == "my-evo:drone-docker-e2e"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_strategy"] == "local_build"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["allow_daemon_registry_pull"]
            is False
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_local_build_command"]
            == "docker build -t my-evo:drone-docker-e2e -f Dockerfile ."
        )
        assert system_context["delivery_cicd"]["deploy"]["docker"]["deploy_host_port"] == 18080
        assert system_context["delivery_cicd"]["deploy"]["docker"]["container_port"] == 8080
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_port_mapping"]
            == "18080:8080"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_health_url"]
            == "http://host.docker.internal:18080/api/health"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_health_check_command"]
            == "wget -qO- http://host.docker.internal:18080/api/health >/dev/null"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_dependency_strategy"]
            == "compose_or_sidecars"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_dependency_network"]
            == "workspace-deploy"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_network_create_command"]
            == "docker network inspect workspace-deploy >/dev/null 2>&1 "
            "|| docker network create workspace-deploy"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_postgres_sidecar_image"]
            == "postgres:16-alpine"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_postgres_sidecar_command"]
            == "docker run -d --name <postgres-container> --network workspace-deploy "
            "-e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=<db> "
            "postgres:16-alpine"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_postgres_cleanup_command"]
            == "docker rm -f <postgres-container> 2>/dev/null || true"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_postgres_readiness_command"]
            == "for i in $(seq 1 30); do docker exec <postgres-container> "
            "pg_isready -U postgres >/dev/null 2>&1 && break || sleep 1; done"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_redis_sidecar_image"]
            == "redis:7-alpine"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_redis_sidecar_command"]
            == "docker run -d --name <redis-container> --network workspace-deploy redis:7-alpine"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_redis_cleanup_command"]
            == "docker rm -f <redis-container> 2>/dev/null || true"
        )
        assert 8080 in system_context["delivery_cicd"]["deploy"]["docker"]["reserved_host_ports"]
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["registry_host_docker"]
            == "localhost:5001"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["runner_docker_socket"]
            == "/var/run/docker.sock"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["runner_docker_socket_volume"]
            == "docker-sock"
        )
        assert system_context["delivery_cicd"]["drone"]["repo"] == "s1366560/my-evo"
        assert "Do not replace the configured deployment mode with a CLI smoke check" in " ".join(
            system_context["delivery_cicd"]["instructions"]
        )
        assert "plugins/docker or docker build/push alone is image publication" in " ".join(
            system_context["delivery_cicd"]["instructions"]
        )
        assert "Do not mask deployment failures" in " ".join(
            system_context["delivery_cicd"]["instructions"]
        )
        assert "Drone step environment variables must use YAML mapping syntax" in " ".join(
            system_context["delivery_cicd"]["instructions"]
        )
        assert "Docker deploy must be self-contained for app runtime dependencies" in " ".join(
            system_context["delivery_cicd"]["instructions"]
        )
        assert system_context["delivery_cicd"]["services"][0]["service_id"] == "my-evo-app"
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_services"][0]["service_id"]
            == "my-evo-app"
        )
        assert (
            system_context["delivery_cicd"]["deploy"]["docker"]["deploy_services"][0][
                "deploy_port_mapping"
            ]
            == "18080:8080"
        )
        assert "sandbox worker may not have DRONE_TOKEN" in " ".join(
            system_context["delivery_cicd"]["instructions"]
        )

    def test_drone_docker_delivery_contract_expands_multi_service_deploy(self) -> None:
        task = _make_task()
        workspace_metadata = {
            "sandbox_code_root": "/workspace/my-evo",
            "delivery_cicd": {
                "provider": "drone",
                "code_root": "/workspace/my-evo",
                "auto_deploy": True,
                "services": [
                    {
                        "service_id": "backend",
                        "name": "Backend API",
                        "start_command": "npm run start:backend",
                        "internal_port": 3001,
                        "health_path": "/health",
                        "required": True,
                    },
                    {
                        "service_id": "frontend",
                        "name": "Frontend Web",
                        "start_command": "npm run start:frontend",
                        "internal_port": 3000,
                        "health_path": "/",
                        "required": True,
                    },
                ],
                "drone": {
                    "repo": "s1366560/my-evo",
                    "branch": "main",
                    "deploy": {
                        "enabled": True,
                        "mode": "docker",
                        "stage": "deploy",
                        "docker": {
                            "image": "localhost:5001/my-evo-backend",
                            "registry": "localhost:5001",
                            "tags": ["drone-docker-e2e"],
                            "services": [
                                {
                                    "service_id": "backend",
                                    "image": "localhost:5001/my-evo-backend",
                                    "context": ".",
                                    "dockerfile": "Dockerfile",
                                    "container_port": 3001,
                                    "deploy_host_port": 18080,
                                    "health_path": "/health",
                                },
                                {
                                    "service_id": "frontend",
                                    "image": "localhost:5001/my-evo-frontend",
                                    "context": "frontend",
                                    "dockerfile": "frontend/Dockerfile",
                                    "container_port": 3000,
                                    "deploy_host_port": 18081,
                                    "health_path": "/",
                                },
                            ],
                        },
                    },
                },
            },
        }

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            workspace_metadata=workspace_metadata,
            plan_node_metadata={"iteration_phase": "deploy"},
        )
        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            workspace_metadata=workspace_metadata,
            plan_node_metadata={"iteration_phase": "deploy"},
        )

        docker_context = system_context["delivery_cicd"]["deploy"]["docker"]
        assert docker_context["deploy_service_count"] == 2
        assert docker_context["deploy_required_service_ids"] == ["backend", "frontend"]
        assert docker_context["deploy_local_build_commands"] == [
            "docker build -t my-evo-backend:drone-docker-e2e -f Dockerfile .",
            "docker build -t my-evo-frontend:drone-docker-e2e -f frontend/Dockerfile frontend",
        ]
        assert [service["service_id"] for service in docker_context["deploy_services"]] == [
            "backend",
            "frontend",
        ]
        assert docker_context["deploy_services"][1]["deploy_port_mapping"] == "18081:3000"
        for expected in (
            "Docker deploy services:",
            "backend (Backend API)",
            "frontend (Frontend Web)",
            "deploy image: `my-evo-backend:drone-docker-e2e`",
            "deploy image: `my-evo-frontend:drone-docker-e2e`",
            "local build: "
            "`docker build -t my-evo-frontend:drone-docker-e2e -f frontend/Dockerfile frontend`",
            "port: `18081:3000`",
            "Docker deploy coverage must match application image coverage",
            "only starts the backend/API container is incomplete",
            "Use docker.deploy_services as the required Docker deploy inventory",
            "every required service in docker.deploy_services is deployed",
        ):
            assert expected in brief

    def test_drone_docker_delivery_context_infers_collapsed_services_from_host_compose(
        self, tmp_path: Any
    ) -> None:
        (tmp_path / "docker-compose.yml").write_text(
            """
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: evomap-backend
    ports:
      - "${PORT:-3001}:3001"
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:3001/health"]
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: evomap-frontend
    ports:
      - "${FRONTEND_PORT:-3000}:3000"
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
""".strip(),
            encoding="utf-8",
        )
        task = _make_task()
        workspace_metadata = {
            "sandbox_code_root": "/workspace/my-evo",
            "delivery_cicd": {
                "provider": "drone",
                "code_root": "/workspace/my-evo",
                "auto_deploy": True,
                "services": [
                    {
                        "service_id": "my-evo-app",
                        "name": "my-evo Application",
                        "start_command": "docker run my-evo",
                        "internal_port": 8080,
                        "health_path": "/health",
                    }
                ],
                "drone": {
                    "repo": "s1366560/my-evo",
                    "branch": "main",
                    "deploy": {
                        "enabled": True,
                        "mode": "docker",
                        "stage": "deploy",
                        "docker": {
                            "image": "localhost:5001/my-evo",
                            "registry": "localhost:5001",
                            "dockerfile": "Dockerfile",
                            "tags": ["drone-docker-e2e"],
                        },
                    },
                },
            },
        }
        code_context = WorkspaceCodeContext(
            sandbox_code_root="/workspace/my-evo",
            host_code_root=tmp_path,
        )

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-3",
            leader_agent_id="L",
            workspace_metadata=workspace_metadata,
            plan_node_metadata={"iteration_phase": "deploy"},
            code_context=code_context,
        )
        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-3",
            leader_agent_id="L",
            workspace_metadata=workspace_metadata,
            plan_node_metadata={"iteration_phase": "deploy"},
            code_context=code_context,
        )

        delivery = system_context["delivery_cicd"]
        docker_context = delivery["deploy"]["docker"]
        assert [service["service_id"] for service in delivery["services"]] == [
            "backend",
            "frontend",
        ]
        assert docker_context["deploy_service_count"] == 2
        assert docker_context["deploy_required_service_ids"] == ["backend", "frontend"]
        assert [service["service_id"] for service in docker_context["deploy_services"]] == [
            "backend",
            "frontend",
        ]
        assert docker_context["deploy_services"][0]["deploy_port_mapping"] == "18080:3001"
        assert docker_context["deploy_services"][1]["deploy_port_mapping"] == "18081:3000"
        assert "backend (evomap-backend)" in brief
        assert "frontend (evomap-frontend)" in brief
        assert "docker compose up -d backend" in brief
        assert "docker compose up -d frontend" in brief
        assert "Use docker.deploy_services as the required Docker deploy inventory" in brief

    def test_docker_run_image_parser_ignores_non_docker_run_commands(self) -> None:
        assert wl._docker_run_image_from_command("npm run start:backend") is None
        assert (
            wl._docker_run_image_from_command(
                "docker run -d --name app -p 18080:3000 localhost:5001/my-evo"
            )
            == "localhost:5001/my-evo"
        )

    def test_system_context_includes_harness_preflight_contract(self) -> None:
        task = _make_task(
            metadata={
                "task_role": "execution_task",
                "root_goal_task_id": "root-1",
                "harness_feature_id": "feature-001",
                "preflight_checks": [
                    {
                        "check_id": "git-status",
                        "kind": "git_status",
                        "command": "git status --short",
                        "required": True,
                        "status": "pending",
                    },
                    {
                        "check_id": "test-command-1",
                        "kind": "test_command",
                        "command": "uv run pytest src/tests/unit/example.py -q",
                        "required": True,
                        "status": "pending",
                    },
                ],
            }
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
        )

        harness = system_context["harness"]
        assert harness["feature_id"] == "feature-001"
        assert harness["required_evidence_prefix"] == "preflight:"
        assert harness["preflight_checks"][0]["command"] == "git status --short"
        assert harness["preflight_checks"][1]["check_id"] == "test-command-1"
        assert "preflight:<check_id>" in " ".join(harness["instructions"])

    def test_system_context_protects_verification_scripts_from_plan_node_phase(self) -> None:
        task = _make_task(
            title="Update report with comprehensive test summary (202/203)",
            description="Document the known deferred responsive-layout check.",
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={"iteration_phase": "test"},
        )

        policy = system_context["workspace_verification_integrity"]
        assert policy["source"] == "workspace_plan_node_metadata"
        assert policy["iteration_phase"] == "test"
        assert policy["protected_script_changes"] is True
        assert policy["allow_failed_tests"] is False
        assert policy["allow_verification_script_changes"] is False
        assert "202/203" in policy["test_contract_hints"][0]
        assert "allow_verification_script_changes=true" in policy["rule"]

    def test_legacy_repair_node_inherits_source_verification_integrity(self) -> None:
        task = _make_task()
        plan_node_metadata = wl._effective_repair_plan_node_metadata(
            {
                "iteration_phase": "implement",
                "repair_for_node_id": "node-source",
            },
            {
                "iteration_phase": "test",
                "expected_artifacts": ["workspace-persistence.test.ts"],
            },
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata=plan_node_metadata,
        )

        policy = system_context["workspace_verification_integrity"]
        assert plan_node_metadata["iteration_phase"] == "test"
        assert plan_node_metadata["allowed_verification_script_paths"] == [
            "workspace-persistence.test.ts"
        ]
        assert "allow_verification_script_changes" not in plan_node_metadata
        assert policy["iteration_phase"] == "test"
        assert policy["protected_script_changes"] is True
        assert policy["allow_verification_script_changes"] is False
        assert policy["allowed_verification_script_paths"] == ["workspace-persistence.test.ts"]

    def test_explicit_implement_repair_contract_is_not_overwritten_by_test_ancestor(
        self,
    ) -> None:
        task = _make_task(
            metadata={
                "task_role": "execution_task",
                "root_goal_task_id": "root-1",
                "iteration_phase": "test",
                "workspace_verification_integrity": {
                    "iteration_phase": "test",
                    "allow_verification_script_changes": False,
                    "protected_script_changes": True,
                },
            }
        )
        plan_node_metadata = wl._effective_repair_plan_node_metadata(
            {
                "iteration_phase": "implement",
                "repair_for_node_id": "node-source",
                "repair_source_iteration_phase": "implement",
                "allow_verification_script_changes": True,
            },
            {"iteration_phase": "test"},
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata=plan_node_metadata,
        )
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata=plan_node_metadata,
        )

        assert plan_node_metadata["iteration_phase"] == "implement"
        assert plan_node_metadata["repair_source_iteration_phase"] == "implement"
        assert plan_node_metadata["allow_verification_script_changes"] is True
        assert "legacy_repair_verification_integrity_repaired" not in plan_node_metadata
        assert "workspace_verification_integrity" not in system_context
        assert "## Test/review integrity gate" not in brief

    def test_explicit_script_change_contract_is_authoritative_without_source_phase(
        self,
    ) -> None:
        task = _make_task(
            metadata={
                "task_role": "execution_task",
                "root_goal_task_id": "root-1",
                "iteration_phase": "test",
                "workspace_verification_integrity": {
                    "iteration_phase": "test",
                    "allow_verification_script_changes": False,
                    "protected_script_changes": True,
                },
            }
        )
        plan_node_metadata = wl._effective_repair_plan_node_metadata(
            {
                "iteration_phase": "implement",
                "repair_for_node_id": "node-source",
                "allow_verification_script_changes": True,
            },
            {"iteration_phase": "test"},
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata=plan_node_metadata,
        )

        assert plan_node_metadata["iteration_phase"] == "implement"
        assert plan_node_metadata["allow_verification_script_changes"] is True
        assert "workspace_verification_integrity" not in system_context

    def test_system_context_extracts_repair_brief_verification_script_allowlist(self) -> None:
        task = _make_task()

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={
                "iteration_phase": "test",
                "current_repair_turn": {
                    "repair_brief": {
                        "allowed_write_scope": (
                            "test-data-persistence.js (fix selector), "
                            "test-results/iteration-sprint/SPRINT-TEST-REPORT.md"
                        )
                    }
                },
            },
        )

        policy = system_context["workspace_verification_integrity"]
        assert policy["protected_script_changes"] is True
        assert policy["allow_verification_script_changes"] is False
        assert policy["allowed_verification_script_paths"] == ["test-data-persistence.js"]

    def test_repair_node_allowlists_paths_from_verifier_feedback_fields(self) -> None:
        task = _make_task()
        plan_node_metadata = wl._effective_repair_plan_node_metadata(
            {
                "iteration_phase": "implement",
                "repair_for_node_id": "node-source",
            },
            {
                "iteration_phase": "test",
                "last_verification_judge_repair_brief": {
                    "failed_items": [
                        "test_run: src/workspace/workspace-persistence.test.ts failed"
                    ],
                    "required_next_action": (
                        "Add the Jest import in src/workspace/service.test.ts."
                    ),
                    "feedback_items": [
                        {
                            "summary": "src/workspace/chat.test.ts also uses jest.fn().",
                            "failure_signature": "ReferenceError in src/workspace/chat.test.ts",
                        }
                    ],
                },
            },
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata=plan_node_metadata,
        )

        policy = system_context["workspace_verification_integrity"]
        assert plan_node_metadata["iteration_phase"] == "test"
        assert set(policy["allowed_verification_script_paths"]) == {
            "src/workspace/chat.test.ts",
            "src/workspace/service.test.ts",
            "src/workspace/workspace-persistence.test.ts",
        }

    def test_system_context_allows_expected_test_artifact_creation(self) -> None:
        task = _make_task(
            metadata={
                "task_role": "execution_task",
                "root_goal_task_id": "root-1",
                "expected_artifacts": [
                    "workspace-persistence.test.ts",
                    "drone test log evidence",
                ],
            }
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={"iteration_phase": "test"},
        )
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={"iteration_phase": "test"},
        )

        policy = system_context["workspace_verification_integrity"]
        assert policy["protected_script_changes"] is True
        assert policy["allow_verification_script_changes"] is False
        assert policy["allowed_verification_script_paths"] == ["workspace-persistence.test.ts"]
        assert "workspace-persistence.test.ts" in brief
        assert "drone test log evidence" not in policy["allowed_verification_script_paths"]

    def test_system_context_allowlists_contract_named_verification_script_path(self) -> None:
        task = _make_task(
            title="Extend frontend/e2e/journey.spec.ts with OAuth login coverage",
            description=(
                "Add OAuth assertions to frontend/e2e/journey.spec.ts, run the full "
                "Playwright suite, and record the new total."
            ),
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={"iteration_phase": "test"},
        )

        policy = system_context["workspace_verification_integrity"]
        assert policy["protected_script_changes"] is True
        assert policy["allow_verification_script_changes"] is False
        assert policy["allowed_verification_script_paths"] == ["frontend/e2e/journey.spec.ts"]

    def test_system_context_honors_explicit_failed_tests_contract(self) -> None:
        task = _make_task(
            metadata={
                "task_role": "execution_task",
                "root_goal_task_id": "root-1",
                "iteration_phase": "review",
                "allow_failed_tests": True,
            }
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
        )

        policy = system_context["workspace_verification_integrity"]
        assert policy["iteration_phase"] == "review"
        assert policy["allow_failed_tests"] is True

    def test_system_context_honors_explicit_verification_script_change_contract(self) -> None:
        task = _make_task()

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={
                "iteration_phase": "review",
                "allow_verification_script_changes": True,
            },
        )

        policy = system_context["workspace_verification_integrity"]
        assert policy["iteration_phase"] == "review"
        assert policy["protected_script_changes"] is False
        assert policy["allow_verification_script_changes"] is True

    def test_brief_surfaces_protected_test_node_integrity_gate(self) -> None:
        task = _make_task()

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={"iteration_phase": "test"},
        )

        assert "## Test/review integrity gate" in brief
        assert "protected `test` workspace node" in brief
        assert "do not call workspace_report_complete" in brief
        assert "Do not edit, replace, regenerate, or loosen test" in brief
        assert "workspace_report_blocked" in brief
        assert "13/14 or 85/86 as complete" in brief
        assert "contract_disposition:<reason>" in brief

    def test_brief_marks_handoff_failed_tests_as_historical_for_protected_nodes(self) -> None:
        task = _make_task()

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={"iteration_phase": "test"},
            extra_instructions=(
                "[feature-checkpoint]\n"
                "worktree_path=/workspace/.memstack/worktrees/att-2\n"
                "[/feature-checkpoint]\n\n"
                "[handoff-package]\n"
                "completed_step=last_report=completed\n"
                "test_command=13 passed 1 failed node test-data-persistence.js\n"
                "[/handoff-package]"
            ),
        )

        assert "## Handoff package interpretation" in brief
        assert "historical context from previous attempts" in brief
        assert "last_report=completed" in brief
        assert "fresh 0-failed evidence" in brief
        assert "workspace_report_blocked" in brief

    def test_handles_missing_description(self) -> None:
        task = _make_task(description=None)
        brief = wl._build_worker_brief(
            workspace_id="w", task=task, attempt_id=None, leader_agent_id=None
        )
        assert "Task description" not in brief

    def test_includes_software_code_context_and_agents_instructions(self) -> None:
        task = _make_task()
        code_context = WorkspaceCodeContext(
            sandbox_code_root="/workspace/my-evo",
            agents_files=(
                AgentsInstructionFile(
                    sandbox_path="/workspace/my-evo/AGENTS.md",
                    content="Always run npm test.",
                ),
            ),
        )
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
        )

        assert "[workspace-code-context]" not in brief
        assert "Always run npm test." not in brief
        assert "## Code root discipline" in brief
        assert "mkdir -p /workspace/my-evo && cd /workspace/my-evo" in brief
        assert "Do not place `package.json`" in brief
        assert "baseline checkout for historical context" in brief
        assert "regenerate it inside the worktree" in brief
        assert "Artifact write discipline" in brief
        assert "git_diff_summary" in brief
        assert "## Code quality gate" in brief
        assert "AGENTS.md/project guidance" in brief
        assert "Schema changes need reproducible migrations" in brief
        assert "Do not silently show mock" in brief
        assert "hard acceptance criteria" in brief
        assert "project_guidance:checked" in brief
        assert "never weaken or replace the verification script" in brief
        assert "git add -A" in brief
        assert "owned files only" in brief

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
        )
        code_context_payload = system_context["code_context"]
        assert code_context_payload["sandbox_code_root"] == "/workspace/my-evo"
        assert code_context_payload["loaded_agents_files"] == ["/workspace/my-evo/AGENTS.md"]
        assert code_context_payload["required_tool_workdir"] == "/workspace/my-evo"
        assert code_context_payload["bootstrap_command"] == (
            "mkdir -p /workspace/my-evo && cd /workspace/my-evo"
        )
        assert code_context_payload["agents_files"][0]["content"] == "Always run npm test."
        assert "Before the first file operation" in code_context_payload["rule"]
        assert (
            "Bash commands must also start from the selected root" in code_context_payload["rule"]
        )
        assert (
            "Do not create project files directly under /workspace" in code_context_payload["rule"]
        )
        assert "do not read current reports" in code_context_payload["rule"]
        assert "regenerate it inside the worktree" in code_context_payload["rule"]
        quality_policy = system_context["code_quality_policy"]
        assert quality_policy["source"] == "workspace_generic_quality_gate"
        quality_instructions = " ".join(quality_policy["instructions"])
        assert "AGENTS.md/project guidance" in quality_instructions
        assert "do not rely on local db push" in quality_instructions
        assert "matching lockfile" in quality_instructions
        assert "mock or fake data" in quality_instructions
        assert "project_guidance:checked" in quality_instructions
        assert "preserve assertion strength" in quality_instructions
        assert "explicit git add <path>" in quality_instructions

    def test_renders_code_root_placeholder_in_extra_instructions(self) -> None:
        task = _make_task()
        code_context = WorkspaceCodeContext(sandbox_code_root="/workspace/my-evo")
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            extra_instructions="worktree_path=${sandbox_code_root}/../.memstack/worktrees/att-2",
        )

        assert "## Workspace checkpoint and worktree" in brief
        assert "worktree_path=/workspace/my-evo/../.memstack/worktrees/att-2" in brief
        assert "${sandbox_code_root}" not in brief
        assert "## Active attempt root - highest priority" in brief
        assert "This overrides `/workspace/my-evo`" in brief
        assert "recalled memories" in brief
        assert "regenerate it there or report a blocker" in brief
        assert brief.index("## Active attempt root - highest priority") < brief.index(
            "## Task description"
        )
        assert "use that path as the task root" in brief
        assert "every absolute file_path must start with that worktree_path" in brief
        assert "bash commands must not create temp scripts" in brief
        assert "For bash, do not write temp scripts" in brief
        assert "Do not edit or inspect the main sandbox checkout" in brief
        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            extra_instructions="worktree_path=${sandbox_code_root}/../.memstack/worktrees/att-2",
        )

        assert (
            system_context["additional_instructions"]
            == "worktree_path=/workspace/my-evo/../.memstack/worktrees/att-2"
        )
        assert (
            "worktree_path overrides code_context.sandbox_code_root"
            in (system_context["workspace_root_override"]["rule"])
        )
        assert "file_path arguments" in system_context["workspace_root_override"]["rule"]
        assert "bash writes" in system_context["workspace_root_override"]["rule"]
        assert "temp scripts" in system_context["workspace_root_override"]["rule"]
        assert "baseline checkout only" in system_context["workspace_root_override"]["rule"]
        assert (
            "do not inspect it for current attempt reports"
            in (system_context["workspace_root_override"]["rule"])
        )
        assert (
            "check additional_instructions for a worktree_path"
            in (system_context["code_context"]["rule"])
        )

    def test_structured_attempt_worktree_sets_active_execution_root(self) -> None:
        task = _make_task()
        code_context = WorkspaceCodeContext(sandbox_code_root="/workspace/my-evo")
        attempt_worktree = {
            "workspace_root": "/workspace",
            "sandbox_code_root": "/workspace/my-evo",
            "active_root": "/workspace/.memstack/worktrees/att-2",
            "worktree_path": "/workspace/.memstack/worktrees/att-2",
            "branch_name": "workspace/node-att-2",
            "base_ref": "HEAD",
            "attempt_id": "att-2",
            "is_isolated": True,
            "setup_status": "prepared",
        }

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            attempt_worktree_context=attempt_worktree,
        )
        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            attempt_worktree_context=attempt_worktree,
        )

        assert "The current attempt root is `/workspace/.memstack/worktrees/att-2`" in brief
        assert "Do not switch the attempt worktree to main/master" in brief
        assert "report commit_ref so the platform harness can publish and merge" in brief
        assert system_context["active_execution_root"] == "/workspace/.memstack/worktrees/att-2"
        assert system_context["attempt_worktree"]["attempt_id"] == "att-2"
        assert system_context["worktree_setup"]["status"] == "prepared"
        assert system_context["workspace_root_override"]["source"] == "attempt_worktree"

    def test_rewrites_checkpoint_commands_to_attempt_worktree_root(self) -> None:
        task = _make_task()
        code_context = WorkspaceCodeContext(sandbox_code_root="/workspace/my-evo")
        extra_instructions = (
            "[feature-checkpoint]\n"
            "worktree_path=${sandbox_code_root}/../.memstack/worktrees/att-2\n"
            "test_command=cd /workspace/my-evo && npm test\n"
            "[/feature-checkpoint]\n\n"
            "[preflight-checks]\n"
            "check_id=test-command-1 kind=test_command required=True "
            "command=cd /workspace/my-evo && npm test\n"
            "[/preflight-checks]"
        )

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            extra_instructions=extra_instructions,
        )
        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            extra_instructions=extra_instructions,
        )

        worktree_command = "cd /workspace/.memstack/worktrees/att-2 && npm test"
        assert f"test_command={worktree_command}" in brief
        assert f"command={worktree_command}" in brief
        assert "test_command=cd /workspace/my-evo && npm test" not in brief
        assert "command=cd /workspace/my-evo && npm test" not in brief
        assert f"test_command={worktree_command}" in system_context["additional_instructions"]
        assert f"command={worktree_command}" in system_context["additional_instructions"]


class TestLaunchWorkerSession:
    @pytest.mark.asyncio
    async def test_retired_worker_launch_fails_closed_before_validation(self) -> None:
        task = _make_task()
        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Avernet Workspace Core"):
            await wl.launch_worker_session(
                workspace_id="w",
                task=task,
                worker_agent_id="",
                actor_user_id="u1",
            )

    @pytest.mark.asyncio
    async def test_retired_worker_launch_does_not_open_platform_db_session(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        task = _make_task()
        platform_db_opened = False

        def _fail_if_platform_db_opens() -> None:
            nonlocal platform_db_opened
            platform_db_opened = True
            raise AssertionError("retired worker launch opened a platform DB session")

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            _fail_if_platform_db_opens,
        )
        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Avernet Workspace Core"):
            await wl.launch_worker_session(
                workspace_id="w",
                task=task,
                worker_agent_id="agent-X",
                actor_user_id="u1",
            )
        assert platform_db_opened is False


class TestScheduleWorkerSession:
    @pytest.mark.asyncio
    async def test_schedules_background_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: dict[str, object] = {}
        lifecycle: list[str] = []

        class _Reservation:
            def __init__(self) -> None:
                self.released = False

            @asynccontextmanager
            async def admit(self, *, operation_id, metadata):
                assert operation_id == "workspace-worker-launch:task-1"
                assert metadata == {
                    "kind": "workspace-worker-launch",
                    "workspace_id": "w",
                    "task_id": "task-1",
                    "worker_agent_id": "agent-X",
                    "attempt_id": "att-1",
                }
                lifecycle.append("operation-entered")
                try:
                    yield object()
                finally:
                    await self.release()

            async def release(self) -> None:
                if self.released:
                    return
                self.released = True
                lifecycle.append("generation-released")

        reservation = _Reservation()

        async def _fork_operation() -> _Reservation:
            lifecycle.append("operation-reserved")
            return reservation

        async def _fake_launch(**kwargs: object) -> dict[str, object]:
            lifecycle.append("launch-started")
            called.update(kwargs)
            return {"launched": True, "conversation_id": "cid", "reason": "launched"}

        monkeypatch.setattr(
            "src.infrastructure.plugins.v2.boundary.fork_current_agent_operation_v2",
            _fork_operation,
        )
        monkeypatch.setattr(wl, "launch_worker_session", _fake_launch)
        task = _make_task()
        await wl.schedule_worker_session(
            workspace_id="w",
            task=task,
            worker_agent_id="agent-X",
            actor_user_id="u1",
            leader_agent_id="leader-1",
            attempt_id="att-1",
            reuse_conversation_id="conv-reuse",
            repair_brief_prompt="[repair-turn]{}[/repair-turn]",
        )
        # let the scheduled task run
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert called["worker_agent_id"] == "agent-X"
        assert called["task"] is task
        assert called["leader_agent_id"] == "leader-1"
        assert called["attempt_id"] == "att-1"
        assert called["reuse_conversation_id"] == "conv-reuse"
        assert called["repair_brief_prompt"] == "[repair-turn]{}[/repair-turn]"
        assert lifecycle == [
            "operation-reserved",
            "operation-entered",
            "launch-started",
            "generation-released",
        ]

    @pytest.mark.asyncio
    async def test_cancelled_unstarted_task_releases_reserved_generation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        release_calls = 0
        release_observed = asyncio.Event()

        class _Reservation:
            @asynccontextmanager
            async def admit(self, *, operation_id, metadata):
                del operation_id, metadata
                yield object()

            async def release(self) -> None:
                nonlocal release_calls
                release_calls += 1
                release_observed.set()

        async def _fork_operation() -> _Reservation:
            return _Reservation()

        async def _blocked_launch(**_kwargs: object) -> None:
            await asyncio.Event().wait()

        monkeypatch.setattr(
            "src.infrastructure.plugins.v2.boundary.fork_current_agent_operation_v2",
            _fork_operation,
        )
        monkeypatch.setattr(wl, "launch_worker_session", _blocked_launch)
        before = set(wl._background_tasks)

        await wl.schedule_worker_session(
            workspace_id="w",
            task=_make_task(),
            worker_agent_id="agent-X",
            actor_user_id="u1",
        )
        scheduled = tuple(set(wl._background_tasks) - before)
        assert len(scheduled) == 1
        scheduled[0].cancel()
        await release_observed.wait()

        assert release_calls == 1
