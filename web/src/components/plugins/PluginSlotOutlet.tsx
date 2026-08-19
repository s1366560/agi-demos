/**
 * Slot outlet (I3): renders all plugin slots of one kind at a mount point.
 *
 * Keyed builtin renderers render directly; every other slot renders through
 * the sandboxed PluginSlotHost iframe. When no slot of the kind exists the
 * outlet renders nothing, so mount points are zero-cost by default.
 */

import { createElement, useEffect, useState } from 'react';

import { getBuiltinRenderer } from '@/services/pluginRendererRegistry';
import {
  getPluginSlots,
  refreshPluginSlots,
  subscribePluginSlots,
} from '@/services/pluginSlotService';

import { PluginSlotHost } from './PluginSlotHost';

import type { UiSlotDefinition, UiSlotKind } from '@/types/pluginSlots';

export interface PluginSlotOutletProps {
  kind: UiSlotKind;
  /** Optional payload forwarded to the slot (init payload / renderer context). */
  context?: unknown;
  /** Restrict the outlet to one contract id (e.g. one tool result kind). */
  contractId?: string;
  onAction?: (name: string, data?: unknown) => void;
  onError?: (message: string) => void;
}

export function PluginSlotOutlet({
  kind,
  context,
  contractId,
  onAction,
  onError,
}: PluginSlotOutletProps) {
  const [slots, setSlots] = useState<UiSlotDefinition[]>(() => getPluginSlots());

  useEffect(() => {
    const unsubscribe = subscribePluginSlots(setSlots);
    if (getPluginSlots().length === 0) {
      void refreshPluginSlots().catch(() => undefined);
    }
    return unsubscribe;
  }, []);

  const visible = slots.filter(
    (slot) => slot.slot === kind && (contractId === undefined || slot.contract === contractId)
  );
  if (visible.length === 0) return null;

  return (
    <>
      {visible.map((slot) => {
        const keyed = getBuiltinRenderer(slot);
        if (keyed) {
          return createElement(keyed, {
            key: `${slot.pluginId}/${slot.id}`,
            slot,
            context,
          });
        }
        return (
          <PluginSlotHost
            key={`${slot.pluginId}/${slot.id}`}
            slot={slot}
            initPayload={context}
            {...(onAction ? { onAction } : {})}
            {...(onError ? { onError } : {})}
          />
        );
      })}
    </>
  );
}

export default PluginSlotOutlet;
