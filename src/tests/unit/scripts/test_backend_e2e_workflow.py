from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "e2e.yml"
FULL_SANDBOX_WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "sandbox-full-runtime.yml"
)
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
    assert "PYTHON_VERSION=3.12" in dockerfile
    assert "plucky" not in dockerfile
    assert "mirrors.tuna.tsinghua.edu.cn" not in dockerfile
    assert "ARG DOCKER_CLI_IMAGE=docker:cli@sha256:" in dockerfile
    assert "amd64) TTYD_ARCH=x86_64" in dockerfile
    assert "sha256sum -c -" in dockerfile
    assert "USER sandbox" in dockerfile
    assert "useradd --uid 10001" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright" in dockerfile
    assert "ln -sf /root/.bun" not in dockerfile
    assert "golang-go rustc cargo" in dockerfile
    assert "--break-system-packages" not in dockerfile
    assert dockerfile.count("playwright install") == 1
    assert "https://ports.ubuntu.com" in dockerfile
    assert "Acquire::Retries=10" in dockerfile
    assert dockerfile.count("--mount=type=cache,target=/var/cache/apt,sharing=locked") >= 2
    assert dockerfile.index("python -m venv ${SKILLS_VENV}") < dockerfile.index(
        "pypdf pdfplumber reportlab pdf2image"
    )


def test_full_sandbox_entrypoint_is_fail_closed_and_profile_aware() -> None:
    entrypoint = SANDBOX_ENTRYPOINT_PATH.read_text(encoding="utf-8")
    dockerfile = SANDBOX_DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert 'TERMINAL_ENABLED="${TERMINAL_ENABLED:-true}"' in entrypoint
    assert 'if [ "$TERMINAL_ENABLED" = "true" ]; then' in entrypoint
    assert (
        'ttyd -W -c "$SERVICE_AUTH_USERNAME:$SERVICE_AUTH_TOKEN" -p "$TERMINAL_PORT"'
        in entrypoint
    )
    assert 'SERVICE_AUTH_TOKEN="${SANDBOX_SERVICE_AUTH_TOKEN:-${MCP_STATIC_TOKEN:-}}"' in entrypoint
    assert 'vncpasswd -u "$SERVICE_AUTH_USERNAME" -w "$HOME/.kasmpasswd"' in entrypoint
    assert "-disableBasicAuth" not in entrypoint
    assert 'if [ -z "$SERVICE_AUTH_TOKEN" ]; then' in entrypoint
    assert "rm -f /tmp/.X1-lock /tmp/.X11-unix/X1" in entrypoint
    assert "start_kasmvnc || log_warn" not in entrypoint
    assert "if ! start_mcp_server; then" in entrypoint
    assert "/root" not in entrypoint
    assert "wait_for_port \"$MCP_PORT\" 30" in entrypoint
    assert "MCP server is not running" in entrypoint
    assert "entering standby mode" not in entrypoint
    assert "DESKTOP_ENABLED" in dockerfile.split("HEALTHCHECK", maxsplit=1)[1]
    assert "TERMINAL_ENABLED" in dockerfile.split("HEALTHCHECK", maxsplit=1)[1]
    assert "sandbox:kasmvnc:ow" not in dockerfile


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
    assert "scripts.verify_full_sandbox_runtime" in commands
    assert "docker network prune" not in commands
