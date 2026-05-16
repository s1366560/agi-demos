import { describe, expect, it } from 'vitest';

import { isFeatureEnabled, setFeatures } from '@/utils/featureCheck';

describe('featureCheck', () => {
  it('stores enabled feature flags', () => {
    setFeatures([
      { id: 'agent.runtime', enabled: true },
      { id: 'billing', enabled: false },
    ]);

    expect(isFeatureEnabled('agent.runtime')).toBe(true);
    expect(isFeatureEnabled('billing')).toBe(false);
  });

  it('ignores malformed feature payloads', () => {
    setFeatures([
      { id: 'valid', enabled: true },
      { id: 'missing-enabled' },
      { enabled: true },
      null,
      'not-a-feature',
    ]);

    expect(isFeatureEnabled('valid')).toBe(true);
    expect(isFeatureEnabled('missing-enabled')).toBe(false);
  });

  it('resets to empty state for non-array payloads', () => {
    setFeatures([{ id: 'previous', enabled: true }]);

    setFeatures({ features: [{ id: 'ignored', enabled: true }] });

    expect(isFeatureEnabled('previous')).toBe(false);
    expect(isFeatureEnabled('ignored')).toBe(false);
  });
});
