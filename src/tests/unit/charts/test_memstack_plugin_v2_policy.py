"""Helm deployment policy gates for protocol-v2 publication readiness."""

from __future__ import annotations

import shutil
import subprocess
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
def test_helm_rejects_production_without_explicit_v2_roster() -> None:
    assert _HELM is not None
    result = subprocess.run(
        [
            _HELM,
            "template",
            "memstack-policy-test",
            str(_CHART),
            "--set-string",
            "config.environment=production",
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
def test_production_chart_renders_exact_v2_policy() -> None:
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
