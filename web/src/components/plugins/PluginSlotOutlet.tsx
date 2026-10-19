import { createElement } from 'react';

import { useWebUiSlotAuthorityV2, useWebUiSlotsV2 } from '@/routes/v2/webUiSlotAuthorityStateV2';

import { PluginSlotHost } from './PluginSlotHost';

import type { UiSlotKind } from '@/types/pluginSlots';

import type { SlotActionV2, SlotContextV2 } from '@agistack/plugin-slots';

export interface PluginSlotOutletProps<K extends UiSlotKind = UiSlotKind> {
  readonly kind: K;
  readonly context?: SlotContextV2<K>;
  readonly contractId?: string;
  readonly onAction?: (action: SlotActionV2) => void;
  readonly onError?: (message: string) => void;
}

export function PluginSlotOutlet<K extends UiSlotKind>({
  kind,
  context,
  contractId,
  onAction,
  onError,
}: PluginSlotOutletProps<K>) {
  const authority = useWebUiSlotAuthorityV2();
  const visible = useWebUiSlotsV2(kind, contractId);
  return (
    <>
      {visible.map((slot) => {
        const renderer = authority.renderers?.resolve(slot);
        const key = `${authority.generationId ?? 'standalone'}/${slot.pluginId}/${slot.id}`;
        const action = (value: SlotActionV2) => {
          if (authority.isActive?.() !== false) onAction?.(value);
        };
        if (renderer) return createElement(renderer, { key, slot, context, onAction: action });
        return (
          <PluginSlotHost
            key={key}
            slot={slot}
            generationId={authority.generationId}
            initPayload={context}
            onAction={action}
            onError={onError}
          />
        );
      })}
    </>
  );
}
