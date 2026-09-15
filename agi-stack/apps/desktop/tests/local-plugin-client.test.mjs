import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  createLocalPluginClient,
  pluginArchiveBase64,
} = require('/tmp/agistack-desktop-test-dist/src/api/localPluginClient.js');
const config = { mode: 'local', tenantId: 'tenant-1', projectId: 'project-1' };
const scope = {
  kind: 'project',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
};
const reference = {
  bundle_id: 'signed-test',
  version: '1.0.0',
  digest: 'sha256:' + 'a'.repeat(64),
  source: 'local-file://signed-test/1.0.0',
};
const inspection = {
  reference,
  scope,
  verified: true,
  declared_permissions: ['file:read', 'network:connect'],
  plugins: [{ plugin_id: 'plugin-test', version: '1.0.0' }],
};
const installation = {
  reference,
  scope,
  enabled: true,
  authorization_status: 'approved',
  activation_status: 'active',
  activation_error: null,
  approved_permissions: inspection.declared_permissions,
};

test('local catalog strictly rejects cross-scope, missing approval state and contradictory revoked enablement', async () => {
  const response = { installations: [installation], trust_configured: true };
  const client = createLocalPluginClient(config, async (path) => {
    assert.equal(
      path,
      '/api/v1/local-plugins/v2/installations?tenant_id=tenant-1&project_id=project-1',
    );
    return response;
  });
  assert.deepEqual((await client.list()).installations, [installation]);
  for (const change of [
    (item) => {
      item.scope.project_id = 'other';
    },
    (item) => {
      item.scope.tenant_id = 'other';
    },
    (item) => {
      item.scope.session_id = 'conversation-1';
    },
    (item) => {
      delete item.authorization_status;
    },
    (item) => {
      item.authorization_status = 'revoked';
    },
  ]) {
    const item = structuredClone(installation);
    change(item);
    response.installations = [item];
    await assert.rejects(client.list(), /local_plugin_response_invalid/);
  }
});

test('only a verified scoped preview may authorize all declared permissions', async () => {
  const requests = [];
  let response = inspection;
  const client = createLocalPluginClient(config, async (path, options) => {
    requests.push({ path, options });
    return response;
  });
  const preview = await client.inspect('YXJjaGl2ZQ==');
  assert.deepEqual(requests[0].options.body, {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    archive_base64: 'YXJjaGl2ZQ==',
  });
  response = { reference, scope, status: 'installed' };
  await assert.rejects(client.install(preview, 'YXJjaGl2ZQ==', []), /permissions_invalid/);
  await assert.rejects(
    client.install(preview, 'YXJjaGl2ZQ==', ['file:read']),
    /permissions_invalid/,
  );
  await assert.rejects(
    client.install(preview, 'YXJjaGl2ZQ==', ['file:read', 'file:read']),
    /permissions_invalid/,
  );
  assert.equal(requests.length, 1);
  await client.install(preview, 'YXJjaGl2ZQ==', preview.declared_permissions);
  assert.deepEqual(Object.keys(requests[1].options.body).sort(), [
    'approved_permissions',
    'archive_base64',
    'project_id',
    'reference',
    'tenant_id',
  ]);
  response = { ...inspection, verified: false };
  await assert.rejects(client.inspect('YXJjaGl2ZQ=='), /response_invalid/);
});

test('management receipts must match the requested immutable reference and action', async () => {
  let response = { reference, scope, status: 'disabled' };
  const client = createLocalPluginClient(config, async (path, options) => {
    assert.equal(path, '/api/v1/local-plugins/v2/installations/signed-test/disable');
    assert.deepEqual(options.body, {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      reference,
    });
    return response;
  });
  assert.equal((await client.control('disable', installation)).status, 'disabled');
  response = { ...response, reference: { ...reference, digest: 'other' } };
  await assert.rejects(client.control('disable', installation), /response_invalid/);
});

test('cloud mode cannot invoke local installation controls', () => {
  assert.throws(
    () => createLocalPluginClient({ ...config, mode: 'cloud' }, async () => null),
    /scope_unavailable/,
  );
});

test('selected signed archive bytes are preserved and unsupported extensions rejected', async () => {
  assert.equal(
    await pluginArchiveBase64(new File([Uint8Array.from([1, 2, 3])], 'example.mspkg')),
    'AQID',
  );
  await assert.rejects(
    pluginArchiveBase64(new File(['content'], 'example.pem')),
    /archive_invalid/,
  );
  await assert.rejects(pluginArchiveBase64(new File([], 'example.mspkg')), /archive_invalid/);
});

test('revoked zero-permission installations require new approval before enable', async () => {
  let requests = 0;
  const client = createLocalPluginClient(config, async () => {
    requests += 1;
  });
  assert.throws(
    () =>
      client.control('enable', {
        ...installation,
        enabled: false,
        approved_permissions: [],
        authorization_status: 'revoked',
      }),
    /authorization_required/,
  );
  assert.equal(requests, 0);
});

test('activation telemetry is required and failed packages remain manageable', async () => {
  let item = {
    ...installation,
    activation_status: 'failed',
    activation_error: 'Archive signature invalid',
  };
  const client = createLocalPluginClient(config, async () => ({
    installations: [item],
    trust_configured: false,
  }));
  assert.deepEqual((await client.list()).installations, [item]);
  for (const patch of [
    { activation_status: undefined },
    { activation_status: 'installed' },
    { activation_error: undefined },
    { activation_error: null },
    { activation_error: '' },
    { activation_status: 'active' },
    { enabled: false },
  ]) {
    item = {
      ...installation,
      activation_status: 'failed',
      activation_error: 'Archive signature invalid',
      ...patch,
    };
    await assert.rejects(client.list(), /response_invalid/);
  }
  for (const activation_status of ['pending', 'active', 'inactive']) {
    item = { ...installation, enabled: activation_status !== 'inactive', activation_status };
    assert.deepEqual((await client.list()).installations, [item]);
  }
});
