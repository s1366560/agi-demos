"""Model catalog service with embedded snapshot.

Loads model metadata from an embedded JSON snapshot file and merges
with ``DEFAULT_MODEL_METADATA`` from the domain layer.  Implements
``ModelCatalogPort`` for read-only model lookups.
"""

import json
import logging
from pathlib import Path
from typing import Any, override

from src.domain.llm_providers.models import (
    DEFAULT_MODEL_METADATA,
    ModelMetadata,
)
from src.domain.llm_providers.repositories import ModelCatalogPort

logger = logging.getLogger(__name__)

_SNAPSHOT_PATH = Path(__file__).parent / "models_snapshot.json"


class ModelCatalogService(ModelCatalogPort):
    """In-memory model catalog backed by an embedded JSON snapshot.

    On first access the catalog loads from ``models_snapshot.json``
    and merges with ``DEFAULT_MODEL_METADATA``.  The snapshot takes
    precedence over domain defaults for overlapping model names.

    Thread-safety: the catalog is loaded once and thereafter read-only.
    """

    def __init__(
        self,
        snapshot_path: Path | None = None,
    ) -> None:
        self._snapshot_path = snapshot_path or _SNAPSHOT_PATH
        self._models: dict[str, ModelMetadata] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # ModelCatalogPort implementation
    # ------------------------------------------------------------------

    @override
    def get_model(self, model_name: str) -> ModelMetadata | None:
        """Get metadata for a specific model by exact name."""
        self._ensure_loaded()
        return self._models.get(model_name)

    @override
    def search_models(
        self,
        query: str,
        provider: str | None = None,
        limit: int = 20,
    ) -> list[ModelMetadata]:
        """Search models by name substring or keyword."""
        self._ensure_loaded()
        query_lower = query.lower()
        results: list[ModelMetadata] = []
        for meta in self._models.values():
            if provider and meta.provider != provider:
                continue
            if self._matches_query(meta, query_lower):
                results.append(meta)
            if len(results) >= limit:
                break
        return results

    @override
    def list_models(
        self,
        provider: str | None = None,
        include_deprecated: bool = False,
    ) -> list[ModelMetadata]:
        """List all known models, optionally filtered."""
        self._ensure_loaded()
        results: list[ModelMetadata] = []
        for meta in self._models.values():
            if provider and meta.provider != provider:
                continue
            if not include_deprecated and meta.is_deprecated:
                continue
            results.append(meta)
        return results

    @override
    def get_variants(self, base_model: str) -> list[ModelMetadata]:
        """Get all variants of a base model.

        Variants are models whose name starts with ``{base_model}-``
        (excluding the base model itself).
        """
        self._ensure_loaded()
        prefix = f"{base_model}-"
        results: list[ModelMetadata] = []
        for name, meta in self._models.items():
            if name == base_model:
                continue
            if name.startswith(prefix):
                results.append(meta)
        return results

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the catalog from the snapshot file.

        This is a stub for future remote-refresh support.
        Currently re-reads the local JSON file.
        """
        self._loaded = False
        self._models.clear()
        self._ensure_loaded()

    @property
    def model_count(self) -> int:
        """Number of models in the catalog."""
        self._ensure_loaded()
        return len(self._models)

    def supports_vision(self, model_name: str) -> bool:
        """Check whether *model_name* supports image/vision inputs.

        Inspects ``ModelMetadata.capabilities`` for ``ModelCapability.VISION``
        (case-insensitive) and ``ModelMetadata.modalities`` for ``"image"``.
        Returns ``False`` for unknown models.
        """
        self._ensure_loaded()
        meta = self._models.get(model_name)
        if meta is None:
            return False
        if any(c.lower() == "vision" for c in meta.capabilities):
            return True
        return "image" in meta.modalities

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Lazily load the catalog on first access."""
        if self._loaded:
            return
        self._load()
        self._loaded = True

    def _load(self) -> None:
        """Load snapshot JSON and merge with domain defaults."""
        # Start with domain defaults
        for name, meta in DEFAULT_MODEL_METADATA.items():
            self._models[name] = meta

        # Overlay snapshot data (takes precedence)
        if self._snapshot_path.exists():
            try:
                raw = json.loads(self._snapshot_path.read_text("utf-8"))
                models_raw: dict[str, Any] = raw.get("models", {})
                for name, data in models_raw.items():
                    self._models[name] = ModelMetadata(**data)
                logger.info(
                    "Loaded %d models from snapshot %s",
                    len(models_raw),
                    self._snapshot_path.name,
                )
            except Exception:
                logger.exception(
                    "Failed to load model snapshot from %s; falling back to domain defaults",
                    self._snapshot_path,
                )
        else:
            logger.warning(
                "Model snapshot not found at %s; using domain defaults only",
                self._snapshot_path,
            )

    @staticmethod
    def _matches_query(meta: ModelMetadata, query: str) -> bool:
        """Check if a model matches a search query."""
        if query in meta.name.lower():
            return True
        if meta.family and query in meta.family.lower():
            return True
        if meta.provider and query in meta.provider.lower():
            return True
        return bool(meta.description and query in meta.description.lower())


# ------------------------------------------------------------------
# Singleton accessor
# ------------------------------------------------------------------

_instance: ModelCatalogService | None = None


def get_model_catalog_service() -> ModelCatalogService:
    """Return the global ``ModelCatalogService`` singleton."""
    global _instance
    if _instance is None:
        _instance = ModelCatalogService()
    return _instance
