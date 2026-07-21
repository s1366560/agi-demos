from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_RUNTIME_ENV_MOUNT = "./docker/ray-runtime.env:/app/.env:ro"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("compose_file", "service_name"),
    [
        ("docker-compose.ray.yml", "ray-head"),
        ("docker-compose.ray.yml", "ray-worker"),
        ("docker-compose.agent-actor.yml", "agent-actor-worker"),
    ],
)
def test_ray_services_mount_authoritative_runtime_env(
    compose_file: str,
    service_name: str,
) -> None:
    compose = yaml.safe_load((_REPOSITORY_ROOT / compose_file).read_text(encoding="utf-8"))

    assert _RUNTIME_ENV_MOUNT in compose["services"][service_name]["volumes"]


@pytest.mark.unit
def test_ray_runtime_database_url_uses_compose_network() -> None:
    runtime_env = (_REPOSITORY_ROOT / "docker/ray-runtime.env").read_text(encoding="utf-8")

    assert "${POSTGRES_PASSWORD:-password}" in runtime_env
    assert "@postgres:5432/memstack" in runtime_env
