/**
 * Tool result renderer hook (I3).
 *
 * A `tool_result_renderer` slot whose contract is `tool-result:<toolName>`
 * (or whose capability id equals the tool name) takes over that tool's
 * result card — keyed builtin renderer directly, anything else sandboxed.
 * Without a matching slot the fallback renders, unchanged.
 */

import { createElement } from 'react';
import type { ReactNode } from 'react';

import { getBuiltinRenderer } from '@/services/pluginRendererRegistry';
import { findToolResultSlot } from '@/services/pluginSlotService';

import { PluginSlotHost } from './PluginSlotHost';

export interface PluginToolResultRendererProps {
  toolName: string;
  result: unknown;
  fallback: ReactNode;
}

export function PluginToolResultRenderer({
  toolName,
  result,
  fallback,
}: PluginToolResultRendererProps) {
  const slot = findToolResultSlot(toolName);
  if (!slot) return <>{fallback}</>;
  const keyed = getBuiltinRenderer(slot);
  if (keyed) return createElement(keyed, { slot, context: { toolName, result } });
  return <PluginSlotHost slot={slot} initPayload={{ toolName, result }} />;
}

export default PluginToolResultRenderer;
