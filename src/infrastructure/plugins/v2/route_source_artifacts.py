"""Repository-owned source artifact attestations for generated route contracts."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import rfc8785
from fastapi import APIRouter

_DIGEST_PREFIX_V2 = "sha256:"


class RouteSourceArtifactErrorV2(RuntimeError):
    """Raised when a source artifact record is malformed or stale."""


@dataclass(frozen=True, kw_only=True)
class RouteSourceArtifactV2:
    path: str
    digest: str

    @classmethod
    def from_payload(cls, payload: object, *, row_id: str) -> RouteSourceArtifactV2:
        if not isinstance(payload, dict):
            raise RouteSourceArtifactErrorV2(
                f"catalog row {row_id} source artifact must be an object"
            )
        path = payload.get("path")
        if not isinstance(path, str) or not path or Path(path).is_absolute():
            raise RouteSourceArtifactErrorV2(
                f"catalog row {row_id} source artifact path must be relative"
            )
        digest = payload.get("digest")
        if not _is_digest_v2(digest):
            raise RouteSourceArtifactErrorV2(
                f"catalog row {row_id} source artifact digest must be a sha256 digest"
            )
        return cls(path=path, digest=cast("str", digest))

    def to_payload(self) -> dict[str, str]:
        return {"path": self.path, "digest": self.digest}


def source_artifacts_for_target_v2(
    target: object,
    *,
    root: Path,
) -> tuple[RouteSourceArtifactV2, ...]:
    sources: dict[str, RouteSourceArtifactV2] = {}
    candidates: list[object] = [target]
    if isinstance(target, APIRouter):
        candidates.extend(getattr(route, "endpoint", None) for route in target.routes)
    for candidate in candidates:
        path = _source_path_v2(candidate)
        if path is None or not path.is_file():
            continue
        try:
            name = str(path.resolve().relative_to(root))
        except ValueError:
            continue
        sources[name] = RouteSourceArtifactV2(
            path=name,
            digest=_DIGEST_PREFIX_V2 + hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    if not sources:
        raise RouteSourceArtifactErrorV2(
            "route inventory target has no repository-owned source artifact"
        )
    return tuple(sources[name] for name in sorted(sources))


def source_fingerprint_from_artifacts_v2(
    *,
    row_id: str,
    inventory_kind: str,
    module: str,
    expression: str,
    prefix: str | None,
    artifacts: Sequence[RouteSourceArtifactV2],
) -> str:
    return _digest_payload_v2(
        {
            "inventory": {
                "row_id": row_id,
                "kind": inventory_kind,
                "module": module,
                "expression": expression,
                "prefix": prefix,
            },
            "source_artifacts": [artifact.to_payload() for artifact in artifacts],
        }
    )


def validate_source_artifacts_v2(
    rows: Sequence[tuple[str, Sequence[RouteSourceArtifactV2]]],
    *,
    root: Path,
) -> None:
    checked: dict[str, str] = {}
    for _row_id, artifacts in rows:
        for artifact in artifacts:
            expected = checked.get(artifact.path)
            if expected is None:
                path = (root / artifact.path).resolve()
                try:
                    path.relative_to(root)
                except ValueError as exc:
                    raise RouteSourceArtifactErrorV2(
                        f"route source artifact escapes repository root: {artifact.path}"
                    ) from exc
                try:
                    expected = _DIGEST_PREFIX_V2 + hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError as exc:
                    raise RouteSourceArtifactErrorV2(
                        f"cannot read route source artifact {artifact.path}: {exc}"
                    ) from exc
                checked[artifact.path] = expected
            if artifact.digest != expected:
                raise RouteSourceArtifactErrorV2(
                    f"route source artifact digest mismatch: {artifact.path}"
                )


def _source_path_v2(target: object) -> Path | None:
    if target is None:
        return None
    if isinstance(target, ModuleType):
        raw = getattr(target, "__file__", None)
    elif inspect.isclass(target) or inspect.isroutine(target):
        raw = inspect.getsourcefile(target)
    else:
        raw = None
    return Path(raw) if isinstance(raw, str) else None


def _digest_payload_v2(payload: object) -> str:
    canonical = rfc8785.dumps(cast("Any", payload))
    return _DIGEST_PREFIX_V2 + hashlib.sha256(canonical).hexdigest()


def _is_digest_v2(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX_V2):
        return False
    digest = value.removeprefix(_DIGEST_PREFIX_V2)
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


__all__ = [
    "RouteSourceArtifactErrorV2",
    "RouteSourceArtifactV2",
    "source_artifacts_for_target_v2",
    "source_fingerprint_from_artifacts_v2",
    "validate_source_artifacts_v2",
]
