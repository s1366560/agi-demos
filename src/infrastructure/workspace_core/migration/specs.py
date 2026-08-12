"""Ordered, lossless source-to-Avernet Workspace migration manifest."""

from __future__ import annotations

from .model import MigrationSpec
from .specs_base import BASE_SPECS
from .specs_execution import EXECUTION_SPECS

MIGRATION_SPECS: tuple[MigrationSpec, ...] = (*BASE_SPECS, *EXECUTION_SPECS)
