import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist';
const { executeVaultBoundCloudRequest } = require(
  `${root}/apps/desktop/electron/main/cloudRequestPolicy.js`,
);
const digest = `sha256:${'a'.repeat(64)}`;

function harness(context = { tenant_id: 'tenant-1', project_id: 'project-1', revision: 1 }) {
  return {
    async loadTrustedSession() {
      return {
        version: 1,
        api_base_url: 'https://cloud.memstack.test',
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: 'test-only-vault-token',
        expires_at: null,
      };
    },
    async fetch(url) {
      const path = new URL(url).pathname;
      const body = path === '/api/v1/workspace-context'
        ? { context }
        : { ok: true };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    },
  };
}

function command(path, body) {
  return { path, method: 'POST', body: { expected_digest: digest, ...body } };
}

test('full desktop rejects legacy business HTTP that signed contributions do not declare', async () => {
  const dependencies = harness();
  const legacy = [
    { path: '/api/v1/graph-stores/types', method: 'GET' },
    { path: '/api/v1/retrieval-stores/types', method: 'GET' },
    {
      path: '/api/v1/memories/?project_id=project-1&page=1&page_size=20',
      method: 'GET',
    },
    { path: '/api/v1/projects/project-1/playbooks?limit=200', method: 'GET' },
  ];
  for (const request of legacy) {
    await assert.rejects(
      executeVaultBoundCloudRequest(request, dependencies),
      /cloud request endpoint is not allowed/,
    );
  }
});

test('full desktop still admits contribution commands and host chrome', async () => {
  const dependencies = harness();
  const projectCommand = command(
    '/api/v1/platform-plugins/v2/optional-business/memstack-agent/commands',
    {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      command_id: 'chat-composer-read',
    },
  );
  const tenantCommand = command('/api/v1/tenant-packages/memstack-agent/commands', {
    tenant_id: 'tenant-1',
    command_id: 'dashboard-read',
  });
  assert.equal((await executeVaultBoundCloudRequest(projectCommand, dependencies)).status, 200);
  assert.equal((await executeVaultBoundCloudRequest(tenantCommand, dependencies)).status, 200);
  assert.equal(
    (await executeVaultBoundCloudRequest({ path: '/api/v1/auth/me', method: 'GET' }, dependencies)).status,
    200,
  );
});

test('installed packages outside the six business ids stay callable', async () => {
  const dependencies = harness();
  const ui = '/api/v1/platform-plugins/v2/optional-business/sample.notes/ui?' + new URLSearchParams({
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    target: 'desktop-renderer',
    expected_digest: digest,
  });
  assert.equal((await executeVaultBoundCloudRequest({ path: ui, method: 'GET' }, dependencies)).status, 200);
  assert.equal((await executeVaultBoundCloudRequest(command(
    '/api/v1/platform-plugins/v2/optional-business/sample.notes/commands',
    { tenant_id: 'tenant-1', project_id: 'project-1', command_id: 'ping' },
  ), dependencies)).status, 200);
  assert.equal((await executeVaultBoundCloudRequest(command(
    '/api/v1/tenant-packages/sample.notes/commands',
    { tenant_id: 'tenant-1', command_id: 'ping' },
  ), dependencies)).status, 200);
});

test('package calls keep tenant and project scope from assertEndpointScope', async () => {
  const dependencies = harness();
  await assert.rejects(
    executeVaultBoundCloudRequest(
      command('/api/v1/tenant-packages/memstack-agent/commands', {
        tenant_id: 'foreign-tenant',
        command_id: 'dashboard-read',
      }),
      dependencies,
    ),
    /cloud request tenant scope mismatch/,
  );
  await assert.rejects(
    executeVaultBoundCloudRequest(
      command('/api/v1/platform-plugins/v2/optional-business/memstack-agent/commands', {
        tenant_id: 'tenant-1',
        project_id: 'foreign-project',
        command_id: 'chat-composer-read',
      }),
      dependencies,
    ),
    /cloud request project scope mismatch/,
  );
});
