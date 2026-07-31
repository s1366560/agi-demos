import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const pageSource = readFileSync(
  new URL('../src/features/tenant/TenantProjectsPage.tsx', import.meta.url),
  'utf8',
);
const { restoreTenantProjectsDialogFocus } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantProjectsDialogFocus.js'
);

test('Tenant Projects dialog focus returns to its connected trigger', () => {
  const focused = [];
  const trigger = focusTarget('trigger', focused);
  const fallback = focusTarget('fallback', focused);
  const scheduled = [];

  restoreTenantProjectsDialogFocus({
    trigger,
    fallback,
    schedule(callback) {
      scheduled.push(callback);
    },
  });

  assert.deepEqual(focused, []);
  assert.equal(scheduled.length, 1);
  scheduled[0]();
  assert.deepEqual(focused, ['trigger']);
});

test('Tenant Projects dialog focus falls back when a mutation removes its trigger', () => {
  const focused = [];
  const trigger = focusTarget('trigger', focused, false);
  const fallback = focusTarget('fallback', focused);

  restoreTenantProjectsDialogFocus({
    trigger,
    fallback,
    schedule(callback) {
      callback();
    },
  });

  assert.deepEqual(focused, ['fallback']);
});

test('Tenant Projects dialogs retain one idempotency key while a failed submission is retried', () => {
  assert.match(
    pageSource,
    /idempotencyKey: createTenantProjectsMutationKey\('create'\)/u,
  );
  assert.match(pageSource, /controller\.create\(input, editor\.idempotencyKey\)/u);
  assert.match(
    pageSource,
    /idempotencyKey: createTenantProjectsMutationKey\('delete'\)/u,
  );
  assert.match(
    pageSource,
    /controller\s*\.delete\([\s\S]*?deleteProject\.project\.id,[\s\S]*?deleteProject\.idempotencyKey,[\s\S]*?\)/u,
  );
});

function focusTarget(name, focused, isConnected = true) {
  return {
    isConnected,
    focus() {
      focused.push(name);
    },
  };
}
