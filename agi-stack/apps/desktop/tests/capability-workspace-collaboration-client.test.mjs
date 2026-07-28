import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createCapabilityWorkspaceCollaborationClient,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/capabilityWorkspaceCollaborationClient.js'
);

const VERSION = {
  service_version: '2.0.0',
  contract_version: '2.0.0',
  minimum_contract_version: '2.0.0',
};

function authority(calls) {
  const state = {
    workspace_id: 'workspace-1',
    surface: 'goals',
    authority: 'cloud',
    status: 'ready',
    revision: 3,
    cursor: 'cursor-3',
    data: { objectives: [] },
    reason_code: null,
  };
  return {
    getSurface: async (...args) => {
      calls.push(['get', ...args]);
      return state;
    },
    refetchAuthority: async (...args) => {
      calls.push(['refetch', ...args]);
      return state;
    },
    mutateSurface: async (...args) => {
      calls.push(['mutate', ...args]);
      return state;
    },
  };
}

test('unavailable capability returns a structured surface without probing authority', async () => {
  const calls = [];
  const client = createCapabilityWorkspaceCollaborationClient(
    authority(calls),
    {
      status: 'unavailable',
      reason_code: 'local_workspace_collaboration_unavailable',
      service_version: null,
      contract_version: null,
      minimum_contract_version: '2.0.0',
      available: false,
    },
    'local',
  );

  const state = await client.getSurface('workspace-1', 'files');
  assert.deepEqual(state, {
    workspace_id: 'workspace-1',
    surface: 'files',
    authority: 'local',
    status: 'unavailable',
    revision: null,
    cursor: null,
    data: null,
    reason_code: 'local_workspace_collaboration_unavailable',
  });
  assert.deepEqual(calls, []);
});

test('degraded capability permits canonical reads but blocks unguarded mutations', async () => {
  const calls = [];
  const client = createCapabilityWorkspaceCollaborationClient(
    authority(calls),
    {
      status: 'degraded',
      reason_code: 'workspace_collaboration_revision_guards_unavailable',
      ...VERSION,
      available: true,
    },
    'cloud',
  );

  assert.equal((await client.getSurface('workspace-1', 'goals')).status, 'ready');
  await assert.rejects(
    () =>
      client.mutateSurface('workspace-1', 'goals', {
        action: 'create_objective',
        expected_revision: 3,
        idempotency_key: 'workspace-create-1',
        payload: { title: 'Parity' },
      }),
    (error) =>
      error?.name === 'WorkspaceCollaborationCapabilityError' &&
      error?.reasonCode === 'workspace_collaboration_revision_guards_unavailable',
  );
  assert.deepEqual(
    calls.map(([name]) => name),
    ['get'],
  );
});

test('available capability delegates reads, refetches, and mutations', async () => {
  const calls = [];
  const client = createCapabilityWorkspaceCollaborationClient(
    authority(calls),
    {
      status: 'available',
      reason_code: null,
      ...VERSION,
      available: true,
    },
    'cloud',
  );

  await client.getSurface('workspace-1', 'goals');
  await client.refetchAuthority('workspace-1', 'goals');
  await client.mutateSurface('workspace-1', 'goals', {
    action: 'create_objective',
    expected_revision: 3,
    idempotency_key: 'workspace-create-1',
    payload: { title: 'Parity' },
  });
  assert.deepEqual(
    calls.map(([name]) => name),
    ['get', 'refetch', 'mutate'],
  );
});
