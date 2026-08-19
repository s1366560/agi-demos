/**
 * Plugin slot registry fed by the platform plugin snapshot (P3/I3).
 *
 * The service fetches the canonical snapshot, extracts `ui_slot` and
 * `ui_renderer` capabilities into slot definitions via the shared
 * `@agistack/plugin-slots` extraction gate (builtin modules, sandboxed
 * renderers, `ui.*` permissions), and caches them for slot outlets.
 */

import { extractSlotDefinitions, PluginSlotError } from '@agistack/plugin-slots';

import { httpClient } from './client/httpClient';

import type {
  PlatformPluginSnapshotResponse,
  UiSlotDefinition,
} from '@/types/pluginSlots';

const SNAPSHOT_URL = '/platform-plugins/snapshot';

export { extractSlotDefinitions, PluginSlotError };

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

/** Test hook: reset the module-level cache. */
export function resetPluginSlotsForTests(): void {
  cachedSlots = [];
  listeners.clear();
}
