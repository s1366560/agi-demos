import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  approvalResponseSubmission,
  latestPendingApproval,
  validateApprovalRequest,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionDecisionModel.js');

const completeRequest = {
  id: 'approval-1',
  conversation_id: 'conversation-1',
  run_id: 'run-1',
  run_revision: 7,
  round: 2,
  kind: 'permission',
  prompt: 'Allow this change?',
  status: 'pending',
  created_at: '2026-07-13T08:00:00Z',
  responded_at: null,
  decision: {
    action: { name: 'workspace.write', label: 'Apply patch' },
    target: { kind: 'worktree', id: 'worktree-1', path: 'src/lib.rs' },
    data: { summary: 'Apply the reviewed patch', redacted_fields: ['api_key'] },
    reason: 'The requested implementation needs this edit',
    risk: { level: 'medium', rationale: 'Runtime behavior will change' },
    reversibility: { mode: 'reversible', recovery: 'Restore checkpoint-6' },
    scope: { kind: 'files', ids: ['src/lib.rs'] },
    evidence: [
      { kind: 'diff', id: 'diff-1', label: 'Patch preview', digest: 'sha256:abc' },
    ],
  },
};

const cloudPermissionRequest = {
  id: 'cloud-permission-1',
  conversation_id: 'conversation-1',
  run_id: null,
  kind: 'permission',
  prompt: 'Allow the reviewed command?',
  status: 'pending',
  created_at: '2026-07-13T10:00:00Z',
  responded_at: null,
  permission: {
    tool_name: 'terminal.execute',
    action: 'run the reviewed test command',
    risk_level: 'medium',
    description: 'Run the focused test suite',
    allow_remember: false,
  },
};

test('approval validation preserves the agent-authored eight-field decision contract', () => {
  assert.deepEqual(validateApprovalRequest(completeRequest), {
    complete: true,
    missing: [],
    canApprove: true,
  });
});

test('an incomplete decision never becomes approvable and no risk is inferred', () => {
  const request = {
    ...completeRequest,
    id: 'approval-incomplete',
    decision: {
      ...completeRequest.decision,
      risk: undefined,
      evidence: [],
    },
  };

  assert.deepEqual(validateApprovalRequest(request), {
    complete: false,
    missing: ['risk', 'evidence'],
    canApprove: false,
  });
});

test('cloud permission validation uses only its persisted structured protocol fields', () => {
  assert.deepEqual(validateApprovalRequest(cloudPermissionRequest), {
    complete: true,
    missing: [],
    canApprove: true,
  });
  assert.deepEqual(
    validateApprovalRequest({
      ...cloudPermissionRequest,
      permission: { ...cloudPermissionRequest.permission, risk_level: 'unknown' },
    }),
    {
      complete: false,
      missing: ['risk'],
      canApprove: false,
    },
  );
});

test('the latest pending structured approval is selected without prompt heuristics', () => {
  const latest = { ...completeRequest, id: 'approval-2', created_at: '2026-07-13T09:00:00Z' };
  const responded = { ...completeRequest, id: 'approval-3', status: 'responded' };

  assert.equal(latestPendingApproval([responded, completeRequest, latest])?.id, 'approval-2');
});

test('the latest cloud permission is selected without synthesizing a decision packet', () => {
  assert.equal(latestPendingApproval([completeRequest, cloudPermissionRequest])?.id, 'cloud-permission-1');
});

test('permission approval binds request, run revision, and idempotency key', () => {
  assert.deepEqual(approvalResponseSubmission(completeRequest, 'approve'), {
    requestId: 'approval-1',
    hitlType: 'permission',
    expectedRevision: 7,
    idempotencyKey: 'approval-1:7:approve',
    responseData: { granted: true },
  });
});

test('request changes carries explicit feedback and denies the permission', () => {
  assert.deepEqual(
    approvalResponseSubmission(completeRequest, 'request_changes', 'Keep the public API stable'),
    {
      requestId: 'approval-1',
      hitlType: 'permission',
      expectedRevision: 7,
      idempotencyKey: 'approval-1:7:request_changes',
      responseData: { granted: false, feedback: 'Keep the public API stable' },
    },
  );
});
