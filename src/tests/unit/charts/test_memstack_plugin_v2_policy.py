"""Helm deployment policy gates for protocol-v2 publication readiness."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[4]
_CHART = _ROOT / "charts/memstack"
_VALUES = _CHART / "values.yaml"
_PRODUCTION_VALUES = _CHART / "values-production-ha.yaml"
_CONFIGMAP = _CHART / "templates/configmap.yaml"
_HELM = shutil.which("helm")


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _config(values: dict[str, object]) -> dict[str, object]:
    config = values.get("config")
    assert isinstance(config, dict)
    return config


def test_default_chart_declares_local_v2_publication_policy() -> None:
    config = _config(_load_yaml(_VALUES))

    assert config["environment"] == "development"
    assert config["pluginV2RequiredDataPlaneIds"] == ""
    assert config["pluginV2AckDeadlineSeconds"] == 30

    template = _CONFIGMAP.read_text(encoding="utf-8")
    assert "ENVIRONMENT: {{ .Values.config.environment | quote }}" in template
    assert "PLUGIN_V2_REQUIRED_DATA_PLANE_IDS:" in template
    assert 'include "memstack.pluginV2RequiredDataPlaneIds"' in template
    assert "PLUGIN_V2_ACK_DEADLINE_SECONDS:" in template


def test_production_chart_declares_finite_required_v2_roster() -> None:
    config = _config(_load_yaml(_PRODUCTION_VALUES))

    assert config["environment"] == "production"
    assert config["pluginV2RequiredDataPlaneIds"] == "python-api-v2"
    assert config["pluginV2AckDeadlineSeconds"] == 30


@pytest.mark.skipif(_HELM is None, reason="helm is not installed")
def test_helm_rejects_full_runtime_production_without_explicit_v2_roster() -> None:
    assert _HELM is not None
    result = subprocess.run(
        [
            _HELM,
            "template",
            "memstack-policy-test",
            str(_CHART),
            "--set-string",
            "config.environment=production",
            "--set",
            "api.packageKernel=false",
            "--set-string",
            "config.pluginV2RequiredDataPlaneIds=",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "production requires config.pluginV2RequiredDataPlaneIds" in result.stderr


@pytest.mark.skipif(_HELM is None, reason="helm is not installed")
def test_production_chart_renders_exact_v2_policy(tmp_path: Path) -> None:
    assert _HELM is not None
    result = subprocess.run(
        [
            _HELM,
            "template",
            "memstack-policy-test",
            str(_CHART),
            "--values",
            str(_PRODUCTION_VALUES),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    documents = [document for document in yaml.safe_load_all(result.stdout) if document]
    config_map = next(
        document
        for document in documents
        if document.get("kind") == "ConfigMap"
        and "PLUGIN_V2_REQUIRED_DATA_PLANE_IDS" in document.get("data", {})
    )
    assert config_map["data"]["ENVIRONMENT"] == "production"
    assert config_map["data"]["PLUGIN_V2_REQUIRED_DATA_PLANE_IDS"] == "python-api-v2"
    assert config_map["data"]["PLUGIN_V2_ACK_DEADLINE_SECONDS"] == "30"

    api = next(
        item
        for item in documents
        if item["kind"] == "Deployment"
        and item["metadata"]["labels"].get("app.kubernetes.io/component") == "api"
    )
    container = api["spec"]["template"]["spec"]["containers"][0]
    assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"
    assert container["livenessProbe"]["httpGet"]["path"] == "/health"
    pod = api["spec"]["template"]["spec"]
    writer = next(init for init in pod["initContainers"] if init["name"] == "database-config")
    output = tmp_path / ".env"
    password = "test@:/?#%quoted"
    result = subprocess.run(
        [sys.executable, "-c", writer["args"][0], str(output)],
        env={
            **os.environ,
            "POSTGRES_HOST": "db.test",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "platform",
            "POSTGRES_USER": "qa",
            "POSTGRES_PASSWORD": password,
        },
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
    from sqlalchemy.engine import make_url

    from src.configuration.config import Settings

    parsed = make_url(Settings(_env_file=output).postgres_url)
    assert (parsed.host, parsed.database, parsed.password) == ("db.test", "platform", password)
    assert any(m["mountPath"] == "/app/.env" and m["readOnly"] for m in container["volumeMounts"])
    assert any(v.get("emptyDir", {}).get("medium") == "Memory" for v in pod["volumes"])


@pytest.mark.skipif(_HELM is None, reason="helm is not installed")
def test_package_kernel_starts_with_only_identity_and_package_dependencies() -> None:
    assert _HELM is not None
    result = subprocess.run(
        [
            _HELM,
            "template",
            "kernel",
            str(_CHART),
            "-f",
            str(_CHART / "values-package-kernel.yaml"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    deployments = {
        d["metadata"]["labels"].get("app.kubernetes.io/component"): d
        for d in yaml.safe_load_all(result.stdout)
        if d and d["kind"] == "Deployment"
    }
    api = deployments["api"]
    web_container = deployments["web"]["spec"]["template"]["spec"]["containers"][0]
    assert web_container["image"].startswith("memstack-package-web:")
    pod = api["spec"]["template"]["spec"]
    assert [wait["name"] for wait in pod["initContainers"]] == [
        "wait-for-postgres",
        "wait-for-redis",
    ]
    container = pod["containers"][0]
    assert container["image"].startswith("memstack-kernel:")
    assert {mount["mountPath"] for mount in container["volumeMounts"]} == {
        "/app/.env",
        "/run/memstack/publisher.pem",
    }
    env_names = {entry["name"] for entry in container["env"]}
    app_secret = next(entry for entry in container["env"] if entry["name"] == "SECRET_KEY")
    assert app_secret["valueFrom"]["secretKeyRef"]["name"] == "memstack-secrets"
    assert "PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES" in env_names
    assert env_names.isdisjoint({"NEO4J_PASSWORD", "AWS_SECRET_ACCESS_KEY"})
