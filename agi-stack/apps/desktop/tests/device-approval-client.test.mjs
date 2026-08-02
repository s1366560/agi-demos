import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  DeviceApprovalError,
  createDeviceApprovalClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/device-approval/deviceApprovalClient.js');

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

test('device approval client sends the exact authenticated Cloud contract', async () => {
  const calls = [];
  const client = createDeviceApprovalClient(cloudConfig, {
    fetch: async (url, init) => {
      calls.push({ url, init });
      return jsonResponse(200, { status: 'approved' });
    },
  });

  const outcome = await client.approve('ABCD2345');
  assert.deepEqual(outcome, { status: 'approved' });
  assert.equal(calls.length, 1);
  assert.equal(
    calls[0].url,
    'https://cloud.example.test/api/v1/auth/device/approve',
  );
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer cloud-session');
  assert.equal(calls[0].init.headers.get('Content-Type'), 'application/json');
  assert.equal(calls[0].init.body, '{"user_code":"ABCD2345"}');
});

test('device approval client fails closed for Local authority and malformed success', async () => {
  let fetchCalls = 0;
  const localClient = createDeviceApprovalClient(
    { ...cloudConfig, mode: 'local', apiKey: '', localApiToken: 'local-token' },
    {
      fetch: async () => {
        fetchCalls += 1;
        return jsonResponse(200, { status: 'approved' });
      },
    },
  );
  await assert.rejects(
    localClient.approve('ABCD2345'),
    (error) =>
      error instanceof DeviceApprovalError &&
      error.reasonCode === 'local_cloud_device_approval_not_applicable',
  );
  assert.equal(fetchCalls, 0);

  const malformedClient = createDeviceApprovalClient(cloudConfig, {
    fetch: async () => jsonResponse(200, { status: 'approved', token: 'never' }),
  });
  await assert.rejects(
    malformedClient.approve('ABCD2345'),
    (error) =>
      error instanceof DeviceApprovalError &&
      error.reasonCode === 'device_approval_contract_invalid',
  );
});

test('device approval client maps protocol status without message heuristics', async () => {
  for (const [status, reasonCode] of [
    [400, 'device_approval_request_invalid'],
    [401, 'device_approval_authentication_required'],
    [403, 'device_approval_forbidden'],
    [404, 'device_approval_code_unknown'],
    [409, 'device_approval_code_already_handled'],
    [410, 'device_approval_code_expired'],
    [503, 'device_approval_authority_busy'],
    [500, 'device_approval_request_failed'],
  ]) {
    const client = createDeviceApprovalClient(cloudConfig, {
      fetch: async () => jsonResponse(status, { detail: 'translated text' }),
    });
    await assert.rejects(
      client.approve('ABCD2345'),
      (error) =>
        error instanceof DeviceApprovalError &&
        error.status === status &&
        error.reasonCode === reasonCode,
    );
  }
});

function jsonResponse(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
