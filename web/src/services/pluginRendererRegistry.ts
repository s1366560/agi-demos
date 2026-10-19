import { createElement, type ComponentType } from 'react';

import { ToolResultDisplay } from '../components/agent/chat/ToolResultDisplay';

import type { UiSlotDefinition } from '@/types/pluginSlots';

import type { SlotActionV2, SlotContextV2 } from '@agistack/plugin-slots';

export interface PluginRendererProps {
  readonly slot: UiSlotDefinition;
  readonly context?: SlotContextV2 | undefined;
  readonly onAction?: (action: SlotActionV2) => void;
}

export type PluginRendererComponent = ComponentType<PluginRendererProps>;
export interface PluginRendererRegistryV2 {
  readonly resolve: (slot: UiSlotDefinition) => PluginRendererComponent | undefined;
}

const ToolResultRenderer: PluginRendererComponent = ({ context }) => {
  if (!context || !('kind' in context) || context.kind !== 'tool-result') return null;
  const { presentation } = context;
  if (presentation.kind !== 'text') return null;
  return createElement(ToolResultDisplay, {
    result: presentation.text,
    isError: context.status === 'failed',
  });
};

/** Compiled modules are immutable; each generation gets its own exact owner projection. */
export function createPluginRendererRegistryV2(
  definitions: readonly UiSlotDefinition[],
  isActive: () => boolean
): PluginRendererRegistryV2 {
  const owned = new Map(definitions.map((slot) => [`${slot.pluginId}/${slot.id}`, slot]));
  return Object.freeze({
    resolve(slot: UiSlotDefinition): PluginRendererComponent | undefined {
      if (!isActive() || owned.get(`${slot.pluginId}/${slot.id}`) !== slot) return undefined;
      return slot.moduleRef === 'builtin:web-slot-tool-result' ? ToolResultRenderer : undefined;
    },
  });
}
