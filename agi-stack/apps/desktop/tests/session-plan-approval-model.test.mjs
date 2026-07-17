import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  canApproveSessionPlan,
  defaultSessionPlanApprovalSelection,
  normalizeSessionTaskListPlan,
  sessionPlanTaskPriorityTranslationKey,
  sessionPlanTaskStatusTranslationKey,
  sessionPlanApprovalIdentity,
  sessionPlanApprovalRequest,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionPlanApprovalModel.js');

const draftPlan = {
  id: 'plan-version-7',
  conversation_id: 'conversation-1',
  version: 7,
  status: 'draft',
  tasks: [{ id: 'task-1', content: 'Inspect the authoritative session' }],
  created_at: '2026-07-16T09:00:00Z',
  approved_at: null,
};

const approvalCapabilities = {
  canSendMessage: true,
  canApprovePlan: true,
  canRespondToHitl: false,
  canSteerNow: false,
  canQueueNext: false,
  canReviewArtifacts: false,
  canDeliverArtifacts: false,
  runActions: [],
  allowedActions: ['send_message', 'approve_plan_and_start'],
};

test('draft plan approval requires both the capability flag and the explicit action', () => {
  assert.equal(canApproveSessionPlan(draftPlan, approvalCapabilities), true);
  assert.equal(
    canApproveSessionPlan(draftPlan, {
      ...approvalCapabilities,
      canApprovePlan: false,
    }),
    false,
  );
  assert.equal(
    canApproveSessionPlan(draftPlan, {
      ...approvalCapabilities,
      allowedActions: ['send_message'],
    }),
    false,
  );
  assert.equal(
    canApproveSessionPlan({ ...draftPlan, status: 'approved' }, approvalCapabilities),
    false,
  );
  assert.equal(canApproveSessionPlan({ ...draftPlan, tasks: [] }, approvalCapabilities), false);
});

test('session plan defaults preserve the safe work and isolated code boundaries', () => {
  assert.deepEqual(defaultSessionPlanApprovalSelection('work'), {
    environmentKind: 'local',
    permissionProfile: 'read_only',
  });
  assert.deepEqual(defaultSessionPlanApprovalSelection('code'), {
    environmentKind: 'worktree',
    permissionProfile: 'workspace_write',
  });
  assert.deepEqual(defaultSessionPlanApprovalSelection('unavailable'), {
    environmentKind: 'local',
    permissionProfile: 'read_only',
  });
});

test('approval request binds the exact previewed version and retry identity', () => {
  const identity = sessionPlanApprovalIdentity({
    conversationId: 'conversation-1',
    plan: draftPlan,
    environmentKind: 'worktree',
    permissionProfile: 'workspace_write',
  });
  assert.equal(identity, 'conversation-1:plan-version-7:7:worktree:workspace_write');
  assert.deepEqual(
    sessionPlanApprovalRequest({
      conversationId: 'conversation-1',
      projectId: 'project-1',
      plan: draftPlan,
      environmentKind: 'worktree',
      permissionProfile: 'workspace_write',
      requestId: 'request-42',
    }),
    {
      conversationId: 'conversation-1',
      projectId: 'project-1',
      planVersionId: 'plan-version-7',
      expectedPlanVersion: 7,
      permissionProfile: 'workspace_write',
      message:
        'The human approved the current structured plan.\n\nBuild mode is now active. Execute the approved tasks in order.\n\nKeep the task list status current and pause for any permission, credential, or irreversible decision.',
      messageId: 'desktop-build-request-42',
      idempotencyKey: 'desktop-plan-approval-request-42',
      environmentKind: 'worktree',
    },
  );
});

test('cloud task-list recovery is all-or-nothing and conversation scoped', () => {
  const recovered = normalizeSessionTaskListPlan(
    [
      {
        id: 'task-2',
        conversation_id: 'conversation-1',
        content: 'Verify the recovered plan',
        status: 'pending',
        priority: 'medium',
        order_index: 2,
        created_at: '2026-07-16T09:01:00Z',
        updated_at: null,
      },
      {
        id: 'task-1',
        conversation_id: 'conversation-1',
        content: 'Inspect the recovered plan',
        status: 'in_progress',
        priority: 'high',
        order_index: 1,
        created_at: '2026-07-16T09:00:00Z',
        updated_at: '2026-07-16T09:02:00Z',
      },
    ],
    'conversation-1',
  );

  assert.deepEqual(recovered?.map((task) => task.id), ['task-1', 'task-2']);
  assert.equal(recovered?.[1].updated_at, '');
  assert.equal(
    normalizeSessionTaskListPlan(
      [{ ...recovered[0], conversation_id: 'conversation-2' }],
      'conversation-1',
    ),
    null,
  );
  assert.equal(
    normalizeSessionTaskListPlan([{ ...recovered[0], content: '' }], 'conversation-1'),
    null,
  );
});

test('task presentation maps protocol values to localized keys', () => {
  assert.equal(sessionPlanTaskStatusTranslationKey('pending'), 'session.planTaskState.pending');
  assert.equal(
    sessionPlanTaskStatusTranslationKey('in_progress'),
    'session.planTaskState.in_progress',
  );
  assert.equal(sessionPlanTaskStatusTranslationKey('unexpected'), 'session.planTaskState.unknown');
  assert.equal(sessionPlanTaskPriorityTranslationKey('high'), 'task.priorityHigh');
  assert.equal(sessionPlanTaskPriorityTranslationKey('unexpected'), 'task.priorityUnknown');
});
