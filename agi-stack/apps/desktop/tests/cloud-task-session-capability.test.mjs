import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { executeVaultBoundCloudRequest } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
// Exact advertised response from the registered Avernet task-session route.
const capability = {
  schema_version: 2,
  atomic_creation: true,
  initial_conversation_mode: 'workspace',
  initial_plan_mode: 'plan',
  workspace_agent_policy: true,
  workspace_authority: 'avernet',
  capability_version: 'avernet-task-session-v1',
};
const path = '/api/v1/tenants/tenant-1/projects/project-1/task-sessions/capabilities';

test('official Cloud task-session capability route passes exact project authorization', async () => {
  const calls = [];
  const response = await executeVaultBoundCloudRequest({ path, method: 'GET' }, {
    loadTrustedSession: async () => ({ version: 1, api_base_url: 'https://cloud.test', runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'test-only', expires_at: '2099-09-14T00:00:00Z' }),
    fetch: async (url) => {
      const pathname = new URL(url).pathname;
      calls.push(pathname);
      return Response.json(pathname === '/api/v1/workspace-context'
        ? { context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 1 } }
        : capability);
    },
  });
  assert.equal(response.status, 200);
  assert.deepEqual(response.body, capability);
  assert.deepEqual(calls, ['/api/v1/workspace-context', path]);
});

test('Cloud planning preflight recognizes the actual Avernet capability payload', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => { calls.push(String(url)); return Response.json(capability); };
  try {
    const client = new DesktopApiClient({ mode: 'cloud', apiBaseUrl: 'https://cloud.test', apiKey: 'test-only', tenantId: 'tenant-1', projectId: 'project-1', workspaceId: 'workspace-1' });
    assert.equal(await client.supportsAgentPlanWorkflow(), true);
    assert.deepEqual(calls, ['https://cloud.test' + path]);
  } finally { globalThis.fetch = original; }
});

test('planning capability rejects unsupported authorities, unknown fields and malformed required contracts', async () => {
  const invalid = [
    { ...capability, workspace_authority: 'unknown' },
    { ...capability, workspace_authority: 'AVERNET' },
    { ...capability, workspace_authority: '' },
    { ...capability, workspace_authority: null },
    { ...capability, workspace_authority: true },
    { ...capability, unrelated_capability: true },
    { ...capability, atomic_creation: false },
    { ...capability, schema_version: 99 },
    { ...capability, initial_plan_mode: 'build' },
    { ...capability, initial_conversation_mode: 'single_agent' },
  ];
  const original = globalThis.fetch;
  const client = new DesktopApiClient({ mode: 'cloud', apiBaseUrl: 'https://cloud.test', apiKey: 'test-only', tenantId: 'tenant-1', projectId: 'project-1', workspaceId: 'workspace-1' });
  try {
    for (const payload of invalid) {
      globalThis.fetch = async () => Response.json(payload);
      assert.equal(await client.supportsAgentPlanWorkflow(), false, JSON.stringify(payload));
    }
    const { workspace_authority, ...legacy } = capability;
    globalThis.fetch = async () => Response.json(legacy);
    assert.equal(await client.supportsAgentPlanWorkflow(), true);
  } finally { globalThis.fetch = original; }
});
