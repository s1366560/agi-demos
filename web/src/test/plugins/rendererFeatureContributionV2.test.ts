import { describe, expect, it } from 'vitest';

import { RendererContributionRegistryV2 } from '@agistack/plugin-runtime';

describe('atomic renderer feature contributions', () => {
  it('revokes a feature route, navigation and commands together without affecting another feature', () => {
    const registry = new RendererContributionRegistryV2('web');
    registry.register('other', { id: 'other', kind: 'route', order: 0, payload: {} });
    const dispose = registry.registerAll('skills', [
      { id: 'skills.route', kind: 'route', order: 1, payload: {} },
      { id: 'skills.nav', kind: 'navigation', order: 2, payload: {} },
      { id: 'skills.command', kind: 'command', order: 3, payload: {} },
    ]);
    expect(registry.list().filter((item) => item.sourceEntryId === 'skills')).toHaveLength(3);
    dispose();
    dispose();
    expect(registry.list().map((item) => item.id)).toEqual(['other']);
  });

  it('does not leak the first contribution when a later candidate conflicts', () => {
    const registry = new RendererContributionRegistryV2('desktop-renderer');
    registry.register('existing', { id: 'shared', kind: 'command', order: 0, payload: {} });
    expect(() =>
      registry.registerAll('candidate', [
        { id: 'new', kind: 'route', order: 1, payload: {} },
        { id: 'shared', kind: 'command', order: 2, payload: {} },
      ])
    ).toThrow();
    expect(registry.list().map((item) => item.sourceEntryId)).toEqual(['existing']);
  });

  it('validates the complete feature before exposing any of its contributions', () => {
    const observed: number[] = [];
    const registry = new RendererContributionRegistryV2('web', (candidate) => {
      observed.push(candidate.length);
      if (candidate.some((item) => item.payload.invalid)) throw new Error('invalid candidate');
    });
    expect(() =>
      registry.registerAll('candidate', [
        { id: 'route', kind: 'route', order: 1, payload: {} },
        { id: 'nav', kind: 'navigation', order: 2, payload: { invalid: true } },
      ])
    ).toThrow('invalid candidate');
    expect(observed).toEqual([2]);
    expect(registry.list()).toEqual([]);
  });
});
