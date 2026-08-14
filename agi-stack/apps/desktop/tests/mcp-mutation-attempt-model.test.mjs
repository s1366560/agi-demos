import assert from 'node:assert/strict';
import test from 'node:test';

import {
  mcpToggleAttemptIdentity,
  resolveMCPMutationAttemptKey,
  retainCurrentMCPToggleAttempts,
} from '/tmp/agistack-desktop-test-dist/src/features/settings/mcpMutationAttemptModel.js';

function server(overrides = {}) {
  return {
    id: 'server-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'QA MCP',
    server_type: 'stdio',
    enabled: true,
    runtime_status: 'healthy',
    runtime_metadata: { revision: 4 },
    ...overrides,
  };
}

test('MCP toggle transport retries reuse the exact scoped mutation attempt key', () => {
  const attempts = new Map();
  let nextKey = 0;
  const createKey = () => `attempt-${++nextKey}`;
  const identity = mcpToggleAttemptIdentity('tenant-1:project-1', server());

  assert.equal(resolveMCPMutationAttemptKey(attempts, identity, createKey), 'attempt-1');
  assert.equal(resolveMCPMutationAttemptKey(attempts, identity, createKey), 'attempt-1');
  assert.equal(nextKey, 1);
});

test('MCP toggle attempt identity rotates on scope, server, revision, or target state', () => {
  const base = mcpToggleAttemptIdentity('tenant-1:project-1', server());
  assert.notEqual(base, mcpToggleAttemptIdentity('tenant-1:project-2', server()));
  assert.notEqual(base, mcpToggleAttemptIdentity('tenant-1:project-1', server({ id: 'server-2' })));
  assert.notEqual(
    base,
    mcpToggleAttemptIdentity(
      'tenant-1:project-1',
      server({ runtime_metadata: { revision: 5 } }),
    ),
  );
  assert.notEqual(base, mcpToggleAttemptIdentity('tenant-1:project-1', server({ enabled: false })));
});

test('canonical MCP refresh prunes committed and removed toggle attempts', () => {
  const contextKey = 'tenant-1:project-1';
  const currentIdentity = mcpToggleAttemptIdentity(contextKey, server());
  const committedIdentity = mcpToggleAttemptIdentity(
    contextKey,
    server({ enabled: false, runtime_metadata: { revision: 5 } }),
  );
  const attempts = new Map([
    [currentIdentity, 'current-attempt'],
    [committedIdentity, 'committed-attempt'],
    ['removed-server-attempt', 'removed-attempt'],
  ]);

  retainCurrentMCPToggleAttempts(attempts, contextKey, [server()]);

  assert.deepEqual([...attempts], [[currentIdentity, 'current-attempt']]);
});
