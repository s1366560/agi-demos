import re
import stat
import subprocess
import sys
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_PATH = REPOSITORY_ROOT / "docker-compose.yml"
DOCKERFILE_PATH = REPOSITORY_ROOT / "Dockerfile.workspace-core"
ENTRYPOINT_PATH = REPOSITORY_ROOT / "docker" / "workspace-core" / "entrypoint.sh"
CONFIG_TEMPLATE_PATH = REPOSITORY_ROOT / "docker" / "workspace-core" / "bcs-config.toml.template"
MAKEFILE_PATH = REPOSITORY_ROOT / "Makefile"
ENV_EXAMPLE_PATH = REPOSITORY_ROOT / ".env.example"
BOOTSTRAP_PATH = REPOSITORY_ROOT / "scripts" / "workspace-core" / "bootstrap-local-env.py"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "avernet-bcs.yml"

CORE_SERVICE = "memstack-workspace-core"
CORE_SECRET_ENV = {
    "WORKSPACE_CORE_DATABASE_URL",
    "WORKSPACE_CORE_SERVICE_TOKEN",
    "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN",
    "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN",
    "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN",
    "AVERNET_SECRET_PRINCIPAL_SIGNING_KEY_VALUE",
    "BCS_SECRET_WORKSPACE_CORE_GROUP_SESSION_WS_JWT",
}


def _compose() -> dict[str, object]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _environment_map(service: dict[str, object]) -> dict[str, str]:
    raw = service["environment"]
    if isinstance(raw, dict):
        return {str(key): str(value or "") for key, value in raw.items()}
    return {
        str(item).partition("=")[0]: str(item).partition("=")[2]
        for item in raw
        if isinstance(item, str)
    }


def _make_recipe(makefile: str, target: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(target)}(?:\s*:[^\n]*)?\n(?P<body>(?:\t[^\n]*\n|\n)*)",
        makefile,
    )
    assert match is not None, f"missing Make target: {target}"
    return match.group("body")


def _env_example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key.strip()] = value.strip()
    return values


def _dotenv_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key.strip()] = value.strip()
    return values


def test_workspace_core_is_an_independent_fail_closed_compose_service() -> None:
    compose = _compose()
    services = compose["services"]
    core = services[CORE_SERVICE]

    assert core["build"] == {"context": ".", "dockerfile": "Dockerfile.workspace-core"}
    assert core["container_name"] == "memstack-workspace-core"
    assert core["restart"] == "unless-stopped"
    assert core["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert core["depends_on"]["redis"]["condition"] == "service_healthy"
    assert core["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "http://127.0.0.1:4319/health",
    ]
    assert core["ports"] == ["127.0.0.1:${WORKSPACE_CORE_PORT:-4319}:4319"]
    assert core["volumes"] == ["workspace_core_files:/var/lib/memstack-workspace-core:rw"]
    assert "workspace_core_files" in compose["volumes"]

    environment = _environment_map(core)
    assert environment.keys() >= CORE_SECRET_ENV
    for key in CORE_SECRET_ENV:
        assert environment[key] == f"${{{key}-}}"


def test_api_waits_for_workspace_core_health_and_receives_only_internal_topology() -> None:
    api = _compose()["services"]["api"]

    assert api["depends_on"][CORE_SERVICE]["condition"] == "service_healthy"
    environment = _environment_map(api)
    assert environment["WORKSPACE_CORE_BASE_URL"] == "http://memstack-workspace-core:4319"
    for key in (
        "WORKSPACE_CORE_SERVICE_TOKEN",
        "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN",
        "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN",
        "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN",
    ):
        assert environment[key] == f"${{{key}-}}"


def test_workspace_core_image_is_locked_non_root_and_runtime_only() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "FROM rust:1.91.1-bookworm AS builder" in dockerfile
    assert "cargo build --locked --release --package memstack-workspace-core" in dockerfile
    assert "FROM debian:bookworm-slim AS runtime" in dockerfile
    assert "libsqlite3-0" in dockerfile
    assert (
        "COPY --from=builder /build/avernet-bcs/target/release/memstack-workspace-core"
        in dockerfile
    )
    assert "USER workspace-core" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/workspace-core-entrypoint"]' in dockerfile
    assert "third_party/avernet-bcs/target" not in dockerfile


def test_workspace_core_entrypoint_requires_credentials_before_rendering_config() -> None:
    entrypoint = ENTRYPOINT_PATH.read_text(encoding="utf-8")
    template = CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8")

    for key in CORE_SECRET_ENV:
        assert f'require_env "{key}"' in entrypoint
    assert "envsubst '${WORKSPACE_CORE_DATABASE_URL}'" in entrypoint
    assert 'exec /usr/local/bin/memstack-workspace-core --config-dir "$config_path"' in entrypoint
    assert "${WORKSPACE_CORE_DATABASE_URL}" in template
    for key in CORE_SECRET_ENV - {
        "WORKSPACE_CORE_DATABASE_URL",
        "AVERNET_SECRET_PRINCIPAL_SIGNING_KEY_VALUE",
    }:
        assert key not in template
    assert "replace-with" not in template
    assert "local-development-only" not in template


def test_workspace_core_callbacks_use_host_api_without_a_compose_dependency_cycle() -> None:
    core = _compose()["services"][CORE_SERVICE]
    environment = _environment_map(core)

    assert core["depends_on"].keys() == {"postgres", "redis"}
    assert core["extra_hosts"] == ["host.docker.internal:host-gateway"]
    assert environment["WORKSPACE_CORE_AGENT_REGISTRY_URL"] == ("http://host.docker.internal:8000")
    assert environment["WORKSPACE_CORE_PROVIDER_WEBHOOK_URL"] == (
        "http://host.docker.internal:8000/internal/v1/workspace-core/provider"
    )
    assert environment["WORKSPACE_CORE_PLAN_DISPATCH_URL"] == (
        "http://host.docker.internal:8000/internal/v1/workspace-core/plan-dispatch"
    )


def test_workspace_core_make_lifecycle_is_complete_and_non_destructive() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")

    for target in (
        "workspace-core-build",
        "workspace-core-start",
        "workspace-core-health",
        "workspace-core-status",
        "workspace-core-logs",
        "workspace-core-stop",
    ):
        assert _make_recipe(makefile, target)

    assert "dev-all: dev-infra-dev db-init workspace-core-start" in makefile
    assert "$(WORKSPACE_CORE_SERVICE)" in _make_recipe(makefile, "dev-stop")
    assert "$(WORKSPACE_CORE_SERVICE)" in _make_recipe(makefile, "status")
    assert "down" not in _make_recipe(makefile, "workspace-core-stop")
    assert "-v" not in _make_recipe(makefile, "workspace-core-stop")


def test_workspace_core_start_bootstraps_missing_local_credentials() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert _make_recipe(makefile, "workspace-core-configure")
    assert "workspace-core-start: workspace-core-configure" in makefile
    assert "bootstrap-local-env.py --env-file .env" in _make_recipe(
        makefile,
        "workspace-core-configure",
    )


def test_workspace_core_local_bootstrap_is_secure_idempotent_and_preserves_values(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            (
                "POSTGRES_USER=local-user",
                "POSTGRES_PASSWORD=p@ss word",
                "POSTGRES_DB=local-db",
                "WORKSPACE_CORE_SERVICE_TOKEN=existing-service-token",
                "",
            )
        ),
        encoding="utf-8",
    )

    first = subprocess.run(
        [sys.executable, str(BOOTSTRAP_PATH), "--env-file", str(env_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    first_content = env_path.read_text(encoding="utf-8")
    values = _dotenv_values(env_path)

    assert values["WORKSPACE_CORE_BASE_URL"] == "http://127.0.0.1:4319"
    assert values["WORKSPACE_CORE_DATABASE_URL"] == (
        "postgresql://local-user:p%40ss%20word@postgres:5432/local-db"
    )
    assert values["WORKSPACE_CORE_SERVICE_TOKEN"] == "existing-service-token"
    credentials = [values[key] for key in CORE_SECRET_ENV if key != "WORKSPACE_CORE_DATABASE_URL"]
    generated = [
        values[key]
        for key in CORE_SECRET_ENV
        if key not in {"WORKSPACE_CORE_DATABASE_URL", "WORKSPACE_CORE_SERVICE_TOKEN"}
    ]
    assert len(credentials) == len(set(credentials))
    assert all(len(value) >= 32 for value in generated)
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert all(value not in first.stdout for value in generated)

    subprocess.run(
        [sys.executable, str(BOOTSTRAP_PATH), "--env-file", str(env_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert env_path.read_text(encoding="utf-8") == first_content


def test_workspace_core_example_credentials_have_no_repository_defaults() -> None:
    values = _env_example_values()

    assert values["WORKSPACE_CORE_BASE_URL"] == "http://127.0.0.1:4319"
    assert values["WORKSPACE_CORE_PORT"] == "4319"
    for key in CORE_SECRET_ENV:
        assert key in values
        assert values[key] == ""


def test_workspace_authority_ci_tracks_every_cross_layer_runtime_and_gate() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    for path_filter in (
        "agi-stack/apps/desktop/**",
        "agi-stack/apps/server/**",
        "src/configuration/**",
        "src/domain/ports/services/workspace_authority_port.py",
        "src/infrastructure/adapters/secondary/persistence/**",
        "src/infrastructure/agent/**",
        "scripts/workspace_core_legacy_sentinel.py",
    ):
        assert workflow.count(f"- '{path_filter}'") == 2

    for gate in (
        "verify-postgres-schema.py",
        "verify-workspace-migration.py",
        "verify-cross-store-scenarios.py",
        "verify-event-parity.py",
        "verify-legacy-workspace-references.py",
    ):
        assert gate in workflow

    assert "cargo test --manifest-path agi-stack/Cargo.toml -p agistack-desktop-sidecar" in workflow
    assert "cargo check --manifest-path agi-stack/Cargo.toml -p agistack-server" in workflow
