import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  dispatchDesktopLocalRun,
  localRunCloudFields,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/localRunDispatch.js');

const absoluteRoot = '/Users/alice/src/agi-demos';

test('cloud fields omit the absolute directory and a failed sidecar does not look synced', async () => {
  const input = {
    userId: 'user-1',
    tenantId: 'tenant-1',
    conversationId: 'conv-1',
    message: 'list the workspace',
    idempotencyKey: 'local-key-001',
    wire: {
      execution_target: 'local',
      execution_machine_id: 'machine-a',
      execution_environment_id: null,
      local_root_label: 'agi-demos',
    },
    localRoot: absoluteRoot,
  };
  const cloud = localRunCloudFields(input);
  assert.equal(JSON.stringify(cloud).includes(absoluteRoot), false);
  assert.equal(cloud.local_root_label, 'agi-demos');
  assert.equal(cloud.execution_target, 'local');
  let invoked = null;
  const pending = await dispatchDesktopLocalRun(input, async (command, args) => {
    invoked = { command, args };
    return {
      sync: 'pending',
      run_id: 'run-1',
      status: 'running',
      executed: true,
      detail: 'The cloud record is not synced yet.',
    };
  });
  assert.equal(invoked.command, 'local_run_execute');
  assert.equal(invoked.args.local_root, absoluteRoot);
  assert.equal(Object.hasOwn(invoked.args, 'authorization'), false);
  assert.equal(Object.hasOwn(invoked.args, 'api_base_url'), false);
  assert.equal(JSON.stringify({ ...invoked.args, local_root: undefined }).includes(absoluteRoot), false);
  assert.equal(pending.sync, 'pending');
  assert.equal(pending.detail.includes('not synced'), true);
  const failed = await dispatchDesktopLocalRun(input, async () => {
    throw new Error('sidecar down');
  });
  assert.equal(failed.sync, 'failed');
  assert.equal(failed.detail.toLowerCase().includes('synced') && !failed.detail.toLowerCase().includes('not'), false);
});

test('a failed local turn stays failed when its record successfully reached the cloud', () => {
  const { localRunFailureMessageKey } = require('/tmp/agistack-desktop-test-dist/src/features/chat/localRunDispatch.js');
  assert.equal(localRunFailureMessageKey({ sync: 'synced', status: 'failed' }), 'executionPlacement.localTurnFailed');
  assert.equal(localRunFailureMessageKey({ sync: 'failed', status: 'queued' }), 'executionPlacement.localUploadFailed');
  assert.equal(localRunFailureMessageKey({ sync: 'conflict', status: 'queued' }), 'executionPlacement.localUploadConflict');
  assert.equal(localRunFailureMessageKey({ sync: 'synced', status: 'completed' }), null);
});
