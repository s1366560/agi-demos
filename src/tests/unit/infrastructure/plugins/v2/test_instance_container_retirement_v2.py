"""Zero-reference gates for the retired instance DI sub-container."""

from __future__ import annotations

from inspect import getsource
from pathlib import Path

import pytest

from src.configuration import containers
from src.configuration.di_container import DIContainer

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]


def test_legacy_instance_subcontainer_is_retired() -> None:
    assert "InstanceContainer" not in vars(containers)
    assert not (_ROOT / "src/configuration/containers/instance_container.py").exists()
    assert "self._instance" not in getsource(DIContainer.__init__)
