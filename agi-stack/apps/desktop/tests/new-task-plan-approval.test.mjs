import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  approvalCapability,
  approvalPlanVersion,
  canApprovePlan,
  canApprovePlanVersion,
  defaultPermissionProfile,
  hasPlanVersionChanged,
  isPlanApprovalBlocked,
  legacyPlanMatchesPreview,
  planVersionIdentity,
} = require('/tmp/agistack-desktop-test-dist/src/features/task/newTaskApprovalModel.js');
const { planTaskSignature } = require(
  '/tmp/agistack-desktop-test-dist/src/features/task/newTaskPlanModel.js'
);

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

test('approval capability is explicit and keeps versioned plan authority', () => {
  const response = {
    conversation_id: 'conversation-1',
    tasks: [],
    total_count: 0,
    approval: { kind: 'versioned_atomic', plan_version: draftPlan },
  };

  assert.deepEqual(approvalCapability(response), response.approval);
  assert.deepEqual(approvalPlanVersion(response), draftPlan);
  assert.equal(canApprovePlan(response.approval, draftPlan, false, 2), true);
  assert.equal(canApprovePlan(response.approval, draftPlan, true, 2), false);
});

test('legacy approval is allowed only after a non-empty unchanged preview', () => {
  const capability = { kind: 'legacy_mode_switch' };
  assert.equal(canApprovePlan(capability, null, false, 2), true);
  assert.equal(canApprovePlan(capability, null, true, 2), false);
  assert.equal(canApprovePlan(capability, null, false, 0), false);
  assert.equal(isPlanApprovalBlocked(false, true), true);
  assert.equal(isPlanApprovalBlocked(true, false), true);
  assert.equal(isPlanApprovalBlocked(false, false), false);
});

test('legacy approval rechecks the exact authoritative task signature', () => {
  const task = {
    id: 'task-1',
    conversation_id: 'conversation-1',
    content: 'Inspect',
    status: 'pending',
    priority: 'high',
    order_index: 1,
    created_at: '2026-07-14T00:00:00Z',
    updated_at: '2026-07-14T00:00:00Z',
  };
  const response = {
    conversation_id: 'conversation-1',
    tasks: [task],
    total_count: 1,
    approval: { kind: 'legacy_mode_switch' },
  };
  const reviewedSignature = planTaskSignature([task]);

  assert.equal(legacyPlanMatchesPreview(response, reviewedSignature), true);
  assert.equal(
    legacyPlanMatchesPreview(
      { ...response, tasks: [{ ...task, content: 'Inspect and verify' }] },
      reviewedSignature,
    ),
    false,
  );
  assert.equal(
    legacyPlanMatchesPreview(
      { ...response, tasks: [{ ...task, id: 'replacement-task' }] },
      reviewedSignature,
    ),
    false,
  );
  assert.equal(
    legacyPlanMatchesPreview(
      { ...response, approval: { kind: 'versioned_atomic', plan_version: draftPlan } },
      reviewedSignature,
    ),
    false,
  );
});
