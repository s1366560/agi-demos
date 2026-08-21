"""Zero-reference gates for the retired static workflow composition seam."""

from __future__ import annotations

from inspect import signature
from pathlib import Path

import pytest

from src.configuration.containers.infra_container import InfraContainer
from src.configuration.di_container import DIContainer
from src.configuration.service_bindings import CONTAINER_SERVICE_BINDINGS
from src.infrastructure.adapters.primary.web import dependencies

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]


def test_static_workflow_accessors_and_constructor_injection_are_removed() -> None:
    binding_keys = {binding.key for binding in CONTAINER_SERVICE_BINDINGS}

    assert "get_workflow_engine" not in vars(dependencies)
    assert "workflow_engine_port" not in vars(DIContainer)
    assert "workflow_engine_port" not in vars(InfraContainer)
    assert "workflow_engine" not in signature(DIContainer).parameters
    assert "workflow_engine" not in signature(InfraContainer).parameters
    assert "workflow_engine_port" not in binding_keys


def test_lifespan_no_longer_owns_or_publishes_a_workflow_engine() -> None:
    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )
    startup_source = (
        _ROOT / "src/infrastructure/adapters/primary/web/startup/__init__.py"
    ).read_text(encoding="utf-8")

    assert "initialize_workflow_engine" not in main_source
    assert "app.state.workflow_engine" not in main_source
    assert "initialize_workflow_engine" not in startup_source
    assert "container = initialize_container(redis_client=redis_client)" in main_source
