import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createProfileFilteredHashLocationPort,
  matchProfileAuxiliaryRoute,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings-routes/profileAuxiliaryRoute.js');

test('Profile auxiliary deep links are strict global aliases outside the 55-route registry', () => {
  assert.deepEqual(matchProfileAuxiliaryRoute('#/tenant/profile'), {
    capability: 'user-profile',
    tenantId: null,
  });
  assert.deepEqual(matchProfileAuxiliaryRoute('#/tenant/tenant-1/profile'), {
    capability: 'user-profile',
    tenantId: 'tenant-1',
  });
  for (const invalid of [
    '',
    '#/',
    '#/tenant',
    '#/tenant//profile',
    '#/tenant/tenant-1/profile/extra',
    '#/tenant/%2F/profile',
    '#/tenant/tenant-1/settings',
  ]) {
    assert.equal(matchProfileAuxiliaryRoute(invalid), null, invalid);
  }
});

test('Profile filter hides only auxiliary aliases from the production router', () => {
  let hash = '#/tenant/tenant-1/profile';
  const listeners = new Set();
  const base = {
    readHash: () => hash,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
  const filtered = createProfileFilteredHashLocationPort(base);
  assert.equal(filtered.readHash(), '');
  hash = '#/tenant/tenant-1/projects';
  for (const listener of listeners) listener();
  assert.equal(filtered.readHash(), '#/tenant/tenant-1/projects');
});
