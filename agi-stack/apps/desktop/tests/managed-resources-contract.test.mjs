import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';
import { createTenantSubAgentDefinitionsHttpClientV2Fixture } from './tenantSubAgentDefinitionsOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const {
  ManagedResourcesClient,
  ManagedResourcesClientError,
} = require('/tmp/agistack-desktop-test-dist/src/api/managedResourcesClient.js');
const { DesktopApiError } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('managed resource lists reject malformed successful collection payloads', async () => {
  const originalFetch = globalThis.fetch;
  const payloads = [
    { unexpected: [] },
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
    const config = {
      ...DEFAULT_CONFIG,
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'managed-resource-trusted-session',
      localApiToken: 'managed-resource-launch',
      tenantId: 'tenant-1',
      projectId: 'project-1',
    };
    const client = new ManagedResourcesClient(config);
    const subagents = createTenantSubAgentDefinitionsHttpClientV2Fixture(config);
    await assert.rejects(
      () => client.listManagedSkills(),
      (error) =>
        error instanceof ManagedResourcesClientError &&
        error.status === 502 &&
        error.payload?.code === 'managed_resource_list_contract_invalid',
    );
    await assert.rejects(
      () => subagents.listManagedSubAgents(),
      (error) =>
        error instanceof DesktopApiError &&
        error.status === 502 &&
        error.reasonCode === 'tenant_subagent_definitions_collection_contract_invalid',
    );
    assert.equal(payloads.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
