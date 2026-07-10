from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "e2e.yml"
COMPOSE_PATH = REPOSITORY_ROOT / "docker-compose.yml"


def test_backend_e2e_job_provisions_real_dependencies_and_runs_smoke() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    job = workflow["jobs"]["backend-e2e"]
    assert set(job["services"]) >= {"postgres", "redis", "neo4j"}

    steps = job["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    assert "uv run alembic upgrade head" in commands
    assert "uv run uvicorn src.infrastructure.adapters.primary.web.main:app" in commands
    assert "scripts/verify_e2e_backend.py" in commands
    assert "playwright test e2e/backend-smoke.spec.ts" in commands
    assert "curl -fsS http://localhost:8000/health" in commands


def test_compose_api_uses_service_hostnames_for_python_dependencies() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    environment = set(compose["services"]["api"]["environment"])

    assert "POSTGRES_HOST=postgres" in environment
    assert "POSTGRES_PORT=5432" in environment
    assert "POSTGRES_DB=memstack" in environment
    assert "POSTGRES_USER=postgres" in environment
    assert "REDIS_HOST=redis" in environment
    assert "REDIS_PORT=6379" in environment
