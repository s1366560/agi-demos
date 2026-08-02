import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  createRuntimeDeploymentsClient,
  RuntimeDeploymentsUnavailableError,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-deployments/runtimeDeploymentsClient.js'
);

function runtimeConfig(mode, overrides = {}) {
  return {
    mode,
    apiBaseUrl: 'https://api.example.test',
    deviceAuthorizationBaseUrl: 'https://api.example.test',
    apiKey: 'cloud-token',
    localApiToken: 'local-token',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function response(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function deploy(overrides = {}) {
  return {
    id: 'deploy-1',
    instance_id: 'instance-1',
    action: 'update',
    revision: 7,
    status: 'running',
    message: null,
    image_version: 'v1.2.3',
    replicas: 3,
    config_snapshot: { region: 'west' },
    triggered_by: 'user-1',
    started_at: '2026-08-02T08:00:00Z',
    finished_at: null,
    created_at: '2026-08-02T07:59:00Z',
    credentials_encrypted: 'must-not-cross-renderer',
    ...overrides,
  };
}

test('Cloud Runtime Deployments projects the backend list and detail contract', async () => {
  const calls = [];
  const client = createRuntimeDeploymentsClient(runtimeConfig('cloud'), {
    fetch: async (input, init) => {
      calls.push({ url: String(input), init });
      if (String(input).endsWith('/deploys/deploy-1')) {
        return response(deploy({ status: 'success', finished_at: '2026-08-02T08:02:00Z' }));
      }
      return response({
        deploys: [deploy()],
        total: 1,
        page: 2,
        page_size: 10,
      });
    },
  });
  const scope = {
    authority: 'cloud',
    tenantId: 'tenant-1',
    instanceId: 'instance-1',
  };
  const page = await client.list(scope, { page: 2, pageSize: 10 });
  assert.deepEqual(page.deployments[0], {
    id: 'deploy-1',
    instanceId: 'instance-1',
    action: 'update',
    revision: 7,
    status: 'running',
    imageVersion: 'v1.2.3',
    replicas: 3,
    startedAt: '2026-08-02T08:00:00Z',
    finishedAt: null,
    createdAt: '2026-08-02T07:59:00Z',
  });
  assert.equal(JSON.stringify(page).includes('credentials_encrypted'), false);
  assert.equal(JSON.stringify(page).includes('config_snapshot'), false);
  assert.equal(JSON.stringify(page).includes('region'), false);
  assert.equal(JSON.stringify(page).includes('user-1'), false);
  assert.match(
    calls[0].url,
    /deploys\/\?instance_id=instance-1&page=2&page_size=10$/u,
  );
  assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer cloud-token');

  const detail = await client.get(scope, 'deploy-1');
  assert.equal(detail.status, 'success');
  assert.equal(detail.finishedAt, '2026-08-02T08:02:00Z');
});

test('Cloud Runtime Deployments parses chunked SSE status and done events', async () => {
  const events = [];
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('data: {"type":"status","status":"running",'));
      controller.enqueue(encoder.encode('"deploy_id":"deploy-1"}\r\n\r\n: keepalive\n\n'));
      controller.enqueue(encoder.encode('data: {"type":"done","status":"success"}\n\n'));
      controller.close();
    },
  });
  const client = createRuntimeDeploymentsClient(runtimeConfig('cloud'), {
    fetch: async () =>
      new Response(body, {
        headers: { 'content-type': 'text/event-stream' },
      }),
  });
  await client.streamProgress(
    {
      authority: 'cloud',
      tenantId: 'tenant-1',
      instanceId: 'instance-1',
    },
    'deploy-1',
    (event) => events.push(event),
  );
  assert.deepEqual(events, [
    { type: 'status', status: 'running', deployId: 'deploy-1' },
    { type: 'done', status: 'success', deployId: null },
  ]);
});

test('Cloud Runtime Deployments treats non-terminal SSE EOF as disconnected', async () => {
  const client = createRuntimeDeploymentsClient(runtimeConfig('cloud'), {
    fetch: async () =>
      new Response('data: {"type":"status","status":"running"}\n\n', {
        headers: { 'content-type': 'text/event-stream' },
      }),
  });
  await assert.rejects(
    () =>
      client.streamProgress(
        {
          authority: 'cloud',
          tenantId: 'tenant-1',
          instanceId: 'instance-1',
        },
        'deploy-1',
        () => {},
      ),
    (error) =>
      error instanceof RuntimeDeploymentsUnavailableError &&
      error.reasonCode === 'runtime_deployments_progress_disconnected',
  );
});

test('Runtime Deployments requires instance scope and never calls Local network', async () => {
  let fetchCalls = 0;
  const cloud = createRuntimeDeploymentsClient(runtimeConfig('cloud'), {
    fetch: async () => {
      fetchCalls += 1;
      return response({});
    },
  });
  await assert.rejects(
    () =>
      cloud.list({
        authority: 'cloud',
        tenantId: 'tenant-1',
        instanceId: null,
      }),
    (error) =>
      error instanceof RuntimeDeploymentsUnavailableError &&
      error.reasonCode === 'runtime_deployments_instance_scope_required',
  );

  const local = createRuntimeDeploymentsClient(runtimeConfig('local'), {
    fetch: async () => {
      fetchCalls += 1;
      return response({});
    },
  });
  await assert.rejects(
    () =>
      local.list({
        authority: 'local',
        tenantId: 'tenant-1',
        instanceId: 'instance-1',
      }),
    (error) =>
      error instanceof RuntimeDeploymentsUnavailableError &&
      error.reasonCode === 'cloud_deployment_authority_not_applicable',
  );
  assert.equal(fetchCalls, 0);
});
