"""Offline effective-profile dump, the dsh ``--dump-config`` equivalent.

The dump composes exactly what a boot would mount: the base profile document,
then any ordered patch overlays, rendered with per-layer provenance comments
so operators can audit which layer contributed each row. Composition reuses
:func:`compose_profile`, so the dump cannot drift from the runtime snapshot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml

from .builtin_manifests import default_builtin_manifests
from .profile import (
    ProfileDocument,
    ProfilePatch,
    ProfileSnapshot,
    _parse_patch,
    compose_profile,
    parse_profile_document,
)

DEFAULT_PROFILE_PATH = Path("config/plugin-profiles/memstack-default.yaml")

__all__ = [
    "DEFAULT_PROFILE_PATH",
    "DumpConfigError",
    "dump_profile",
    "load_patch_overlays",
    "load_profile_document",
    "render_dump",
]


class DumpConfigError(RuntimeError):
    """Raised when a profile or overlay cannot be read, parsed, or composed."""


def load_profile_document(path: Path) -> ProfileDocument:
    """Load and validate one profile document from disk."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DumpConfigError(f"cannot read profile {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise DumpConfigError(f"cannot parse profile {path}: {exc}") from exc
    try:
        return parse_profile_document(payload)
    except Exception as exc:
        raise DumpConfigError(f"invalid profile {path}: {exc}") from exc


def load_patch_overlays(paths: tuple[Path, ...] | list[Path]) -> tuple[ProfilePatch, ...]:
    """Load ordered patch overlays; each file holds a top-level patch list.

    A file may either be a bare list of patches or an object with a
    ``patches`` list. An absent file is an error: the caller named it.
    """
    patches: list[ProfilePatch] = []
    for path in paths:
        try:
            payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise DumpConfigError(f"cannot read patch overlay {path}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise DumpConfigError(f"cannot parse patch overlay {path}: {exc}") from exc
        if isinstance(payload, dict):
            payload = payload.get("patches")
        if not isinstance(payload, list):
            raise DumpConfigError(f"patch overlay {path} must be a list or hold a patches list")
        for index, raw in enumerate(payload):
            try:
                patches.append(_parse_patch(raw, index))
            except Exception as exc:
                raise DumpConfigError(f"invalid patch in {path}: {exc}") from exc
    return tuple(patches)


def render_dump(
    snapshot: ProfileSnapshot,
    *,
    source_labels: tuple[str, ...] = (),
    fmt: Literal["yaml", "json"] = "yaml",
) -> str:
    """Render one composed snapshot with provenance annotations."""
    if fmt == "json":
        return snapshot.to_json()
    header = [
        f"# effective profile: {snapshot.profile_id}",
        f"# digest: {snapshot.digest}",
    ]
    if source_labels:
        header.append(f"# sources: {', '.join(source_labels)}")
    lines = [
        *header,
        "schemaVersion: 1",
        f"profile_id: {snapshot.profile_id}",
        f"digest: {snapshot.digest}",
        "plugins:",
    ]
    if not snapshot.rows:
        lines.append("  []")
        return "\n".join(lines) + "\n"
    previous_layer: str | None = None
    for row in snapshot.rows:
        if row.layer_id != previous_layer:
            lines.append(f"  # == layer {row.layer_id}")
            previous_layer = row.layer_id
        body = yaml.safe_dump(row.to_payload(), sort_keys=True).rstrip()
        body_lines = body.splitlines()
        lines.append(f"  - {body_lines[0]}")
        lines.extend(f"    {line}" for line in body_lines[1:])
    return "\n".join(lines) + "\n"


def dump_profile(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    patch_paths: tuple[Path, ...] | list[Path] = (),
    *,
    fmt: Literal["yaml", "json"] = "yaml",
) -> str:
    """Compose the effective profile and render it with layer provenance."""
    document = load_profile_document(profile_path)
    overlays = load_patch_overlays(tuple(patch_paths))
    effective_document = ProfileDocument(
        profile_id=document.profile_id,
        layers=document.layers,
        patches=(*document.patches, *overlays),
    )
    try:
        snapshot = compose_profile(effective_document, default_builtin_manifests())
    except Exception as exc:
        raise DumpConfigError(f"profile {profile_path} does not compose: {exc}") from exc
    labels = (str(profile_path), *(str(path) for path in patch_paths))
    return render_dump(snapshot, source_labels=labels, fmt=fmt)
