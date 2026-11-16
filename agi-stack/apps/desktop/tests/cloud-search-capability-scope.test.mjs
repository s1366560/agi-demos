import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { authorizeCloudProductEndpoint } = require('/tmp/agistack-desktop-test-dist/apps/desktop/electron/main/cloudProductEndpointPolicy.js');

test('search capability request binds its exact tenant and project to native authority', () => {
  const base = 'https://cloud.test/api/v1/search-enhanced/capabilities';
  const url = new URL(`${base}?tenant_id=tenant-1&project_id=project-1`);
  assert.deepEqual(authorizeCloudProductEndpoint({ method: 'GET' }, url), {
    kind: 'project', tenantId: 'tenant-1', projectId: 'project-1', workspaceId: null,
  });
  for (const query of ['tenant_id=tenant-1', 'project_id=project-1', 'tenant_id=&project_id=p', 'tenant_id=t&project_id=p&extra=1', 'tenant_id=t&project_id=p&project_id=q']) {
    assert.equal(authorizeCloudProductEndpoint({ method: 'GET' }, new URL(`${base}?${query}`)), null);
  }
  assert.equal(authorizeCloudProductEndpoint({ method: 'POST' }, url), null);
});
