# Feishu Plugin Migration Plan

> **Historical V1 document — do not execute.** This plan describes the retired protocol-V1
> `.memstack/plugins` runtime and its compatibility facade. The production authority is now the
> Cordis V2 contract catalog, profile, and generation runtime. Use
> `platform-plugin-kernel.md` and `plugin-capability-inventory.md` for the current architecture;
> do not recreate any loader, facade, manifest, or mutation path proposed below.

**Date**: 2026-03-14
**Status**: Historical / superseded by Cordis V2
**Goal**: Completely migrate the Feishu channel plugin from `src/infrastructure/adapters/secondary/channels/feishu/` to `.memstack/plugins/feishu/`, leaving zero Feishu code inside `src/`.

---

## Executive Summary

The Feishu integration currently lives inside `src/` as a traditional hexagonal-architecture adapter (16 files, ~4000+ lines). A thin 8-line shim at `.memstack/plugins/feishu/plugin.py` delegates to this code, but the plugin is not self-contained.

This plan migrates **all** Feishu code into `.memstack/plugins/feishu/` as a standalone local plugin, following the patterns established by `pdf-assistant` and `example-showcase`. After migration:

1. `.memstack/plugins/feishu/` is fully self-contained with its own manifest, entry point, and all implementation modules.
2. `src/infrastructure/adapters/secondary/channels/feishu/` is **deleted entirely**.
3. All external consumers (application services, routers, tests) are updated to import from the new location.
4. The `examples/plugins/memstack-plugin-feishu/` package template is updated.

**Estimated effort**: 2-3 days (including testing and verification).

---

## 1. Current State Inventory

### 1.1 Files to Migrate (16 files in `src/infrastructure/adapters/secondary/channels/feishu/`)

| File | Lines | Purpose |
|------|-------|---------|
| `plugin.py` | 65 | `FeishuChannelPlugin` class with `setup(api)` — registers channel type |
| `adapter.py` | 1327+ | `FeishuAdapter` — full channel adapter (WebSocket + Webhook modes) |
| `client.py` | 438 | `FeishuClient` — API client with lazy-loaded sub-clients |
| `webhook.py` | 229 | `FeishuWebhookHandler` + `FeishuEventDispatcher` |
| `media.py` | ~150 | `FeishuMediaManager` — image/file upload/download |
| `media_downloader.py` | ~100 | `FeishuMediaDownloader` — media download utility |
| `cards.py` | ~300 | `CardBuilder`, `PostBuilder` — card construction |
| `rich_cards.py` | ~200 | Rich card templates (progress, status, etc.) |
| `hitl_cards.py` | ~200 | HITL interactive card builders |
| `cardkit_streaming.py` | ~150 | CardKit streaming update support |
| `docx.py` | ~150 | `FeishuDocClient` — document operations |
| `wiki.py` | ~100 | `FeishuWikiClient` — knowledge base operations |
| `drive.py` | ~150 | `FeishuDriveClient` — cloud storage operations |
| `bitable.py` | ~200 | `FeishuBitableClient` — multi-dimensional table operations |
| `__init__.py` | 62 | Package exports (`__all__`) |

### 1.2 Current Plugin Shim (`.memstack/plugins/feishu/plugin.py`)

```python
"""Local Feishu plugin entry for .memstack/plugins discovery."""
from src.infrastructure.adapters.secondary.channels.feishu.plugin import FeishuChannelPlugin
plugin = FeishuChannelPlugin()
```

### 1.3 External Consumers (files outside `feishu/` that import Feishu code)

These files **must be updated** to import from the new location after migration:

| File | Imports Used | Category |
|------|-------------|----------|
| `src/application/services/channels/event_bridge.py` | `cardkit_streaming`, `hitl_cards`, `rich_cards` | **Application service** |
| `src/application/services/channels/channel_service_factory.py` | `media_downloader` | **Application service** |
| `src/application/services/channels/media_import_service.py` | `media_downloader` | **Application service** |
| `src/application/services/channels/channel_message_router.py` | `cardkit_streaming` | **Application service** |
| `src/infrastructure/adapters/primary/web/routers/channels.py` | `FeishuAdapter`, `FeishuWebhookHandler` | **Router** |
| `src/channels_example.py` | `FeishuAdapter`, various exports | **Example script** |
| `src/channels_enhanced_example.py` | various Feishu exports, `bitable` | **Example script** |
| `examples/plugins/memstack-plugin-feishu/src/.../plugin.py` | `FeishuAdapter` | **Package template** |
| `src/tests/unit/.../feishu/test_hitl_cards.py` | `hitl_cards` | **Test** |
| `src/tests/unit/.../feishu/test_cardkit_streaming.py` | `cardkit_streaming` | **Test** |
| `src/tests/unit/.../feishu/test_rich_cards.py` | `rich_cards` | **Test** |
| `src/tests/unit/.../feishu/test_adapter.py` | `FeishuAdapter` | **Test** |
| `src/tests/unit/.../feishu/test_plugin.py` | `FeishuAdapter` | **Test** |

---

## 2. Target Structure

```
.memstack/plugins/feishu/
  memstack.plugin.json       # NEW: plugin manifest
  __init__.py                 # NEW: package marker (empty)
  plugin.py                   # REWRITE: full FeishuChannelPlugin (not a shim)
  adapter.py                  # MOVE from src/
  client.py                   # MOVE from src/
  webhook.py                  # MOVE from src/
  media.py                    # MOVE from src/
  media_downloader.py         # MOVE from src/
  cards.py                    # MOVE from src/
  rich_cards.py               # MOVE from src/
  hitl_cards.py               # MOVE from src/
  cardkit_streaming.py        # MOVE from src/
  docx.py                     # MOVE from src/
  wiki.py                     # MOVE from src/
  drive.py                    # MOVE from src/
  bitable.py                  # MOVE from src/
  README.md                   # NEW: plugin documentation
```

---

## 3. Design Decisions

### 3.1 Import Strategy

**Problem**: Local plugins are loaded via `importlib.util.spec_from_file_location` WITHOUT a package context, so relative imports (`from .adapter import ...`) will NOT work.

**Solution**: Two import patterns coexist in the migrated plugin:

| Import Target | Pattern | Example |
|--------------|---------|---------|
| **Sibling plugin modules** | `_load_sibling()` helper | `_load_sibling("adapter.py").FeishuAdapter` |
| **`src/` domain/application types** | Absolute imports (unchanged) | `from src.domain.model.channels.message import Message` |

The `_load_sibling()` pattern is proven in `pdf-assistant` and `example-showcase`.

### 3.2 Intra-Module References

Currently, Feishu modules import each other using absolute paths:
```python
# In client.py
from src.infrastructure.adapters.secondary.channels.feishu.media import FeishuMediaManager
```

After migration, these become sibling-module loads via `_load_sibling()`. Since `_load_sibling()` calls happen at import time (module-level), we must handle **circular dependencies**:

| Module | Imports From |
|--------|-------------|
| `client.py` | `media.py`, `docx.py`, `wiki.py`, `drive.py`, `bitable.py`, `cards.py` |
| `adapter.py` | `hitl_cards.py`, `webhook.py` (lazy, inside functions) |
| `cardkit_streaming.py` | `adapter.py` (lazy, inside functions) |
| `media.py` | `client.py` |
| `docx.py` | `client.py` |
| `wiki.py` | `client.py` |
| `drive.py` | `client.py` |
| `bitable.py` | `client.py` |
| `media_downloader.py` | (no Feishu imports) |

**Circular chain**: `client.py` -> `media.py` -> `client.py`.

**Solution**: The existing code already handles this. `client.py` uses lazy imports inside `@property` methods (e.g., `self._media` is created on first access, not at import time). The sub-client modules (`media.py`, `docx.py`, etc.) accept a `FeishuClient` instance as a constructor parameter with a `TYPE_CHECKING`-guarded type annotation. This pattern continues to work after migration — each file will receive a `_PLUGIN_DIR` and `_load_sibling` at module level, but actual `_load_sibling()` calls for circular deps will be deferred to lazy property bodies.

### 3.3 Handling External Consumers

**Core problem**: 5 application-layer files in `src/` import Feishu-specific code (card builders, streaming, media downloader). This creates a hard coupling between the application layer and a specific channel plugin.

**Strategy: Re-export facade module**

Create a thin facade at `src/infrastructure/adapters/secondary/channels/feishu_facade.py` that re-exports symbols from the plugin location. This allows a **two-phase migration**:

- **Phase A** (this plan): Move all code. Update the facade to import from `.memstack/plugins/feishu/`. Update external consumers to use the facade.
- **Phase B** (future): Refactor application services to use channel-agnostic abstractions. Remove the facade entirely.

```python
# src/infrastructure/adapters/secondary/channels/feishu_facade.py
"""Thin re-export facade for Feishu plugin code.

This module exists as a transitional bridge so that application-layer code
(event_bridge.py, channel_service_factory.py, etc.) does not need to import
directly from .memstack/plugins/feishu/.

TODO: Remove this facade when application services are refactored to use
channel-agnostic abstractions (Phase B).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_FEISHU_PLUGIN_DIR = Path(__file__).resolve().parents[5] / ".memstack" / "plugins" / "feishu"


def _load_feishu_module(module_file: str) -> ModuleType:
    """Load a module from the Feishu plugin directory."""
    file_path = _FEISHU_PLUGIN_DIR / module_file
    module_name = f"feishu_plugin_{file_path.stem}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Feishu plugin module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Re-export commonly used symbols
# Application services import these:
def get_cardkit_streaming_module() -> ModuleType:
    return _load_feishu_module("cardkit_streaming.py")

def get_hitl_cards_module() -> ModuleType:
    return _load_feishu_module("hitl_cards.py")

def get_rich_cards_module() -> ModuleType:
    return _load_feishu_module("rich_cards.py")

def get_media_downloader_module() -> ModuleType:
    return _load_feishu_module("media_downloader.py")

def get_adapter_module() -> ModuleType:
    return _load_feishu_module("adapter.py")

def get_webhook_module() -> ModuleType:
    return _load_feishu_module("webhook.py")
```

**Alternative considered**: Making external consumers import directly from `.memstack/plugins/feishu/` using `importlib`. Rejected because it spreads `importlib` boilerplate across many files. The facade centralizes it.

**Alternative considered**: Adding `.memstack/plugins/feishu/` to `sys.path`. Rejected because it pollutes the module namespace and can cause naming collisions.

### 3.4 Application Service Updates

The external consumers currently use **lazy imports** (inside function bodies) for Feishu code. This is good — it means the imports only execute when Feishu is actually in use. After migration, these lazy imports change to facade calls:

```python
# BEFORE (in event_bridge.py):
from src.infrastructure.adapters.secondary.channels.feishu.cardkit_streaming import (
    CardKitStreamingManager,
)

# AFTER:
from src.infrastructure.adapters.secondary.channels.feishu_facade import (
    get_cardkit_streaming_module,
)
# ... inside the function body:
cardkit_mod = get_cardkit_streaming_module()
CardKitStreamingManager = cardkit_mod.CardKitStreamingManager
```

Since these are already lazy (inside function bodies), the behavioral change is minimal.

### 3.5 Test Migration

Tests at `src/tests/unit/infrastructure/adapters/secondary/channels/feishu/` should **move** to `src/tests/unit/plugins/feishu/` (new directory) and update their imports to use the facade or load directly from the plugin directory.

### 3.6 `lark_oapi` Dependency

The `lark_oapi` (Feishu SDK) dependency is declared in the project's `pyproject.toml`. After migration, it should also be listed in `memstack.plugin.json` under `dependencies.python` so that the plugin is self-documenting:

```json
{
  "dependencies": {
    "python": ["lark_oapi>=1.0.0"]
  }
}
```

The actual installation continues to come from `pyproject.toml` for the local development case. The manifest declaration is for documentation and future `plugin install` automation.

---

## 4. Step-by-Step Migration

### Step 1: Create Plugin Manifest

Create `.memstack/plugins/feishu/memstack.plugin.json`:

```json
{
  "id": "feishu-channel-plugin",
  "kind": "channel",
  "name": "Feishu Channel Plugin",
  "description": "Full Feishu (Lark) integration: messaging, documents, wiki, drive, bitable, cards, webhooks, and streaming.",
  "version": "1.0.0",
  "channels": ["feishu"],
  "providers": [],
  "skills": [],
  "dependencies": {
    "python": ["lark_oapi>=1.0.0"]
  }
}
```

### Step 2: Create `__init__.py`

Create `.memstack/plugins/feishu/__init__.py` (empty package marker):

```python
"""Feishu channel plugin for MemStack."""
```

### Step 3: Add `_load_sibling` Infrastructure

Add the sibling module loader to the top of `plugin.py`. This is the same pattern used by `pdf-assistant` and `example-showcase`.

### Step 4: Move Implementation Files

Copy all 14 implementation files (everything except `__init__.py` and `plugin.py`) from `src/infrastructure/adapters/secondary/channels/feishu/` to `.memstack/plugins/feishu/`:

```
adapter.py
bitable.py
cardkit_streaming.py
cards.py
client.py
docx.py
drive.py
hitl_cards.py
media.py
media_downloader.py
rich_cards.py
webhook.py
wiki.py
```

**Note**: The old `__init__.py` (with `__all__` exports) is NOT copied. Its purpose was package re-exports which are no longer needed in the plugin model.

### Step 5: Rewrite Intra-Module Imports

In each moved file, replace absolute intra-Feishu imports with `_load_sibling()` calls:

```python
# BEFORE (in client.py):
from src.infrastructure.adapters.secondary.channels.feishu.media import FeishuMediaManager

# AFTER (in client.py):
# At module level:
import importlib.util
from pathlib import Path
from types import ModuleType

_PLUGIN_DIR = Path(__file__).resolve().parent

def _load_sibling(module_file: str) -> ModuleType:
    file_path = _PLUGIN_DIR / module_file
    module_name = f"feishu_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Lazy property usage (already existing pattern):
@property
def media(self) -> "FeishuMediaManager":
    if self._media is None:
        _media_mod = _load_sibling("media.py")
        self._media = _media_mod.FeishuMediaManager(self)
    return self._media
```

**Important**: For files with circular dependency risk (client <-> media/docx/wiki/drive/bitable), the `_load_sibling()` calls MUST remain inside lazy properties or function bodies — never at module level. This matches the existing pattern.

For files WITHOUT circular dependency risk (e.g., `cards.py` which imports nothing from Feishu), no `_load_sibling()` is needed — they only import from `src/` domain types or stdlib.

**File-by-file import rewrite summary**:

| File | Intra-Feishu Imports | Rewrite Strategy |
|------|---------------------|-----------------|
| `plugin.py` | `adapter.py` | `_load_sibling("adapter.py")` in factory |
| `adapter.py` | `hitl_cards.py`, `webhook.py` | Already lazy (inside functions). Change to `_load_sibling()` |
| `client.py` | `media.py`, `docx.py`, `wiki.py`, `drive.py`, `bitable.py`, `cards.py` | Already lazy (`@property`). Change to `_load_sibling()` |
| `cardkit_streaming.py` | `adapter.py` | Already lazy (inside function). Change to `_load_sibling()` |
| `media.py` | `client.py` | TYPE_CHECKING import only. No runtime change needed |
| `docx.py` | `client.py` | TYPE_CHECKING import only. No runtime change needed |
| `wiki.py` | `client.py` | TYPE_CHECKING import only. No runtime change needed |
| `drive.py` | `client.py` | TYPE_CHECKING import only. No runtime change needed |
| `bitable.py` | `client.py` | TYPE_CHECKING import only. No runtime change needed |
| `cards.py` | (none) | No changes needed |
| `rich_cards.py` | (none) | No changes needed |
| `hitl_cards.py` | (none) | No changes needed |
| `media_downloader.py` | (none) | No changes needed |
| `webhook.py` | (none) | No changes needed |

### Step 6: Rewrite `plugin.py`

Replace the 8-line shim with a full plugin entry point:

```python
"""Feishu channel plugin for MemStack.

Provides full Feishu (Lark) integration: messaging, documents, wiki,
drive, bitable, interactive cards, webhooks, and CardKit streaming.

Usage:
    plugin_manager(action="enable", plugin_name="feishu-channel-plugin")
    plugin_manager(action="reload")
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from src.infrastructure.agent.plugins.registry import ChannelAdapterBuildContext
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

_PLUGIN_DIR = Path(__file__).resolve().parent


def _load_sibling(module_file: str) -> ModuleType:
    """Load a Python module from the same directory as this plugin file."""
    file_path = _PLUGIN_DIR / module_file
    module_name = f"feishu_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FeishuChannelPlugin:
    """Plugin that contributes Feishu channel adapter factory."""

    name = "feishu-channel-plugin"

    def setup(self, api: PluginRuntimeApi) -> None:
        """Register Feishu adapter factory under channel_type=feishu."""

        def _factory(context: ChannelAdapterBuildContext):
            _adapter_mod = _load_sibling("adapter.py")
            return _adapter_mod.FeishuAdapter(context.channel_config)

        api.register_channel_type(
            "feishu",
            _factory,
            config_schema={
                "type": "object",
                "properties": {
                    "app_id": {"type": "string", "title": "App ID", "minLength": 1},
                    "app_secret": {"type": "string", "title": "App Secret", "minLength": 1},
                    "encrypt_key": {"type": "string", "title": "Encrypt Key"},
                    "verification_token": {"type": "string", "title": "Verification Token"},
                    "domain": {"type": "string", "title": "Domain", "default": "feishu"},
                    "connection_mode": {
                        "type": "string",
                        "title": "Connection Mode",
                        "enum": ["websocket", "webhook"],
                        "default": "websocket",
                    },
                    "webhook_url": {"type": "string", "title": "Webhook URL"},
                    "webhook_port": {
                        "type": "integer",
                        "title": "Webhook Port",
                        "minimum": 1,
                        "maximum": 65535,
                    },
                    "webhook_path": {"type": "string", "title": "Webhook Path"},
                },
                "required": ["app_id", "app_secret"],
                "additionalProperties": False,
            },
            config_ui_hints={
                "app_secret": {"sensitive": True},
                "encrypt_key": {"sensitive": True, "advanced": True},
                "verification_token": {"sensitive": True, "advanced": True},
                "webhook_port": {"advanced": True},
                "webhook_path": {"advanced": True},
            },
            defaults={
                "domain": "feishu",
                "connection_mode": "websocket",
                "webhook_path": "/api/v1/channels/events/feishu",
                "webhook_port": 8000,
            },
            secret_paths=["app_secret", "encrypt_key", "verification_token"],
        )


# Discovery loader resolves `plugin` attribute at module level.
plugin = FeishuChannelPlugin()
```

### Step 7: Create Facade Module

Create `src/infrastructure/adapters/secondary/channels/feishu_facade.py` as described in Section 3.3. This is the transitional bridge for application-layer code.

### Step 8: Update External Consumers

Update each external consumer to use the facade:

**`src/application/services/channels/event_bridge.py`** (7 import sites):
- Replace `from src.infrastructure.adapters.secondary.channels.feishu.X import Y` with facade calls.
- Since all current imports are lazy (inside function bodies), wrap them with `get_X_module()` calls.

**`src/application/services/channels/channel_service_factory.py`**:
- Replace `from ...feishu.media_downloader import ...` with `get_media_downloader_module()`.

**`src/application/services/channels/media_import_service.py`**:
- Same as above.

**`src/application/services/channels/channel_message_router.py`**:
- Replace `from ...feishu.cardkit_streaming import ...` with `get_cardkit_streaming_module()`.

**`src/infrastructure/adapters/primary/web/routers/channels.py`**:
- Replace direct Feishu imports with facade calls.

### Step 9: Update Example Scripts

**`src/channels_example.py`** and **`src/channels_enhanced_example.py`**:
- Update imports to use facade. These are standalone example scripts, so alternatively they can be moved to `examples/` or updated with inline `importlib` loading.

### Step 10: Update Package Template

**`examples/plugins/memstack-plugin-feishu/src/memstack_plugin_feishu/plugin.py`**:
- This is an example of how to package the Feishu plugin as a pip-installable package. It should import from the new plugin location or be rewritten to be self-contained.

### Step 11: Move Tests

Move `src/tests/unit/infrastructure/adapters/secondary/channels/feishu/` to `src/tests/unit/plugins/feishu/`.

Update all imports in the moved test files:
- Replace `from src.infrastructure.adapters.secondary.channels.feishu.X import Y` with either:
  - Facade calls, or
  - Direct `importlib` loading from `.memstack/plugins/feishu/`

### Step 12: Delete Old Code

Delete `src/infrastructure/adapters/secondary/channels/feishu/` entirely (all 16 files + `__pycache__/`).

### Step 13: Update README and Documentation

- Update `src/infrastructure/adapters/secondary/channels/README.md` to reflect the migration.
- Update `AGENTS.md` (the `Architecture Overview` section still references the old path).
- Create `.memstack/plugins/feishu/README.md` with plugin documentation (can be adapted from the existing channels README).

### Step 14: Verify

1. `make lint` -- all linting passes
2. `make test-unit` -- all unit tests pass
3. `make test-integration` -- integration tests pass
4. Manual verification:
   - `plugin_manager(action="list")` shows `feishu-channel-plugin`
   - `plugin_manager(action="enable", plugin_name="feishu-channel-plugin")` succeeds
   - `plugin_manager(action="reload")` loads the plugin
   - Feishu channel creation and connection work end-to-end
5. `grep -r "from src.infrastructure.adapters.secondary.channels.feishu" src/` returns ZERO results (only the facade file may reference the old path in comments).

---

## 5. Risk Assessment

### 5.1 High Risk: Circular Import Breakage

**Risk**: `_load_sibling()` at module level could trigger circular imports between `client.py` and its sub-clients.

**Mitigation**: The existing code already uses lazy imports (inside `@property` methods and function bodies). The migration preserves this pattern. All `_load_sibling()` calls for circular-risk modules MUST remain inside lazy accessors.

**Verification**: Import `plugin.py` in an isolated Python process and confirm no `ImportError` or stack overflow.

### 5.2 Medium Risk: Facade Performance

**Risk**: Each `get_X_module()` call does a dynamic module load.

**Mitigation**: Python's `sys.modules` cache ensures each module is loaded only once. The facade uses `sys.modules` check before loading. Performance impact is negligible (one-time ~1ms per module).

### 5.3 Medium Risk: Type Checking

**Risk**: `_load_sibling()` returns `ModuleType`, losing type information. Pyright/mypy cannot infer attribute types.

**Mitigation**:
- Add `TYPE_CHECKING` blocks with explicit type imports for static analysis.
- Use `# type: ignore[attr-defined]` sparingly where needed.
- Long-term: Phase B refactoring introduces proper abstractions that restore full type safety.

### 5.4 Low Risk: `sys.modules` Namespace Collision

**Risk**: `_load_sibling()` registers modules as `feishu_{stem}` (e.g., `feishu_adapter`). Could collide if another plugin uses the same naming.

**Mitigation**: The `feishu_` prefix is sufficiently unique. If needed, use `feishu_channel_{stem}` for extra safety.

### 5.5 Low Risk: Plugin State Store

**Risk**: The plugin name changes from what's currently in `state.json`.

**Mitigation**: The current shim uses `name = "feishu-channel-plugin"` which matches the new plugin.py. No state store migration needed.

---

## 6. Rollback Strategy

Each step is designed to be independently reversible:

1. **Steps 1-6** (new files): Delete new files, restore shim `plugin.py`.
2. **Step 7** (facade): Delete `feishu_facade.py`.
3. **Steps 8-10** (consumer updates): Revert import changes via `git checkout`.
4. **Step 11** (test move): Move tests back.
5. **Step 12** (deletion): Restore from git (`git checkout -- src/infrastructure/adapters/secondary/channels/feishu/`).

**Recommended**: Create a feature branch (`feat/feishu-plugin-migration`) and merge via PR after all verification passes.

---

## 7. Future Work (Phase B)

After this migration completes, the following improvements become possible:

1. **Channel-agnostic abstractions**: Refactor `event_bridge.py`, `channel_message_router.py`, and `channel_service_factory.py` to use abstract interfaces instead of importing Feishu-specific card builders. This eliminates the facade entirely.

2. **Plugin-provided card builders**: The Feishu plugin could register its card builders as plugin services via `api.register_service()`, making them discoverable without direct imports.

3. **Plugin-scoped tests**: Move plugin tests into `.memstack/plugins/feishu/tests/` co-located with the plugin code, following the self-contained plugin principle.

4. **Hot-reloadable channel plugins**: With all code in `.memstack/plugins/feishu/`, the plugin can be reloaded at runtime without restarting the API server.

---

## 8. Implementation Checklist

- [ ] Create `memstack.plugin.json` manifest
- [ ] Create `__init__.py` package marker
- [ ] Copy 13 implementation files to `.memstack/plugins/feishu/`
- [ ] Rewrite `plugin.py` with full plugin entry point
- [ ] Add `_load_sibling()` infrastructure to files that need it
- [ ] Rewrite intra-module imports (absolute -> `_load_sibling()`)
- [ ] Verify no circular import issues (standalone import test)
- [ ] Create `feishu_facade.py` transitional bridge
- [ ] Update `event_bridge.py` imports (7 sites)
- [ ] Update `channel_service_factory.py` imports
- [ ] Update `media_import_service.py` imports
- [ ] Update `channel_message_router.py` imports
- [ ] Update `channels.py` router imports
- [ ] Update example scripts
- [ ] Update package template
- [ ] Move tests to `src/tests/unit/plugins/feishu/`
- [ ] Update test imports
- [ ] Delete `src/infrastructure/adapters/secondary/channels/feishu/`
- [ ] Update `README.md` and `AGENTS.md`
- [ ] Create `.memstack/plugins/feishu/README.md`
- [ ] Run `make lint` -- passes
- [ ] Run `make test` -- passes
- [ ] Manual end-to-end Feishu channel test
- [ ] Verify `grep` returns zero old-path imports in `src/`
