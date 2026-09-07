import subprocess
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "e2e.yml"
NEO4J_RUNTIME_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "neo4j-runtime.yml"
FULL_SANDBOX_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "sandbox-full-runtime.yml"
COMPOSE_PATH = REPOSITORY_ROOT / "docker-compose.yml"
DOCKERIGNORE_PATH = REPOSITORY_ROOT / ".dockerignore"
SANDBOX_DOCKERIGNORE_PATH = REPOSITORY_ROOT / "sandbox-mcp-server" / ".dockerignore"
SANDBOX_DOCKERFILE_PATH = REPOSITORY_ROOT / "sandbox-mcp-server" / "Dockerfile"
SANDBOX_ENTRYPOINT_PATH = REPOSITORY_ROOT / "sandbox-mcp-server" / "scripts" / "entrypoint.sh"


def test_backend_e2e_job_provisions_real_dependencies_and_runs_smoke() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    job = workflow["jobs"]["backend-e2e"]
    assert set(job["services"]) >= {"postgres", "redis", "neo4j"}

    steps = job["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    assert "initialize_database" in commands
    assert "uv run alembic upgrade head" in commands
    assert commands.index("initialize_database") < commands.index("uv run alembic upgrade head")
    assert "scripts.fake_openai_server:app" in commands
    assert "uv run uvicorn src.infrastructure.adapters.primary.web.main:app" in commands
    assert "scripts/verify_e2e_backend.py" in commands
    assert "-m scripts.verify_e2e_agent" in commands
    assert "-m scripts.verify_e2e_graph" in commands
    assert "ray start --head" in commands
    assert "--min-worker-port=20000" in commands
    assert "--max-worker-port=29999" in commands
    assert "-m src.agent_actor_worker" in commands
    assert "ray.get_actor" in commands
    assert "AGENT_RUNTIME_MODE=ray" in commands
    assert "Using Ray Actor (AGENT_RUNTIME_MODE=ray)" in commands
    assert commands.count("-m scripts.verify_e2e_agent") == 2
    assert "sandbox-mcp-server/Dockerfile.e2e" in commands
    assert "sandbox-mcp-server:lite" in commands
    assert "-m scripts.verify_e2e_sandbox" in commands
    assert "playwright test e2e/backend-smoke.spec.ts" in commands
    assert "curl -fsS http://localhost:8000/health" in commands

    environment = job["env"]
    assert environment["AGENT_RUNTIME_MODE"] == "local"
    assert environment["AGENT_MEMORY_RUNTIME_MODE"] == "disabled"
    assert environment["LLM_PROVIDER"] == "openai"
    assert environment["OPENAI_BASE_URL"] == "http://localhost:8010/v1"
    assert environment["OPENAI_MODEL"] == "openai/memstack-e2e"
    assert environment["RAY_ENABLE_UV_RUN_RUNTIME_ENV"] == "0"
    assert "RAY_ADDRESS=127.0.0.1:6380" in commands
    assert environment["SANDBOX_DOCKER_SERVICES_ENABLED"] is True
    assert environment["SANDBOX_DOCKER_SOCKET_ENABLED"] is False
    assert environment["SANDBOX_PIP_CACHE_ENABLED"] is False
    assert environment["SANDBOX_HOST_MEMSTACK_PATH"] == "/tmp/memstack-e2e-meta"


def test_neo4j_runtime_job_is_dedicated_pinned_and_restartable() -> None:
    workflow = yaml.safe_load(NEO4J_RUNTIME_WORKFLOW_PATH.read_text(encoding="utf-8"))

    job = workflow["jobs"]["neo4j-runtime"]
    assert job["runs-on"] == "ubuntu-latest"
    assert "if" not in job
    assert job.get("continue-on-error") is not True

    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
    pinned_image = (
        "neo4j:5.26-community@"
        "sha256:d9dd3dc7d1c78fa959191ff02dbdcbefadceaf83eee23428fb92a58cac8ad3fe"
    )
    assert pinned_image in commands
    assert "docker volume create memstack-neo4j-runtime-data" in commands
    assert "--name memstack-neo4j-runtime" in commands
    assert "docker stop memstack-neo4j-runtime" in commands
    assert "docker start memstack-neo4j-runtime" in commands
    assert "scripts.verify_e2e_graph" in commands
    assert "scripts.verify_neo4j_runtime --expect degraded" in commands
    assert "scripts.verify_neo4j_runtime --expect available" in commands
    assert "CALL db.awaitIndexes" in commands
    assert "SHOW INDEXES" in commands
    assert "RuntimeSentinel" in commands
    assert job["env"]["AGENT_MEMORY_RUNTIME_MODE"] == "plugin"
    assert job["env"]["EMBEDDING_DIMENSION"] == 1024
    assert job["env"]["E2E_EMBEDDING_DIMENSIONS"] == 1024
    assert "docker inspect --format" in commands
    assert "{{.Config.Env}}" not in commands
    assert "docker inspect memstack-neo4j-runtime >" not in commands

    cleanup = next(step for step in job["steps"] if step.get("name") == "Clean Neo4j runtime")
    assert cleanup["if"] == "always()"
    assert "docker rm --force memstack-neo4j-runtime" in cleanup["run"]
    assert "docker volume rm memstack-neo4j-runtime-data" in cleanup["run"]


def test_neo4j_runtime_job_runs_required_web_desktop_matched_state() -> None:
    workflow = yaml.safe_load(NEO4J_RUNTIME_WORKFLOW_PATH.read_text(encoding="utf-8"))

    job = workflow["jobs"]["neo4j-runtime"]
    steps = job["steps"]
    step_names = [str(step.get("name", "")) for step in steps]
    commands = "\n".join(str(step.get("run", "")) for step in steps)

    setup_pnpm = next(
        step for step in steps if str(step.get("uses", "")).startswith("pnpm/action-setup@")
    )
    assert setup_pnpm["with"]["version"] == "11.15.1"
    setup_node = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/setup-node@")
    )
    assert setup_node["with"]["node-version"] == "22"
    assert "pnpm --dir web install --frozen-lockfile" in commands
    assert "pnpm --dir agi-stack/apps/desktop install --frozen-lockfile" in commands
    assert "playwright install --with-deps chromium" in commands

    matched_state = next(
        step for step in steps if step.get("name") == "Verify Web and Desktop Neo4j matched state"
    )
    assert matched_state.get("continue-on-error") is not True
    assert "qa:neo4j-matched-state" in matched_state["run"]
    assert step_names.index("Verify real graph mutation, search, traversal, and communities") < (
        step_names.index("Verify Web and Desktop Neo4j matched state")
    )
    assert step_names.index("Verify Web and Desktop Neo4j matched state") < step_names.index(
        "Verify structured degradation while Neo4j is stopped"
    )

    upload = next(step for step in steps if step.get("name") == "Upload Neo4j runtime evidence")
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "neo4j-runtime-logs"
    assert upload["with"]["if-no-files-found"] == "error"


def test_compose_api_uses_service_hostnames_for_python_dependencies() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    environment = set(compose["services"]["api"]["environment"])

    assert "POSTGRES_HOST=postgres" in environment
    assert "POSTGRES_PORT=5432" in environment
    assert "POSTGRES_DB=memstack" in environment
    assert "POSTGRES_USER=postgres" in environment
    assert "REDIS_HOST=redis" in environment
    assert "REDIS_PORT=6379" in environment


def test_docker_context_excludes_local_secrets_and_build_artifacts() -> None:
    patterns = {
        line.strip()
        for line in DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {".git", ".env", ".env.*", ".venv", "**/node_modules", "**/target"} <= patterns
    assert {".memstack/workspace", ".memstack/worktrees", "logs", "*.log"} <= patterns
    assert {".ssh", ".aws", ".npmrc", ".pypirc", "*.pem", "*.key"} <= patterns

    sandbox_patterns = {
        line.strip()
        for line in SANDBOX_DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {".venv", "venv", "**/__pycache__", ".pytest_cache", ".coverage"} <= (sandbox_patterns)
    assert {".env", ".env.*", ".ssh", ".aws", ".npmrc", ".pypirc", "*.pem", "*.key"} <= (
        sandbox_patterns
    )
    assert {"logs", "*.log"} <= sandbox_patterns
    assert "docker" not in sandbox_patterns
    assert "scripts" not in sandbox_patterns


def test_full_sandbox_image_uses_supported_lts_runtime() -> None:
    dockerfile = SANDBOX_DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "FROM ubuntu:24.04" in dockerfile
    assert "ARG PYTHON_VERSION=3.12" in dockerfile
    assert "ARG NODE_VERSION=22" in dockerfile
    assert "FROM python:${PYTHON_VERSION}-slim-bookworm AS python-wheel-builder" in dockerfile
    assert "FROM node:${NODE_VERSION}-bookworm-slim AS node-runtime" in dockerfile
    assert "plucky" not in dockerfile
    assert "mirrors.tuna.tsinghua.edu.cn" not in dockerfile
    assert "USER sandbox" in dockerfile
    assert "useradd --uid 10001" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright" in dockerfile
    assert "--break-system-packages" not in dockerfile
    assert dockerfile.count("install chromium --no-shell") == 1
    assert "python3 -m venv /opt/sandbox-mcp-venv" in dockerfile
    assert "--no-index" in dockerfile
    assert "--find-links=/wheelhouse" in dockerfile
    for stage, source, target in (
        ("node-runtime", "/usr/local/", "/usr/local/"),
        ("python-runtime", "/opt/sandbox-mcp-venv", "/opt/sandbox-mcp-venv"),
        ("playwright-browser", "/opt/ms-playwright", "/opt/ms-playwright"),
        ("sky-cua-builder", "/out/", "/opt/sky-cua/"),
    ):
        assert f"COPY --from={stage} {source} {target}" in dockerfile
    assert 'test "$(git rev-parse HEAD)" = "${SKY_CUA_COMMIT}"' in dockerfile
    assert "cargo build --locked --release" in dockerfile
    assert "TTYD_ARCH=x86_64" in dockerfile
    assert "TTYD_ARCH=aarch64" in dockerfile
    assert dockerfile.count("TTYD_SHA256=") == 2
    assert dockerfile.count("KASM_SHA256=") == 2
    assert '${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c -' in dockerfile
    assert '${KASM_SHA256}  /tmp/kasmvnc.deb" | sha256sum -c -' in dockerfile
    assert "unsupported ttyd architecture" in dockerfile
    assert "unsupported KasmVNC architecture" in dockerfile


def test_full_sandbox_entrypoint_is_fail_closed_and_profile_aware() -> None:
    entrypoint = SANDBOX_ENTRYPOINT_PATH.read_text(encoding="utf-8")
    dockerfile = SANDBOX_DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "set -Eeuo pipefail" in entrypoint
    assert 'TERMINAL_ENABLED="${TERMINAL_ENABLED:-true}"' in entrypoint
    assert 'SERVICE_AUTH_TOKEN="${SANDBOX_SERVICE_AUTH_TOKEN:-${MCP_STATIC_TOKEN:-}}"' in entrypoint
    assert '-c "${SERVICE_AUTH_USERNAME}:${SERVICE_AUTH_TOKEN}"' in entrypoint
    assert "-disableBasicAuth" not in entrypoint
    assert "entering standby mode" not in entrypoint
    assert "DESKTOP_ENABLED" in dockerfile.split("HEALTHCHECK", maxsplit=1)[1]
    assert "TERMINAL_ENABLED" in dockerfile.split("HEALTHCHECK", maxsplit=1)[1]

    # Execute the production orchestration, replacing only side-effecting services.
    main_function = "main() {" + entrypoint.split("main() {", 1)[1].split("\n}\n", 1)[0] + "\n}"
    service_names = (
        "configure_hostname",
        "prepare_session_directories",
        "start_session_dbus",
        "activate_at_spi",
        "start_kasmvnc",
        "wait_for_x11_session",
        "clear_stale_chromium_profile_locks",
        "install_chromium_native_host",
        "start_chromium",
        "start_mcp_server",
        "start_ttyd",
        "wait_for_primary_process",
    )
    stubs = "\n".join(f"{name}() {{ echo {name}; }}" for name in service_names)

    def run_main(*, desktop: str, terminal: str, token: str, fail_mcp: bool = False):
        script = (
            "set -Eeuo pipefail\n"
            + main_function
            + "\n"
            + stubs
            + '\nlog_error() { echo "$*" >&2; }\nlog_success() { :; }\n'
            + f"DESKTOP_ENABLED={desktop}\nTERMINAL_ENABLED={terminal}\n"
            + f"SERVICE_AUTH_TOKEN={token}\n"
        )
        if fail_mcp:
            script += "start_mcp_server() { echo mcp-failed; return 17; }\n"
        return subprocess.run(
            ["bash"],
            input=script + "main\n",
            text=True,
            capture_output=True,
            check=False,
        )

    terminal_function = (
        "start_ttyd() {" + entrypoint.split("start_ttyd() {", 1)[1].split("\n}\n", 1)[0] + "\n}"
    )
    disabled_terminal = subprocess.run(
        ["bash"],
        input="set -Eeuo pipefail\nTERMINAL_ENABLED=false\n" + terminal_function + "\nstart_ttyd\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert disabled_terminal.returncode == 0
    assert disabled_terminal.stdout == ""

    denied = run_main(desktop="false", terminal="true", token="")
    assert denied.returncode != 0
    assert "Interactive services require" in denied.stderr
    assert "start_ttyd" not in denied.stdout
    headless = run_main(desktop="false", terminal="false", token="")
    assert headless.returncode == 0
    assert "start_kasmvnc" not in headless.stdout
    assert "start_mcp_server" in headless.stdout
    desktop = run_main(desktop="true", terminal="true", token="test-token")
    assert desktop.returncode == 0
    calls = desktop.stdout.splitlines()
    assert calls.index("start_kasmvnc") < calls.index("start_chromium")
    assert calls.index("start_mcp_server") < calls.index("start_ttyd")
    failed = run_main(desktop="false", terminal="true", token="test-token", fail_mcp=True)
    assert failed.returncode == 17
    assert "start_ttyd" not in failed.stdout
    assert "wait_for_primary_process" not in failed.stdout


def test_full_sandbox_runtime_has_scheduled_release_gate() -> None:
    workflow = yaml.safe_load(FULL_SANDBOX_WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert set(workflow[True]) == {"workflow_dispatch", "schedule"}
    job = workflow["jobs"]["full-runtime"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] >= 60
    steps = job["steps"]
    build_step = next(step for step in steps if step.get("uses") == "docker/build-push-action@v6")
    assert build_step["with"]["file"] == "sandbox-mcp-server/Dockerfile"
    assert build_step["with"]["load"] is True
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    assert "playwright install --with-deps chromium" in commands
    assert "scripts.verify_full_sandbox_runtime" in commands
    assert "sandbox_api::tests::docker_live" in commands
    rust_gate = next(
        step for step in steps if "sandbox_api::tests::docker_live" in str(step.get("run", ""))
    )
    assert rust_gate["env"]["AGISTACK_RUN_SANDBOX_LIVE_TESTS"] == "1"
    assert rust_gate["env"]["AGISTACK_SANDBOX_LIVE_IMAGE"] == "sandbox-mcp-server:full-ci"
    assert str(job["env"]["AGISTACK_SANDBOX_LIVE_PROJECT_ID"]).startswith("rust-live-")
    assert "label=agistack.project=${AGISTACK_SANDBOX_LIVE_PROJECT_ID}" in commands
    assert "docker network prune" not in commands
