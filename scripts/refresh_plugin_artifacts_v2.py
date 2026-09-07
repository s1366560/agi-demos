"""Explicitly refresh selected repository artifact digests without changing trust metadata."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from src.domain.model.plugins.artifact_attestation_v2 import (
    artifact_digest_v2,
    python_artifact_source_v2,
)

_SOURCE_LANGUAGES = {
    "repo+python": (frozenset({".py"}), frozenset({"python"})),
    "repo+typescript": (frozenset({".ts", ".tsx"}), frozenset({"web", "desktop-renderer"})),
    "repo+rust": (frozenset({".rs"}), frozenset({"rust-server", "desktop-sidecar"})),
}


def refresh_declared_artifacts_v2(
    root: Path,
    directory: Path,
    module_refs: frozenset[str],
    *,
    check: bool,
) -> list[dict[str, object]]:
    """Validate every source and refresh only explicitly named unsigned artifacts.

    All validation finishes before any write. Check mode rejects drift without
    writing manifests; callers can then check their generated catalog outputs.
    """
    root = root.resolve()
    documents: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    changes: list[dict[str, object]] = []
    changed_paths: set[Path] = set()
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        documents.append((path, document))
        for module in document["modules"]:
            module_ref = module["module_ref"]
            if module_ref in seen:
                raise ValueError(f"duplicate artifact module: {module_ref}")
            seen.add(module_ref)
            source = _artifact_source_path(root, module)
            data = source.read_bytes()
            digest = artifact_digest_v2(data)
            artifact = module["artifact"]
            if digest == artifact["digest"]:
                continue
            if check or module_ref not in module_refs:
                raise ValueError(f"module {module_ref} artifact digest mismatch: expected {digest}")
            if artifact.get("signature") is not None or artifact.get("provenance") is not None:
                raise ValueError(
                    f"module {module_ref} artifact trust metadata requires re-attestation"
                )
            changes.append(
                {
                    "module_ref": module_ref,
                    "source": artifact["source"],
                    "previous_digest": artifact["digest"],
                    "digest": digest,
                    "size_bytes": len(data),
                }
            )
            artifact["digest"] = digest
            changed_paths.add(path)
    unknown = module_refs - seen
    if unknown:
        raise ValueError(f"unknown artifact modules: {', '.join(sorted(unknown))}")
    for path, document in documents:
        if path in changed_paths:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            temporary.replace(path)
    return changes


def _artifact_source_path(root: Path, module: dict[str, Any]) -> Path:
    source = module["artifact"]["source"]
    scheme, separator, raw_path = source.partition("://")
    language = _SOURCE_LANGUAGES.get(scheme)
    if not separator or language is None:
        raise ValueError(f"unsupported repository artifact source: {source}")
    suffixes, targets = language
    relative = PurePosixPath(raw_path)
    if (
        not raw_path
        or relative.is_absolute()
        or relative.as_posix() != raw_path
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.suffix not in suffixes
        or not module["targets"]
        or not set(module["targets"]).issubset(targets)
    ):
        raise ValueError(f"invalid repository artifact path or language: {source}")
    if scheme == "repo+python" and source != python_artifact_source_v2(module["entrypoint"]):
        raise ValueError(f"artifact does not match Python entrypoint: {source}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"artifact is not a repository-owned file: {source}")
    return path
