/**
 * postMessage protocol between the host and sandboxed plugin slot iframes (P3).
 *
 * Every frame message is a plain object with `source: 'memstack-plugin-slot'`
 * so host and guest can filter foreign traffic. The host only accepts
 * messages whose `slotId` matches the mounted slot and whose origin was
 * explicitly allowed for that slot.
 */

export const SLOT_MESSAGE_SOURCE = 'memstack-plugin-slot' as const;

export type SlotHostMessage =
  | { type: 'slot:init'; slotId: string; payload?: unknown }
  | { type: 'slot:event'; slotId: string; name: string; data?: unknown }
  | { type: 'slot:dispose'; slotId: string };

export type SlotGuestMessage =
  | { type: 'slot:ready'; slotId: string }
  | { type: 'slot:resize'; slotId: string; height: number }
  | { type: 'slot:action'; slotId: string; name: string; data?: unknown }
  | { type: 'slot:error'; slotId: string; message: string };

interface Envelope {
  source: typeof SLOT_MESSAGE_SOURCE;
  message: SlotHostMessage | SlotGuestMessage;
}

export function encodeSlotMessage(message: SlotHostMessage | SlotGuestMessage): Envelope {
  return { source: SLOT_MESSAGE_SOURCE, message };
}

export function decodeSlotMessage(data: unknown): Envelope['message'] | null {
  if (typeof data !== 'object' || data === null) return null;
  const envelope = data as Partial<Envelope>;
  if (envelope.source !== SLOT_MESSAGE_SOURCE) return null;
  const message: unknown = envelope.message;
  if (typeof message !== 'object' || message === null) return null;
  if (typeof (message as { type?: unknown }).type !== 'string') return null;
  return message as Envelope['message'];
}

export function isGuestMessageForSlot(
  message: SlotHostMessage | SlotGuestMessage,
  slotId: string
): message is SlotGuestMessage {
  return (
    (message.type === 'slot:ready' ||
      message.type === 'slot:resize' ||
      message.type === 'slot:action' ||
      message.type === 'slot:error') &&
    message.slotId === slotId
  );
}
