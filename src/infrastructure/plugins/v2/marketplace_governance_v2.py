"""Search, update hints, and a minimal publish-review queue.

This is not a second marketplace. It projects packages the catalog already stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True, kw_only=True)
class CatalogProjectionRowV2:
    plugin_id: str
    version: str
    permissions: tuple[str, ...]
    revoked: bool


@dataclass(frozen=True, kw_only=True)
class ReviewRequestV2:
    review_id: str
    plugin_id: str
    version: str
    digest: str
    status: str
    note: str


class MarketplaceReviewQueueV2:
    def __init__(self) -> None:
        self._rows: dict[str, ReviewRequestV2] = {}

    def submit(self, *, plugin_id: str, version: str, digest: str, note: str) -> ReviewRequestV2:
        review_id = str(uuid4())
        row = ReviewRequestV2(
            review_id=review_id,
            plugin_id=plugin_id,
            version=version,
            digest=digest,
            status="pending",
            note=note,
        )
        self._rows[review_id] = row
        return row

    def list(self, status: str | None = None) -> tuple[ReviewRequestV2, ...]:
        rows = list(self._rows.values())
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return tuple(sorted(rows, key=lambda row: row.review_id))

    def decide(self, review_id: str, status: str) -> ReviewRequestV2:
        if status not in {"approved", "rejected"}:
            raise ValueError("review decision must be approved or rejected")
        current = self._rows.get(review_id)
        if current is None:
            raise KeyError(review_id)
        updated = ReviewRequestV2(
            review_id=current.review_id,
            plugin_id=current.plugin_id,
            version=current.version,
            digest=current.digest,
            status=status,
            note=current.note,
        )
        self._rows[review_id] = updated
        return updated


def projection_row_from_package_v2(package: object) -> CatalogProjectionRowV2:
    """Read one governance row without trusting a caller-supplied scan flag."""
    plugin_id = str(getattr(package, "plugin_id", ""))
    version = str(getattr(package, "version", ""))
    revoked = bool(getattr(package, "revoked", False))
    manifest = getattr(package, "manifest", {})
    permissions: list[str] = []
    manifests = manifest.get("manifests", []) if isinstance(manifest, dict) else []
    if isinstance(manifests, list):
        for item in manifests:
            if not isinstance(item, dict):
                continue
            declared = item.get("permissions", [])
            if isinstance(declared, list):
                permissions.extend(value for value in declared if isinstance(value, str))
    return CatalogProjectionRowV2(
        plugin_id=plugin_id,
        version=version,
        permissions=tuple(dict.fromkeys(permissions)),
        revoked=revoked,
    )


def project_catalog_v2(
    rows: tuple[CatalogProjectionRowV2, ...] | list[CatalogProjectionRowV2],
    *,
    query: str = "",
    permission: str | None = None,
) -> tuple[CatalogProjectionRowV2, ...]:
    needle = query.casefold()
    projected = [
        row
        for row in rows
        if (not needle or needle in row.plugin_id.casefold() or needle in row.version.casefold())
        and (permission is None or permission in row.permissions)
        and not row.revoked
    ]
    return tuple(sorted(projected, key=lambda row: (row.plugin_id, row.version)))


def update_available_v2(
    installed: dict[str, str], rows: list[CatalogProjectionRowV2] | tuple[CatalogProjectionRowV2, ...]
) -> tuple[dict[str, str], ...]:
    latest: dict[str, str] = {}
    for row in rows:
        if row.revoked:
            continue
        current = latest.get(row.plugin_id)
        if current is None or _version_key(row.version) > _version_key(current):
            latest[row.plugin_id] = row.version
    hints = []
    for plugin_id, installed_version in sorted(installed.items()):
        candidate = latest.get(plugin_id)
        if candidate is not None and _version_key(candidate) > _version_key(installed_version):
            hints.append(
                {
                    "plugin_id": plugin_id,
                    "installed_version": installed_version,
                    "available_version": candidate,
                }
            )
    return tuple(hints)


def _version_key(version: str) -> tuple[int, ...]:
    numbers = []
    for part in version.split("."):
        digits = "".join(character for character in part if character.isdigit())
        numbers.append(int(digits) if digits else 0)
    return tuple(numbers)
