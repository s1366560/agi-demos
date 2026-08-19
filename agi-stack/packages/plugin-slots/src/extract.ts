/**
 * Snapshot-to-slot extraction and the client-side safety gate (I3).
 *
 * Shared by the web and desktop renderers: extracts `ui_slot` and
 * `ui_renderer` capabilities from the platform plugin snapshot into slot
 * definitions and enforces the contract client-side — sandboxed renderers
 * only, builtin module references only, and `ui.*` permissions only.
 */

import type {
  PlatformPluginSnapshotResponse,
  UiSlotDefinition,
  UiSlotKind,
} from './types';

export class PluginSlotError extends Error {}

export const SLOT_KINDS: ReadonlySet<string> = new Set([
  'nav_item',
  'settings_page',
  'conversation_renderer',
  'tool_result_renderer',
  'composer_action',
  'mcp_canvas',
]);

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
    contract?: string;
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
    contract: capability.contract ?? '',
    moduleRef,
    permission,
    sandbox,
  };
}
