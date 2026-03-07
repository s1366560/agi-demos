"""Model catalog service with embedded snapshot.

Loads model metadata from an embedded JSON snapshot file generated
from the models.dev API via ``models_dev_fetcher.py``.  Implements
``ModelCatalogPort`` for read-only model lookups.

When a model is not found in the snapshot, a conservative
``FALLBACK_MODEL_METADATA`` is returned instead of ``None`` (via
the ``get_model_or_fallback`` helper).

Since v3.0.0 the snapshot is the sole authoritative source.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, override

from src.domain.llm_providers.models import (
    FALLBACK_MODEL_METADATA,
    ModelMetadata,
)
from src.domain.llm_providers.repositories import ModelCatalogPort

logger = logging.getLogger(__name__)

_SNAPSHOT_PATH = Path(__file__).parent / "models_snapshot.json"
_STALENESS_THRESHOLD_DAYS = 30

class ModelCatalogService(ModelCatalogPort):
    """In-memory model catalog backed by an embedded JSON snapshot.

    On first access the catalog loads from ``models_snapshot.json``.
    The snapshot is the sole data source (since v3.0.0).

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

    def refresh(self, *, from_remote: bool = False) -> None:
        """Reload the catalog.

        Args:
            from_remote: If True, fetch fresh data from models.dev API
                and regenerate the local snapshot before reloading.
                Requires network access.  Falls back to the existing
                snapshot on failure.
        """
        if from_remote:
            self._refresh_from_remote()
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

    def is_reasoning_model(self, model_name: str) -> bool | None:
        """Check whether *model_name* is a reasoning/thinking model.

        Returns ``True``/``False`` if the model is known, ``None`` if unknown
        (caller should fall back to heuristic detection).
        """
        self._ensure_loaded()
        meta = self._models.get(model_name)
        if meta is None:
            return None
        return meta.reasoning

    def model_supports_temperature(self, model_name: str) -> bool | None:
        """Check whether *model_name* accepts the temperature parameter.

        Returns ``True``/``False`` if the model is known, ``None`` if unknown
        (caller should fall back to heuristic detection).
        """
        self._ensure_loaded()
        meta = self._models.get(model_name)
        if meta is None:
            return None
        return meta.supports_temperature

    def get_model_fuzzy(self, model_name: str) -> ModelMetadata | None:
        """Look up a model, stripping provider prefix if needed.

        Tries exact match first, then strips common ``provider/`` prefixes
        (e.g. ``openai/gpt-4o`` -> ``gpt-4o``).
        """
        self._ensure_loaded()
        meta = self._models.get(model_name)
        if meta is not None:
            return meta
        # Strip provider prefix
        if "/" in model_name:
            bare = model_name.split("/", 1)[-1]
            return self._models.get(bare)
        return None

    def get_model_or_fallback(self, model_name: str) -> ModelMetadata:
        """Return model metadata, falling back to conservative defaults.

        Unlike ``get_model`` which returns ``None`` for unknown models,
        this method always returns a ``ModelMetadata`` instance.  For
        unknown models it returns a copy of ``FALLBACK_MODEL_METADATA``
        with the ``name`` field set to *model_name*.
        """
        self._ensure_loaded()
        meta = self._models.get(model_name)
        if meta is not None:
            return meta
        # Strip provider prefix and retry
        if "/" in model_name:
            bare = model_name.split("/", 1)[-1]
            meta = self._models.get(bare)
            if meta is not None:
                return meta
        # Conservative fallback
        return ModelMetadata(
            name=model_name,
            context_length=FALLBACK_MODEL_METADATA.context_length,
            max_output_tokens=FALLBACK_MODEL_METADATA.max_output_tokens,
            input_cost_per_1m=FALLBACK_MODEL_METADATA.input_cost_per_1m,
            output_cost_per_1m=FALLBACK_MODEL_METADATA.output_cost_per_1m,
            capabilities=list(FALLBACK_MODEL_METADATA.capabilities),
            supports_streaming=FALLBACK_MODEL_METADATA.supports_streaming,
            supports_json_mode=FALLBACK_MODEL_METADATA.supports_json_mode,
            provider=FALLBACK_MODEL_METADATA.provider,
            modalities=list(FALLBACK_MODEL_METADATA.modalities),
            description=(
                f"Unknown model '{model_name}' with conservative defaults"
            ),
        )
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
        """Load snapshot JSON into the in-memory catalog."""
        # Snapshot is the sole data source (since v3.0.0)
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
                self._check_staleness(raw)
            except Exception:
                logger.exception(
                    "Failed to load model snapshot from %s",
                    self._snapshot_path,
                )
        else:
            logger.warning(
                "Model snapshot not found at %s; catalog will be empty",
                self._snapshot_path,
            )

    def _check_staleness(self, raw: dict[str, Any]) -> None:
        """Log a warning when the snapshot is older than the threshold."""
        meta = raw.get("_meta", {})
        generated_at_str = meta.get("generated_at")
        if not generated_at_str:
            return
        try:
            generated_at = datetime.fromisoformat(
                generated_at_str.replace("Z", "+00:00")
            )
            age_days = (
                datetime.now(UTC) - generated_at
            ).days
            if age_days > _STALENESS_THRESHOLD_DAYS:
                logger.warning(
                    "Model snapshot is %d days old (generated %s). "
                    "Run 'python -m src.infrastructure.llm"
                    ".models_dev_fetcher --force' to refresh.",
                    age_days,
                    generated_at_str,
                )
        except (ValueError, TypeError):
            logger.debug(
                "Could not parse snapshot generated_at: %s",
                generated_at_str,
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

    def _refresh_from_remote(self) -> None:
        """Fetch models.dev data and regenerate the local snapshot."""
        try:
            from src.infrastructure.llm.models_dev_fetcher import (
                convert_to_model_metadata,
                fetch_models_dev,
                generate_snapshot,
            )

            raw = fetch_models_dev()
            models = convert_to_model_metadata(raw)
            generate_snapshot(models, output_path=self._snapshot_path)
            logger.info(
                "Refreshed snapshot from models.dev: %d models",
                len(models),
            )
        except Exception:
            logger.exception(
                "Failed to refresh from models.dev; keeping existing snapshot"
            )


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
