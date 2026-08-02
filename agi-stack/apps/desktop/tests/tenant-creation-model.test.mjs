import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createTenantCreationDraft,
  tenantCreationIsDirty,
  upsertCreatedTenant,
  validateTenantCreationDraft,
} = require('/tmp/agistack-desktop-test-dist/src/features/tenant-creation/tenantCreationModel.js');

test('tenant creation draft preserves the Web plan defaults and field boundaries', () => {
  assert.deepEqual(createTenantCreationDraft(), {
    name: '',
    description: '',
    plan: 'free',
  });
  assert.deepEqual(
    validateTenantCreationDraft({
      name: ' Acme ',
      description: ' Team memory ',
      plan: 'premium',
    }),
    {
      valid: true,
      value: {
        name: 'Acme',
        description: 'Team memory',
        plan: 'premium',
      },
    },
  );
});

test('tenant creation validation fails closed for every unsupported field state', () => {
  for (const [draft, reasonCode] of [
    [{ name: '', description: '', plan: 'free' }, 'tenant_creation_name_required'],
    [
      { name: 'a'.repeat(256), description: '', plan: 'free' },
      'tenant_creation_name_too_long',
    ],
    [
      { name: 'Acme', description: 'a'.repeat(1001), plan: 'free' },
      'tenant_creation_description_too_long',
    ],
    [
      { name: 'Acme', description: '', plan: 'custom' },
      'tenant_creation_plan_invalid',
    ],
  ]) {
    assert.deepEqual(validateTenantCreationDraft(draft), {
      valid: false,
      reasonCode,
    });
  }
});

test('dirty state and catalog update use structural form and authority identities', () => {
  assert.equal(
    tenantCreationIsDirty({ name: '', description: '', plan: 'free' }),
    false,
  );
  assert.equal(
    tenantCreationIsDirty({ name: '', description: '', plan: 'premium' }),
    true,
  );
  const original = Object.freeze([
    Object.freeze({ id: 'tenant-1', name: 'One', plan: 'free' }),
  ]);
  const created = Object.freeze({
    id: 'tenant-2',
    name: 'Two',
    slug: 'two',
    description: null,
    owner_id: 'user-1',
    plan: 'premium',
    created_at: '2026-08-02T12:00:00Z',
    updated_at: null,
  });
  const appended = upsertCreatedTenant(original, created);
  assert.notEqual(appended, original);
  assert.deepEqual(appended.map((tenant) => tenant.id), ['tenant-1', 'tenant-2']);
  assert.deepEqual(
    upsertCreatedTenant(appended, { ...created, name: 'Two updated' }),
    [original[0], { ...created, name: 'Two updated' }],
  );
});
