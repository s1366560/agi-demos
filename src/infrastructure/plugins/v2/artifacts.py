"""Artifact resolution that separates byte attestation from Python import."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol

from src.domain.model.plugins.artifact_attestation_v2 import (
    python_artifact_path_v2,
    python_artifact_source_v2,
)
from src.domain.model.plugins.generated_v2 import PluginModuleV2

from .runtime_context import RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class ResolvedPluginArtifactV2:
    """Unloaded entrypoint plus the exact bytes that must authorize its import."""

    module_ref: str
    entrypoint: str
    source: str
    canonical_bytes: bytes
    load: Callable[[], object]


class PluginArtifactResolverV2(Protocol):
    """Resolve artifact bytes without importing or executing plugin code."""

    def resolve(self, module: PluginModuleV2) -> ResolvedPluginArtifactV2: ...


class RepositoryPythonArtifactResolverV2:
    """Resolve trusted Python source artifacts anchored inside one repository root."""

    def __init__(self, repository_root: str | Path | None = None) -> None:
        default_root = Path(__file__).resolve().parents[4]
        self._root = Path(repository_root or default_root).resolve()

    def resolve(self, module: PluginModuleV2) -> ResolvedPluginArtifactV2:
        try:
            relative_path = python_artifact_path_v2(module.entrypoint)
            expected_source = python_artifact_source_v2(module.entrypoint)
        except ValueError as exc:
            raise RuntimeV2Error("invalid_plugin_entrypoint", str(exc)) from exc
        if module.artifact.source != expected_source:
            raise RuntimeV2Error(
                "artifact_source_mismatch",
                f"module {module.module_ref} artifact source does not match its entrypoint",
            )
        source_path = (self._root / relative_path).resolve()
        if not source_path.is_relative_to(self._root) or not source_path.is_file():
            raise RuntimeV2Error(
                "artifact_resolution_failed",
                f"module {module.module_ref} artifact source is unavailable",
            )
        try:
            canonical_bytes = source_path.read_bytes()
        except OSError as exc:
            raise RuntimeV2Error(
                "artifact_resolution_failed",
                f"module {module.module_ref} artifact source could not be read",
            ) from exc
        module_name, symbol_name = module.entrypoint.split(":", maxsplit=1)
        loaded_before_resolution = module_name in sys.modules

        def load() -> object:
            if loaded_before_resolution:
                raise RuntimeV2Error(
                    "artifact_loaded_before_attestation",
                    f"module {module.module_ref} entrypoint was imported before verified loading",
                )
            _assert_unchanged(module.module_ref, source_path, canonical_bytes)
            imported = sys.modules.get(module_name)
            if imported is None:
                try:
                    imported = importlib.import_module(module_name)
                except Exception as exc:
                    raise RuntimeV2Error(
                        "artifact_entrypoint_load_failed",
                        f"module {module.module_ref} entrypoint import failed",
                    ) from exc
            _validate_import_origin(module.module_ref, imported, source_path)
            _assert_unchanged(module.module_ref, source_path, canonical_bytes)
            try:
                return getattr(imported, symbol_name)
            except AttributeError as exc:
                raise RuntimeV2Error(
                    "artifact_entrypoint_missing",
                    f"module {module.module_ref} entrypoint symbol is unavailable",
                ) from exc

        return ResolvedPluginArtifactV2(
            module_ref=module.module_ref,
            entrypoint=module.entrypoint,
            source=module.artifact.source,
            canonical_bytes=canonical_bytes,
            load=load,
        )


def _assert_unchanged(module_ref: str, path: Path, expected: bytes) -> None:
    try:
        current = path.read_bytes()
    except OSError as exc:
        raise RuntimeV2Error(
            "artifact_changed_after_verification",
            f"module {module_ref} artifact became unreadable after verification",
        ) from exc
    if current != expected:
        raise RuntimeV2Error(
            "artifact_changed_after_verification",
            f"module {module_ref} artifact changed after verification",
        )


def _validate_import_origin(module_ref: str, module: ModuleType, expected: Path) -> None:
    origin = getattr(module, "__file__", None)
    if not isinstance(origin, str) or Path(origin).resolve() != expected:
        raise RuntimeV2Error(
            "artifact_import_origin_mismatch",
            f"module {module_ref} imported from an unexpected source",
        )


__all__ = [
    "PluginArtifactResolverV2",
    "RepositoryPythonArtifactResolverV2",
    "ResolvedPluginArtifactV2",
]
