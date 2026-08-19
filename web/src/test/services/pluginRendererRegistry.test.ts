import { beforeEach, describe, expect, it } from 'vitest';

import {
  getBuiltinRenderer,
  registerBuiltinRenderer,
  rendererKeys,
  resetBuiltinRenderersForTests,
} from '@/services/pluginRendererRegistry';

const slot = { id: 'card', pluginId: 'acme', contract: 'tool-result:card' };

describe('pluginRendererRegistry', () => {
  beforeEach(() => resetBuiltinRenderersForTests());

  it('resolves by contract id first, then plugin/slot key', () => {
    expect(rendererKeys(slot)).toEqual(['tool-result:card', 'acme/card']);
    expect(rendererKeys({ ...slot, contract: '' })).toEqual(['acme/card']);
  });

  it('registers, resolves, and disposes renderers', () => {
    const A = () => null;
    const B = () => null;
    const disposeA = registerBuiltinRenderer('tool-result:card', A);
    registerBuiltinRenderer('acme/card', B);

    expect(getBuiltinRenderer(slot)).toBe(A);
    disposeA();
    expect(getBuiltinRenderer(slot)).toBe(B);
  });

  it('returns undefined for unknown slots', () => {
    expect(getBuiltinRenderer({ id: 'x', pluginId: 'y', contract: '' })).toBeUndefined();
  });
});
