import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  TenantCreationError,
  createTenantCreationClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/tenant-creation/tenantCreationClient.js');

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.example.test',
  deviceAuthorizationBaseUrl: 'https://cloud.example.test',
  apiKey: 'cloud-session',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
  workspaceRoot: '/workspace',
});

const tenantResponse = Object.freeze({
  id: 'tenant-2',
  name: 'Acme',
  slug: 'acme',
  description: 'Team memory',
  owner_id: 'user-1',
  plan: 'premium',
  max_projects: 3,
  max_users: 10,
  max_storage: 1073741824,
  created_at: '2026-08-02T12:00:00Z',
  updated_at: null,
});

test('tenant creation client requires the exact authenticated 201 Cloud contract', async () => {
  const calls = [];
  const client = createTenantCreationClient(cloudConfig, {
    fetch: async (url, init) => {
      calls.push({ url, init });
      return jsonResponse(201, tenantResponse);
    },
  });

  const result = await client.create({
    name: 'Acme',
    description: 'Team memory',
    plan: 'premium',
  });
  assert.deepEqual(result, tenantResponse);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://cloud.example.test/api/v1/tenants/');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer cloud-session');
  assert.equal(calls[0].init.headers.get('Content-Type'), 'application/json');
  assert.equal(
    calls[0].init.body,
    '{"name":"Acme","description":"Team memory","plan":"premium"}',
  );
});

test('tenant creation client performs no request for Local or missing authentication', async () => {
  let fetchCalls = 0;
  const fetch = async () => {
    fetchCalls += 1;
    return jsonResponse(201, tenantResponse);
  };
  const localClient = createTenantCreationClient(
    { ...cloudConfig, mode: 'local', apiKey: '', localApiToken: 'local-token' },
    { fetch },
  );
  await assert.rejects(
    localClient.create({ name: 'Acme', description: '', plan: 'free' }),
    hasReason('local_tenant_creation_not_applicable'),
  );
  const anonymousClient = createTenantCreationClient(
    { ...cloudConfig, apiKey: '' },
    { fetch },
  );
  await assert.rejects(
    anonymousClient.create({ name: 'Acme', description: '', plan: 'free' }),
    hasReason('tenant_creation_authentication_required', 401),
  );
  assert.equal(fetchCalls, 0);
});

test('tenant creation client rejects non-201 and malformed success without text heuristics', async () => {
  for (const [status, reasonCode] of [
    [400, 'tenant_creation_request_invalid'],
    [401, 'tenant_creation_authentication_required'],
    [403, 'tenant_creation_forbidden'],
    [409, 'tenant_creation_conflict'],
    [429, 'tenant_creation_rate_limited'],
    [503, 'tenant_creation_authority_unavailable'],
    [500, 'tenant_creation_request_failed'],
  ]) {
    const client = createTenantCreationClient(cloudConfig, {
      fetch: async () => jsonResponse(status, { detail: 'translated text' }),
    });
    await assert.rejects(
      client.create({ name: 'Acme', description: '', plan: 'free' }),
      hasReason(reasonCode, status),
    );
  }

  const wrongStatus = createTenantCreationClient(cloudConfig, {
    fetch: async () => jsonResponse(200, tenantResponse),
  });
  await assert.rejects(
    wrongStatus.create({ name: 'Acme', description: '', plan: 'free' }),
    hasReason('tenant_creation_contract_invalid', 200),
  );

  const malformed = createTenantCreationClient(cloudConfig, {
    fetch: async () =>
      jsonResponse(201, { ...tenantResponse, max_storage: '1073741824' }),
  });
  await assert.rejects(
    malformed.create({ name: 'Acme', description: '', plan: 'free' }),
    hasReason('tenant_creation_contract_invalid', 201),
  );
});

function hasReason(reasonCode, status = null) {
  return (error) =>
    error instanceof TenantCreationError &&
    error.reasonCode === reasonCode &&
    error.status === status;
}

function jsonResponse(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
