import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  ManagedResourcesClient,
  ManagedResourcesClientError,
} = require('/tmp/agistack-desktop-test-dist/src/api/managedResourcesClient.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('managed resource lists reject malformed successful collection payloads', async () => {
  const originalFetch = globalThis.fetch;
  const payloads = [
    { unexpected: [] },
    { definitions: null },
    { agents: 'not-an-array' },
    { subagents: {} },
  ];
  globalThis.fetch = async () => {
    const payload = payloads.shift();
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new ManagedResourcesClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      tenantId: 'tenant-1',
      projectId: 'project-1',
    });
    for (const load of [
      () => client.listManagedSkills(),
      () => client.listManagedAgents(),
      () => client.listManagedExternalAcpAgents(),
      () => client.listManagedSubAgents(),
    ]) {
      await assert.rejects(
        load,
        (error) =>
          error instanceof ManagedResourcesClientError &&
          error.status === 502 &&
          error.payload?.code === 'managed_resource_list_contract_invalid',
      );
    }
    assert.equal(payloads.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
