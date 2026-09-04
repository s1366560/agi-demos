import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { createDesktopRuntimeDeploymentsHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimeDeploymentsHttpProjectionV2.js',
);
const { RuntimeDeploymentsUnavailableError } = require(
  COMPILED_ROOT + '/src/features/runtime-deployments/runtimeDeploymentsContract.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function config(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'session',
    localApiToken: 'launch',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

const scope = (authority = 'cloud', instanceId = 'instance-1') => ({
  authority,
  tenantId: 'tenant-1',
  instanceId,
});

function rawDeployment(overrides = {}) {
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

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function byteLength(value) {
  return new TextEncoder().encode(value).byteLength;
}

test('Cloud authority projects safe JSON and exact query paths', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (String(input).endsWith('/deploys/deploy-1')) {
      return jsonResponse(rawDeployment({ status: 'success' }));
    }
    return jsonResponse({ deploys: [rawDeployment()], total: 1, page: 2, page_size: 10 });
  };
  try {
    const authority = createDesktopRuntimeDeploymentsHttpAuthorityV2(config(), scope());
    const page = await authority.list({ page: 2, pageSize: 10 });
    const detail = await authority.get('deploy-1');
    assert.equal(JSON.stringify(page).includes('credentials_encrypted'), false);
    assert.equal(JSON.stringify(page).includes('config_snapshot'), false);
    assert.equal(JSON.stringify(page).includes('triggered_by'), false);
    assert.equal(detail.status, 'success');
    assert.match(
      calls[0].input,
      /deploys\/\?instance_id=instance-1&page=2&page_size=10$/u,
    );
    assert.match(calls[1].input, /deploys\/deploy-1$/u);
    for (const { init } of calls) {
      assert.equal(init.headers.get('Authorization'), 'Bearer session');
      assert.equal(init.headers.get('Accept'), 'application/json');
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Cloud authority rejects malformed JSON and scope-crossing records', async () => {
  const originalFetch = globalThis.fetch;
  const payloads = [
    new Response('not-json', { headers: { 'content-type': 'text/plain' } }),
    jsonResponse({ deploys: [rawDeployment({ instance_id: 'other-instance' })], total: 1, page: 1, page_size: 10 }),
    jsonResponse(rawDeployment({ status: 'unknown' })),
  ];
  globalThis.fetch = async () => payloads.shift();
  try {
    const authority = createDesktopRuntimeDeploymentsHttpAuthorityV2(config(), scope());
    await assert.rejects(authority.list({ page: 1, pageSize: 10 }), /runtime_deployments_contract_invalid/u);
    await assert.rejects(authority.list({ page: 1, pageSize: 10 }), /runtime_deployments_contract_invalid/u);
    await assert.rejects(authority.get('deploy-1'), /runtime_deployments_contract_invalid/u);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Cloud SSE validates chunks, ignores malformed frames and cancels after done', async () => {
  const originalFetch = globalThis.fetch;
  const encoder = new TextEncoder();
  let cancelled = 0;
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('data: not-json\n\n'));
      controller.enqueue(encoder.encode('data: {"type":"status","status":"running",'));
      controller.enqueue(encoder.encode('"deploy_id":"deploy-1"}\r\n\r\n'));
      controller.enqueue(encoder.encode('data: {"type":"done","status":"success"}\n\n'));
    },
    cancel() {
      cancelled += 1;
    },
  });
  globalThis.fetch = async (_input, init) => {
    assert.equal(init.headers.get('Accept'), 'text/event-stream');
    return new Response(body, { headers: { 'content-type': 'text/event-stream' } });
  };
  try {
    const events = [];
    const authority = createDesktopRuntimeDeploymentsHttpAuthorityV2(config(), scope());
    await authority.streamProgress('deploy-1', (event) => events.push(event));
    assert.deepEqual(events, [
      { type: 'status', status: 'running', deployId: 'deploy-1' },
      { type: 'done', status: 'success', deployId: null },
    ]);
    assert.equal(cancelled, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Cloud SSE cancels on abort and callback failure without replacing primary errors', async () => {
  const originalFetch = globalThis.fetch;
  const encoder = new TextEncoder();
  let cancellations = 0;
  globalThis.fetch = async () =>
    new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('data: {"type":"status","status":"running"}\n\n'));
        },
        cancel() {
          cancellations += 1;
          throw new Error('cancel-cleanup-failure');
        },
      }),
      { headers: { 'content-type': 'text/event-stream' } },
    );
  try {
    const authority = createDesktopRuntimeDeploymentsHttpAuthorityV2(config(), scope());
    const callbackFailure = new Error('callback-primary');
    await assert.rejects(
      authority.streamProgress('deploy-1', async () => { throw callbackFailure; }),
      callbackFailure,
    );

    const controller = new AbortController();
    await authority.streamProgress('deploy-1', () => controller.abort(), controller.signal);
    assert.equal(cancellations, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Cloud SSE rejects non-stream responses and non-terminal disconnects', async () => {
  const originalFetch = globalThis.fetch;
  const responses = [
    new Response('{}', { headers: { 'content-type': 'application/json' } }),
    new Response('data: {"type":"status","status":"running"}\n\n', {
      headers: { 'content-type': 'text/event-stream' },
    }),
  ];
  globalThis.fetch = async () => responses.shift();
  try {
    const authority = createDesktopRuntimeDeploymentsHttpAuthorityV2(config(), scope());
    await assert.rejects(
      authority.streamProgress('deploy-1', () => {}),
      /runtime_deployments_contract_invalid/u,
    );
    await assert.rejects(
      authority.streamProgress('deploy-1', () => {}),
      /runtime_deployments_progress_disconnected/u,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Cloud SSE enforces the two MiB cap for direct authenticated transport', async () => {
  const originalFetch = globalThis.fetch;
  let cancelled = 0;
  globalThis.fetch = async () =>
    new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array(2 * 1024 * 1024 + 1));
        },
        cancel() {
          cancelled += 1;
        },
      }),
      { headers: { 'content-type': 'text/event-stream' } },
    );
  try {
    const authority = createDesktopRuntimeDeploymentsHttpAuthorityV2(config(), scope());
    await assert.rejects(
      authority.streamProgress('deploy-1', () => {}),
      /runtime_deployments_contract_invalid/u,
    );
    assert.equal(cancelled, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('vault-bound Cloud transport carries exact paths and a two MiB SSE cap', async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async () => assert.fail('credential-free Cloud must use vault broker');
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          assert.equal(command, 'cloud_request');
          requests.push(args.request);
          if (args.request.path.endsWith('/progress')) {
            const text = 'data: {"type":"done","status":"success"}\n\n';
            return {
              status: 200,
              body: {
                kind: 'event-stream',
                text,
                size_bytes: byteLength(text),
                mime_type: 'text/event-stream',
              },
            };
          }
          if (args.request.path.endsWith('/deploy-1')) {
            return { status: 200, body: rawDeployment() };
          }
          return {
            status: 200,
            body: { deploys: [rawDeployment()], total: 1, page: 1, page_size: 10 },
          };
        },
      },
    },
  };
  try {
    const authority = createDesktopRuntimeDeploymentsHttpAuthorityV2(
      config({ apiKey: '' }),
      scope(),
    );
    await authority.list({ page: 1, pageSize: 10 });
    await authority.get('deploy-1');
    await authority.streamProgress('deploy-1', () => {});
    assert.deepEqual(requests.map(({ path }) => path), [
      '/api/v1/deploys/?instance_id=instance-1&page=1&page_size=10',
      '/api/v1/deploys/deploy-1',
      '/api/v1/deploys/deploy-1/progress',
    ]);
    assert.deepEqual(requests[2].response, {
      kind: 'event-stream',
      max_bytes: 2 * 1024 * 1024,
    });
    assert.equal(JSON.stringify(requests).includes('session'), false);
  } finally {
    globalThis.window = originalWindow;
    globalThis.fetch = originalFetch;
  }
});

test('Local authority performs zero network or native transport and probes not-applicable', async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  let transports = 0;
  globalThis.fetch = async () => {
    transports += 1;
    throw new Error('network forbidden');
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke() {
          transports += 1;
          throw new Error('native transport forbidden');
        },
      },
    },
  };
  try {
    const localScope = scope('local');
    const authority = createDesktopRuntimeDeploymentsHttpAuthorityV2(
      config({ mode: 'local' }),
      localScope,
    );
    for (const operation of [
      () => authority.list({ page: 1, pageSize: 10 }),
      () => authority.get('deploy-1'),
      () => authority.streamProgress('deploy-1', () => {}),
    ]) {
      await assert.rejects(
        operation,
        (error) =>
          error instanceof RuntimeDeploymentsUnavailableError &&
          error.reasonCode === 'cloud_deployment_authority_not_applicable',
      );
    }
    const result = await authority.probe();
    assert.deepEqual(result, {
      availability: 'not_applicable',
      reason_code: 'cloud_deployment_authority_not_applicable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: {
        tenant_id: 'tenant-1',
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: null,
    });
    assert.equal(transports, 0);
  } finally {
    globalThis.window = originalWindow;
    globalThis.fetch = originalFetch;
  }
});
