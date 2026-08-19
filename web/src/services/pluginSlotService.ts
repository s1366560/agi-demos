/**
 * Plugin slot registry fed by the platform plugin snapshot (P3).
 *
 * The service fetches the canonical snapshot, extracts `ui_slot` and
 * `ui_renderer` capabilities into slot definitions, and enforces the
 * backend safety contract client-side: sandboxed renderers only, builtin
 * module references only, and `ui.*` permissions only.
 */

import { httpClient } from './client/httpClient';

import type {
  PlatformPluginSnapshotResponse,
  UiSlotDefinition,
  UiSlotKind,
} from '@/types/pluginSlots';

const SNAPSHOT_URL = '/platform-plugins/snapshot';

const SLOT_KINDS: ReadonlySet<string> = new Set([
  'nav_item',
  'settings_page',
  'conversation_renderer',
  'tool_result_renderer',
  'composer_action',
  'mcp_canvas',
]);

export class PluginSlotError extends Error {}

type Listener = (slots: UiSlotDefinition[]) => void;

const listeners = new Set<Listener>();
let cachedSlots: UiSlotDefinition[] = [];

export function getPluginSlots(): UiSlotDefinition[] {
  return cachedSlots;
}

export function subscribePluginSlots(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export async function refreshPluginSlots(): Promise<UiSlotDefinition[]> {
  const snapshot = await httpClient.get<PlatformPluginSnapshotResponse>(SNAPSHOT_URL);
  cachedSlots = extractSlotDefinitions(snapshot);
  listeners.forEach((listener) => {
    listener(cachedSlots);
  });
  return cachedSlots;
}

export function extractSlotDefinitions(
  snapshot: PlatformPluginSnapshotResponse
): UiSlotDefinition[] {
  const definitions: UiSlotDefinition[] = [];
  for (const row of snapshot.payload.plugins) {
    for (const capability of row.provides) {
      if (capability.kind !== 'ui_slot' && capability.kind !== 'ui_renderer') continue;
      definitions.push(toSlotDefinition(row.id, capability.kind, capability));
    }
  }
  return definitions;
}

function toSlotDefinition(
  pluginId: string,
  kind: string,
  capability: {
    id: string;
    config_schema?: Record<string, unknown>;
    permissions?: string[] | undefined;
  }
): UiSlotDefinition {
  const schema = capability.config_schema ?? {};
  const slot =
    typeof schema.slot === 'string'
      ? schema.slot
      : kind === 'ui_slot'
        ? ''
        : 'conversation_renderer';
  if (!SLOT_KINDS.has(slot)) {
    throw new PluginSlotError(`plugin ${pluginId} declares unknown slot kind: ${slot}`);
  }
  const moduleRef = typeof schema.module_ref === 'string' ? schema.module_ref : '';
  if (!moduleRef.startsWith('builtin:')) {
    throw new PluginSlotError(
      `plugin ${pluginId} slot ${capability.id} uses a non-builtin module_ref`
    );
  }
  const permission =
    typeof schema.permission === 'string' ? schema.permission : (capability.permissions?.[0] ?? '');
  if (!permission.startsWith('ui.')) {
    throw new PluginSlotError(
      `plugin ${pluginId} slot ${capability.id} permission must start with ui.`
    );
  }
  const sandbox = schema.sandbox !== false;
  if (!sandbox) {
    throw new PluginSlotError(`plugin ${pluginId} slot ${capability.id} must run in a sandbox`);
  }
  return {
    pluginId,
    slot: slot as UiSlotKind,
    id: capability.id,
    moduleRef,
    permission,
    sandbox,
  };
}

/** Test hook: reset the module-level cache. */
export function resetPluginSlotsForTests(): void {
  cachedSlots = [];
  listeners.clear();
}
