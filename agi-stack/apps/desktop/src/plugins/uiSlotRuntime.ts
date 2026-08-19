import {
  UiSlotDefinition,
  UiSlotRegistry,
} from './uiSlotRegistry';

export { UiSlotRegistry };
export type { UiSlotDefinition } from './uiSlotRegistry';

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

const UI_SLOT_KINDS = new Set([
  'nav_item',
  'settings_page',
  'conversation_renderer',
  'tool_result_renderer',
  'composer_action',
  'mcp_canvas',
]);

export function frontendSlotDefinitions(
  snapshot: {
    readonly plugins: readonly PlatformPluginSnapshotRow[];
  },
): UiSlotDefinition[] {
  const definitions: UiSlotDefinition[] = [];
  for (const plugin of snapshot.plugins) {
    if (plugin.runtime !== 'frontend' || plugin.trust !== 'signed') continue;
    const artifactDigest = (plugin.config.artifact as
      | { layer_sha256?: unknown }
      | undefined)?.layer_sha256;
    if (typeof artifactDigest !== 'string' || artifactDigest.length !== 64) continue;
    for (const capability of plugin.provides) {
      if (capability.kind !== 'ui_slot' && capability.kind !== 'ui_renderer') continue;
      const slot = UI_SLOT_KINDS.has(capability.id)
        ? (capability.id as UiSlotDefinition['slot'])
        : 'tool_result_renderer';
      definitions.push({
        pluginId: plugin.id,
        slot,
        id: capability.id,
        contract: capability.contract,
        moduleRef: `signed:${artifactDigest}`,
        permission: capability.permissions[0] ?? 'ui.render',
        sandbox: true,
      });
    }
  }
  return definitions;
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
      const trust = definition.moduleRef.startsWith('builtin:')
        ? 'builtin'
        : definition.moduleRef.startsWith('signed:')
          ? 'signed'
          : null;
      if (trust === null) continue;
      this.disposers.set(
        key,
        this.registry.register(definition, {
          trust,
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
