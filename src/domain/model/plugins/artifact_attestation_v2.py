"""Pure canonical-byte rules for protocol-v2 Python plugin artifacts."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

PYTHON_ARTIFACT_SOURCE_PREFIX_V2 = "repo+python://"


def artifact_digest_v2(content: bytes) -> str:
    """Hash exact artifact bytes without text or line-ending normalization."""
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def python_artifact_path_v2(entrypoint: str) -> PurePosixPath:
    """Map one strict ``module:symbol`` entrypoint to its canonical source path."""
    if entrypoint.count(":") != 1:
        raise ValueError("Python plugin entrypoint must use module:symbol")
    module_name, symbol_name = entrypoint.split(":", maxsplit=1)
    module_parts = module_name.split(".")
    if (
        not module_parts
        or any(not part or not part.isidentifier() for part in module_parts)
        or not symbol_name.isidentifier()
    ):
        raise ValueError("Python plugin entrypoint must contain identifiers only")
    return PurePosixPath(*module_parts).with_suffix(".py")


def python_artifact_source_v2(entrypoint: str) -> str:
    """Return the canonical repository URI for one Python entrypoint artifact."""
    return f"{PYTHON_ARTIFACT_SOURCE_PREFIX_V2}{python_artifact_path_v2(entrypoint)}"


__all__ = [
    "PYTHON_ARTIFACT_SOURCE_PREFIX_V2",
    "artifact_digest_v2",
    "python_artifact_path_v2",
    "python_artifact_source_v2",
]
