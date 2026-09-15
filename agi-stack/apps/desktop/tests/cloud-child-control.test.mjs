import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/';
const { decodeCloudChildAuthority, loadCloudChildAuthority, sendCloudChildControl } = require(root + 'src/features/chat/cloudSubagentControlClient.js');
const { subAgentGroupControlAvailability } = require(root + 'src/features/chat/subagentControlAuthorityModel.js');
const { subAgentControlSocketMessage } = require(root + 'src/hooks/useAgentSocket.js');
const { executeVaultBoundCloudRequest } = require(root + 'electron/main/cloudRequestPolicy.js');
const { DEFAULT_CONFIG } = require(root + 'src/types.js');
const config = { ...DEFAULT_CONFIG, mode: 'cloud', apiBaseUrl: 'https://test.invalid', apiKey: '', tenantId: 'tenant', projectId: 'project' };
const row = { conversation_id: 'conversation', run_id: 'actual-child', subagent_name: 'worker', status: 'running', control_revision: 0, cancel_requested: false, allowed_actions: ['steer', 'kill_run'] };
const snapshot = { schema_version: 1, authority_kind: 'subagent_execution_registry', conversation_id: 'conversation', tenant_id: 'tenant', project_id: 'project', controls: [row] };
test('Cloud child authority uses persisted execution identity without a parent run or resource roster', () => {
  const authority = decodeCloudChildAuthority(snapshot, config, 'conversation');
  assert.equal(authority.authorityRevision, null);
  assert.deepEqual(subAgentGroupControlAvailability(authority, { runId: 'actual-child', subagentId: 'resource', status: 'running' }).allowedActions, ['steer', 'kill_run']);
  assert.equal(subAgentGroupControlAvailability(authority, { runId: 'resource', subagentId: 'resource', status: 'running' }).available, false);
  for (const patch of [{ tenant_id: 'foreign' }, { conversation_id: 'foreign' }, { authority_kind: 'workspace_session' }, { controls: [row, row] }, { controls: [{ ...row, status: 'completed' }] }, { controls: [{ ...row, control_revision: null }] }]) {
    assert.throws(() => decodeCloudChildAuthority({ ...snapshot, ...patch }, config, 'conversation'));
  }
  const terminal = decodeCloudChildAuthority({ ...snapshot, controls: [{ ...row, status: 'cancelled', allowed_actions: [] }] }, config, 'conversation');
  assert.equal(subAgentGroupControlAvailability(terminal, { runId: row.run_id }).available, false);
});
test('Cloud client traverses exact vault scope and HTTP child control while Local rejects missing parent revision', async () => {
  const calls = [];
  const deps = {
    loadTrustedSession: async () => ({ version: 1, api_base_url: config.apiBaseUrl, runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'fixture', expires_at: '2099-01-01T00:00:00Z' }),
    fetch: async (input, init) => {
      const url = new URL(input); calls.push(url.pathname);
      const payload = url.pathname === '/api/v1/workspace-context' ? { context: { tenant_id: 'tenant', project_id: 'project', revision: 1 } }
        : url.pathname === '/api/v1/agent/conversations/conversation' ? { id: 'conversation', tenant_id: 'tenant', project_id: 'project' }
        : url.pathname.endsWith('/subagent-controls') ? snapshot
        : { accepted: true, duplicate: false, conversation_id: 'conversation', run_id: 'actual-child', control_revision: 1, action: 'steer', idempotency_key: JSON.parse(init.body).idempotency_key };
      return new Response(JSON.stringify(payload), { headers: { 'content-type': 'application/json' } });
    },
  };
  const original = globalThis.window;
  globalThis.window = { __MEMSTACK_DESKTOP__: { core: { invoke: async (command, args) => { assert.equal(command, 'cloud_request'); return executeVaultBoundCloudRequest(args.request, deps); } } } };
  try {
    const authority = await loadCloudChildAuthority(config, 'conversation');
    assert.equal(authority.cloudControls[0].runId, 'actual-child');
    const command = { action: 'steer', conversationId: 'conversation', runId: 'actual-child', expectedRunRevision: null, expectedControlRevision: 0, idempotencyKey: 'first', instruction: 'follow instruction' };
    assert.equal(subAgentControlSocketMessage(command), null);
    assert.equal((await sendCloudChildControl(config, command)).accepted, true);
    assert.ok(calls.includes('/api/v1/agent/conversations/conversation/subagents/actual-child/control'));
    assert.equal((await sendCloudChildControl(config, { ...command, expectedRunRevision: 9 })).accepted, false);
    await assert.rejects(executeVaultBoundCloudRequest({ path: '/api/v1/agent/conversations/conversation/subagent-controls?tenant_id=foreign&project_id=project', method: 'GET' }, deps), /tenant scope mismatch/);
    await assert.rejects(executeVaultBoundCloudRequest({ path: '/api/v1/agent/conversations/conversation/subagents/actual-child/control?tenant_id=tenant&project_id=project', method: 'POST', body: { action: 'kill_run', expected_run_revision: 1, idempotency_key: 'key' } }, deps), /endpoint is not allowed/);
  } finally { if (original === undefined) delete globalThis.window; else globalThis.window = original; }
});
