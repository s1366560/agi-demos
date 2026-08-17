import {
  UiSlotDefinition,
  UiSlotRegistry,
} from './uiSlotRegistry';

export interface PlatformPluginSnapshotCapability {
  readonly kind: string;
  readonly id: string;
  readonly contract: string;
  readonly permissions: readonly string[];
}

export interface PlatformPluginSnapshotRow {
  readonly schema_version: number;
  readonly id: string;
  readonly version: string;
  readonly runtime: string;
  readonly trust: string;
  readonly provides: readonly PlatformPluginSnapshotCapability[];
  readonly config: Record<string, unknown>;
}

export interface UiSlotRuntimeState {
  readonly slots: readonly ReturnType<UiSlotRegistry['list']>[number][];
}

export class UiSlotRuntime {
  private readonly disposers = new Map<string, () => void>();

  constructor(private readonly registry: UiSlotRegistry = new UiSlotRegistry()) {}

  reconcile(
    snapshot: {
      readonly plugins: readonly PlatformPluginSnapshotRow[];
    },
    definitions: readonly UiSlotDefinition[],
  ): UiSlotRuntimeState {
    const activePlugins = new Set(
      snapshot.plugins
        .filter((plugin) => plugin.runtime === 'frontend')
        .map((plugin) => plugin.id),
    );
    const desired = new Set(
      definitions.filter((definition) => activePlugins.has(definition.pluginId)),
    );

    for (const definition of definitions) {
      const key = `${definition.pluginId}:${definition.slot}:${definition.id}`;
      if (!desired.has(definition)) {
        this.disposers.get(key)?.();
        this.disposers.delete(key);
        continue;
      }
      if (this.disposers.has(key)) continue;
      this.disposers.set(
        key,
        this.registry.register(definition, {
          trust: 'builtin',
          runtime: 'frontend',
        }),
      );
    }

    return { slots: this.registry.list() };
  }

  dispose(): void {
    for (const dispose of this.disposers.values()) dispose();
    this.disposers.clear();
  }
}
