"""Artifact resolution that separates byte attestation from Python import."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import threading
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

_VERIFIED_MODULES_LOCK_V2 = threading.RLock()
_VERIFIED_ORIGINAL_MODULES_V2: dict[str, tuple[str, ModuleType]] = {}
_VERIFIED_ARTIFACT_MODULES_V2: dict[tuple[str, str, str], ModuleType] = {}


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
        loaded_before_resolution = sys.modules.get(module_name)

        def load() -> object:
            _assert_unchanged(module.module_ref, source_path, canonical_bytes)
            imported = _load_attested_module_v2(
                module_ref=module.module_ref,
                module_name=module_name,
                artifact_digest=module.artifact.digest,
                source_path=source_path,
                canonical_bytes=canonical_bytes,
                loaded_before_resolution=loaded_before_resolution,
            )
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


def _load_attested_module_v2(
    *,
    module_ref: str,
    module_name: str,
    artifact_digest: str,
    source_path: Path,
    canonical_bytes: bytes,
    loaded_before_resolution: ModuleType | None,
) -> ModuleType:
    with _VERIFIED_MODULES_LOCK_V2:
        if loaded_before_resolution is not None and not _is_verified_original_module_v2(
            module_name,
            loaded_before_resolution,
        ):
            raise RuntimeV2Error(
                "artifact_loaded_before_attestation",
                f"module {module_ref} entrypoint was imported before verified loading",
            )

        current = sys.modules.get(module_name)
        if current is not None:
            registered = _VERIFIED_ORIGINAL_MODULES_V2.get(module_name)
            if registered is None or registered[1] is not current:
                raise RuntimeV2Error(
                    "artifact_loaded_before_attestation",
                    f"module {module_ref} entrypoint was imported before verified loading",
                )
            if registered[0] == artifact_digest:
                _validate_import_origin(module_ref, current, source_path)
                return current

        cache_key = (module_name, str(source_path), artifact_digest)
        cached = _VERIFIED_ARTIFACT_MODULES_V2.get(cache_key)
        if cached is not None:
            _validate_import_origin(module_ref, cached, source_path)
            return cached

        execution_name = (
            module_name
            if current is None
            else _isolated_module_name_v2(module_name, source_path, artifact_digest)
        )
        imported = _execute_attested_module_v2(
            module_ref=module_ref,
            module_name=execution_name,
            source_path=source_path,
            canonical_bytes=canonical_bytes,
        )
        _VERIFIED_ARTIFACT_MODULES_V2[cache_key] = imported
        if execution_name == module_name:
            _VERIFIED_ORIGINAL_MODULES_V2[module_name] = (artifact_digest, imported)
        return imported


def _is_verified_original_module_v2(module_name: str, module: ModuleType) -> bool:
    registered = _VERIFIED_ORIGINAL_MODULES_V2.get(module_name)
    return registered is not None and registered[1] is module


def _isolated_module_name_v2(module_name: str, source_path: Path, artifact_digest: str) -> str:
    parent, separator, leaf = module_name.rpartition(".")
    identity = f"{source_path}\0{artifact_digest}".encode()
    suffix = hashlib.sha256(identity).hexdigest()[:24]
    isolated_leaf = f"__memstack_v2_{leaf}_{suffix}"
    return f"{parent}{separator}{isolated_leaf}" if parent else isolated_leaf


def _execute_attested_module_v2(
    *,
    module_ref: str,
    module_name: str,
    source_path: Path,
    canonical_bytes: bytes,
) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise RuntimeV2Error(
            "artifact_entrypoint_load_failed",
            f"module {module_ref} entrypoint import spec is unavailable",
        )
    imported = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = imported
    try:
        code = compile(canonical_bytes, str(source_path), "exec")
        exec(code, imported.__dict__)  # noqa: S102
    except Exception as exc:
        if previous is None:
            _ = sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise RuntimeV2Error(
            "artifact_entrypoint_load_failed",
            f"module {module_ref} entrypoint import failed",
        ) from exc
    _validate_import_origin(module_ref, imported, source_path)
    _assert_unchanged(module_ref, source_path, canonical_bytes)
    return imported


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
