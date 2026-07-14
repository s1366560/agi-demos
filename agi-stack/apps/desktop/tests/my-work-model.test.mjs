import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { countMyWorkGroups, filterMyWorkItems } = require(
  '/tmp/agistack-desktop-test-dist/src/features/my-work/myWorkModel.js'
);

const items = [
  {
    id: 'approval',
    group: 'needs_approval',
    capability_mode: 'code',
    updated_at: '2026-07-13T02:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
  {
    id: 'input',
    group: 'needs_input',
    capability_mode: 'work',
    updated_at: '2026-07-13T03:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
  {
    id: 'review',
    group: 'ready_review',
    capability_mode: 'code',
    updated_at: '2026-07-13T04:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
];

test('My Work filters only explicit backend groups and capability modes', () => {
  assert.deepEqual(
    filterMyWorkItems(items, 'all', 'code').map((item) => item.id),
    ['review', 'approval']
  );
  assert.deepEqual(
    filterMyWorkItems(items, 'needs_input', 'all').map((item) => item.id),
    ['input']
  );
});

test('My Work counts preserve the four authoritative attention groups', () => {
  assert.deepEqual(countMyWorkGroups(items), {
    needs_input: 1,
    needs_approval: 1,
    running: 0,
    ready_review: 1,
  });
});
