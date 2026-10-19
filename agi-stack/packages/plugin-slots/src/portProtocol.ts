import { decodeSlotActionV2, type SlotActionV2 } from './ownerContext';

export const SLOT_PORT_MESSAGE_SOURCE_V2 = 'memstack-plugin-slot-v2' as const;

export interface SlotBridgeIdentityV2 {
  readonly slotId: string;
  readonly instanceNonce: string;
  readonly generationId: string;
}

export type SlotPortPayloadV2 =
  | { readonly type: 'slot:ready' }
  | { readonly type: 'slot:connect' }
  | { readonly type: 'slot:init'; readonly payload: unknown }
  | { readonly type: 'slot:dispose' }
  | { readonly type: 'slot:resize'; readonly height: number }
  | { readonly type: 'slot:action'; readonly action: SlotActionV2 }
  | { readonly type: 'slot:error'; readonly message: string };

export type SlotPortMessageV2 = SlotBridgeIdentityV2 &
  SlotPortPayloadV2 & {
    readonly source: typeof SLOT_PORT_MESSAGE_SOURCE_V2;
  };

export function encodeSlotPortMessageV2(
  identity: SlotBridgeIdentityV2,
  payload: SlotPortPayloadV2,
): SlotPortMessageV2 {
  return { source: SLOT_PORT_MESSAGE_SOURCE_V2, ...identity, ...payload };
}

export function matchesSlotBridgeIdentityV2(
  value: SlotBridgeIdentityV2,
  expected: SlotBridgeIdentityV2,
): boolean {
  return (
    value.slotId === expected.slotId &&
    value.instanceNonce === expected.instanceNonce &&
    value.generationId === expected.generationId
  );
}

/** Validate every message received at the iframe/MessagePort trust boundary. */
export function decodeSlotPortMessageV2(
  value: unknown,
): SlotPortMessageV2 | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    return null;
  const row = value as Record<string, unknown>;
  if (
    row.source !== SLOT_PORT_MESSAGE_SOURCE_V2 ||
    typeof row.slotId !== 'string' ||
    !row.slotId ||
    typeof row.instanceNonce !== 'string' ||
    !row.instanceNonce ||
    typeof row.generationId !== 'string' ||
    !row.generationId
  )
    return null;
  const identity = {
    slotId: row.slotId,
    instanceNonce: row.instanceNonce,
    generationId: row.generationId,
  };
  switch (row.type) {
    case 'slot:ready':
    case 'slot:connect':
    case 'slot:dispose':
      return encodeSlotPortMessageV2(identity, { type: row.type });
    case 'slot:init':
      return encodeSlotPortMessageV2(identity, {
        type: row.type,
        payload: row.payload,
      });
    case 'slot:resize':
      return typeof row.height === 'number' &&
        Number.isFinite(row.height) &&
        row.height > 0
        ? encodeSlotPortMessageV2(identity, {
            type: row.type,
            height: row.height,
          })
        : null;
    case 'slot:action': {
      const action = decodeSlotActionV2(row.action);
      return action
        ? encodeSlotPortMessageV2(identity, { type: row.type, action })
        : null;
    }
    case 'slot:error':
      return typeof row.message === 'string'
        ? encodeSlotPortMessageV2(identity, {
            type: row.type,
            message: row.message,
          })
        : null;
    default:
      return null;
  }
}
