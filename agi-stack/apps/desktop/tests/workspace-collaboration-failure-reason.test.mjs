import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { workspaceCollaborationFailureReason } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceCollaborationFailureReason.js',
);
test('preserves the structured upstream rejection instead of reporting a refetch failure', () => {
  assert.equal(workspaceCollaborationFailureReason({
    reason_code: 'workspace_surface_request_failed',
    payload: { detail: { reason_code: 'workspace_collaboration_payload_invalid', message: 'private' } },
  }, 'workspace_surface_mutation_failed'), 'workspace_collaboration_payload_invalid');
});
test('retains genuine stale refetch codes and hides arbitrary error text', () => {
  assert.equal(workspaceCollaborationFailureReason({ reason_code: 'workspace_surface_stale_refetch' },
    'workspace_surface_mutation_failed'), 'workspace_surface_stale_refetch');
  for (const error of [new Error('private bearer credential'), { code: 'Bearer private' }, null,
    { payload: { detail: { reason_code: 'private\ncredential' } } }]) {
    assert.equal(workspaceCollaborationFailureReason(error, 'workspace_surface_mutation_failed'),
      'workspace_surface_mutation_failed');
  }
});
