/**
 * Keyed builtin renderer registry (I3).
 *
 * Builtin (trusted) renderers register a React component under the slot's
 * contract id (e.g. `tool-result:memory_search`) or under the slot's
 * `pluginId/slotId` key. Slots without a keyed renderer fall back to the
 * sandboxed PluginSlotHost iframe. External modules never register here —
 * the extraction gate keeps them sandboxed by construction.
 */

import type { ComponentType } from 'react';

import type { UiSlotDefinition } from '@/types/pluginSlots';

export interface PluginRendererProps {
  slot: UiSlotDefinition;
  context?: unknown;
}

export type PluginRendererComponent = ComponentType<PluginRendererProps>;

const renderers = new Map<string, PluginRendererComponent>();

/** Registry key candidates for one slot, most specific first. */
export function rendererKeys(slot: Pick<UiSlotDefinition, 'id' | 'pluginId' | 'contract'>): string[] {
  const keys: string[] = [];
  if (slot.contract) keys.push(slot.contract);
  keys.push(`${slot.pluginId}/${slot.id}`);
  return keys;
}

export function registerBuiltinRenderer(
  key: string,
  component: PluginRendererComponent
): () => void {
  renderers.set(key, component);
  return () => {
    if (renderers.get(key) === component) renderers.delete(key);
  };
}

export function getBuiltinRenderer(
  slot: Pick<UiSlotDefinition, 'id' | 'pluginId' | 'contract'>
): PluginRendererComponent | undefined {
  for (const key of rendererKeys(slot)) {
    const component = renderers.get(key);
    if (component) return component;
  }
  return undefined;
}

/** Test hook: clear all registered renderers. */
export function resetBuiltinRenderersForTests(): void {
  renderers.clear();
}
