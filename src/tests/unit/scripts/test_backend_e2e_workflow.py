from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "e2e.yml"
COMPOSE_PATH = REPOSITORY_ROOT / "docker-compose.yml"
DOCKERIGNORE_PATH = REPOSITORY_ROOT / ".dockerignore"


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
    assert "ray start --head" in commands
    assert "--min-worker-port=20000" in commands
    assert "--max-worker-port=29999" in commands
    assert "-m src.agent_actor_worker" in commands
    assert "ray.get_actor" in commands
    assert "AGENT_RUNTIME_MODE=ray" in commands
    assert "Using Ray Actor (AGENT_RUNTIME_MODE=ray)" in commands
    assert commands.count("-m scripts.verify_e2e_agent") == 2
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
