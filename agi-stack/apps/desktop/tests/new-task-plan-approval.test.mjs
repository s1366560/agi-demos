import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  canApprovePlanVersion,
  defaultPermissionProfile,
  hasPlanVersionChanged,
  planVersionIdentity,
} = require('/tmp/agistack-desktop-test-dist/src/features/task/NewTaskFlow.js');

const draftPlan = {
  id: 'plan-version-2',
  conversation_id: 'conversation-1',
  version: 2,
  status: 'draft',
  tasks: [],
  created_at: '2026-07-13T08:00:00Z',
};

test('plan approval identity binds the immutable id and monotonic version', () => {
  assert.equal(planVersionIdentity(draftPlan), 'plan-version-2:2');
  assert.equal(planVersionIdentity(null), '');
  assert.equal(
    hasPlanVersionChanged(draftPlan, {
      ...draftPlan,
      id: 'plan-version-3',
      version: 3,
    }),
    true,
  );
  assert.equal(hasPlanVersionChanged(draftPlan, { ...draftPlan }), false);
});

test('approval is disabled until the latest draft version has been reviewed', () => {
  assert.equal(canApprovePlanVersion(draftPlan, false), true);
  assert.equal(canApprovePlanVersion(draftPlan, true), false);
  assert.equal(canApprovePlanVersion(null, false), false);
  assert.equal(canApprovePlanVersion({ ...draftPlan, status: 'approved' }, false), false);
});

test('permission defaults use explicit task kinds without semantic text inference', () => {
  assert.equal(defaultPermissionProfile('general'), 'read_only');
  assert.equal(defaultPermissionProfile('programming'), 'workspace_write');
});
