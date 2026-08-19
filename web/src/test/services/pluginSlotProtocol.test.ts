import { describe, expect, it } from 'vitest';

import {
  decodeSlotMessage,
  encodeSlotMessage,
  isGuestMessageForSlot,
  SLOT_MESSAGE_SOURCE,
} from '@/services/pluginSlotProtocol';

describe('pluginSlotProtocol', () => {
  it('round-trips an encoded message', () => {
    const encoded = encodeSlotMessage({ type: 'slot:ready', slotId: 'card' });
    expect(encoded.source).toBe(SLOT_MESSAGE_SOURCE);
    expect(decodeSlotMessage(encoded)).toEqual({ type: 'slot:ready', slotId: 'card' });
  });

  it('rejects foreign sources and malformed payloads', () => {
    expect(decodeSlotMessage(null)).toBeNull();
    expect(decodeSlotMessage('string')).toBeNull();
    expect(decodeSlotMessage({ source: 'other', message: { type: 'slot:ready' } })).toBeNull();
    expect(decodeSlotMessage({ source: SLOT_MESSAGE_SOURCE })).toBeNull();
    expect(decodeSlotMessage({ source: SLOT_MESSAGE_SOURCE, message: {} })).toBeNull();
  });

  it('scopes guest messages to their slot id', () => {
    const ready = { type: 'slot:ready', slotId: 'a' } as const;
    expect(isGuestMessageForSlot(ready, 'a')).toBe(true);
    expect(isGuestMessageForSlot(ready, 'b')).toBe(false);
    expect(isGuestMessageForSlot({ type: 'slot:init', slotId: 'a' }, 'a')).toBe(false);
  });
});
