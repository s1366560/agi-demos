import { describe, expect, it } from 'vitest';
import {
  decodeSlotPortMessageV2,
  encodeSlotPortMessageV2,
  matchesSlotBridgeIdentityV2,
} from '@agistack/plugin-slots';
const identity = { slotId: 'composer', generationId: 'scope-a:1', instanceNonce: 'unique-frame' };
describe('isolated slot port boundary', () => {
  it('decodes only structured owner actions and binds all identity fields', () => {
    const payload = encodeSlotPortMessageV2(identity, {
      type: 'slot:action',
      action: { type: 'composer.insert-text', text: 'Hello', draftRevision: 'draft-7' },
    });
    expect(decodeSlotPortMessageV2(payload)).toEqual(payload);
    for (const key of ['slotId', 'generationId', 'instanceNonce'] as const)
      expect(matchesSlotBridgeIdentityV2({ ...identity, [key]: 'different' }, identity)).toBe(
        false
      );
    expect(
      decodeSlotPortMessageV2({ ...payload, action: { type: 'eval', code: 'unsafe' } })
    ).toBeNull();
    expect(
      decodeSlotPortMessageV2({
        ...payload,
        action: { type: 'composer.insert-text', text: 'Hello' },
      })
    ).toBeNull();
  });
  it.each([
    null,
    [],
    {},
    { ...identity, source: 'other', type: 'slot:ready' },
    { ...encodeSlotPortMessageV2(identity, { type: 'slot:ready' }), instanceNonce: '' },
    encodeSlotPortMessageV2(identity, { type: 'slot:resize', height: Number.NaN }),
  ])('rejects malformed input %#', (value) => expect(decodeSlotPortMessageV2(value)).toBeNull());
});
