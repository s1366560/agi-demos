import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import Module, { createRequire } from 'node:module';
import { test } from 'node:test';

process.env.NODE_PATH = new URL('../node_modules', import.meta.url).pathname;
Module._initPaths();

const require = createRequire(import.meta.url);
const compiledRoot = '/tmp/agistack-desktop-test-dist/src';
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require(`${compiledRoot}/i18n.js`);
const { BackendStoresPage } = require(
  `${compiledRoot}/features/backend-stores/BackendStoresPage.js`,
);
const { BACKEND_STORES_ROUTE_ID, createBackendStoresClient } = require(
  `${compiledRoot}/features/backend-stores/backendStoresClient.js`,
);
const { createBackendStoresController } = require(
  `${compiledRoot}/features/backend-stores/backendStoresController.js`,
);
const { createBackendStoresRouteModuleLoader } = require(
  `${compiledRoot}/features/backend-stores/backendStoresRouteModule.js`,
);
const { PROJECT_PLAYBOOKS_ROUTE_ID, createProjectPlaybooksClient } = require(
  `${compiledRoot}/features/project-playbooks/projectPlaybooksClient.js`,
);
const { createProjectPlaybooksController } = require(
  `${compiledRoot}/features/project-playbooks/projectPlaybooksController.js`,
);
const { createCloudProjectPlaybooksEventSource, createProjectPlaybooksEventSource } = require(
  `${compiledRoot}/features/project-playbooks/projectPlaybooksEventSource.js`,
);
const { createProjectPlaybooksRouteModuleLoader } = require(
  `${compiledRoot}/features/project-playbooks/projectPlaybooksRouteModule.js`,
);
const { DESKTOP_PRODUCTION_ROUTE_IDS, createDesktopProductionRouteRegistry } = require(
  `${compiledRoot}/features/navigation/desktopProductionRouteRegistry.js`,
);
const {
  CloudRequestExecutionRegistry,
  executeVaultBoundCloudRequest,
} = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const {
  authorizeVaultBoundCloudSocket,
} = require('/tmp/agistack-desktop-test-dist/electron/main/cloudSocketPolicy.js');
const {
  desktopApiAuthenticationAvailable,
  desktopApiFetch,
  desktopVaultBoundCloudRequestBroker,
} = require(`${compiledRoot}/api/cloudRequestBroker.js`);

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: '',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
});
const playbooksRouteSource = readFileSync(
  new URL('../src/features/project-playbooks/projectPlaybooksRouteModule.tsx', import.meta.url),
  'utf8',
);
const appRouteRegistrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);
const localConfig = Object.freeze({
  ...cloudConfig,
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'http://127.0.0.1:43117',
  apiKey: '',
  localApiToken: 'private-launch',
  mode: 'local',
});
const tenantScope = Object.freeze({ authority: 'cloud', tenantId: 'tenant-1' });
const projectScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});

test('W4 production registry exposes scoped Backend Stores and Project Playbooks routes', () => {
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {},
  });
  const backendStores = registry.byId.get(BACKEND_STORES_ROUTE_ID);
  const playbooks = registry.byId.get(PROJECT_PLAYBOOKS_ROUTE_ID);

  assert.equal(DESKTOP_PRODUCTION_ROUTE_IDS.includes(BACKEND_STORES_ROUTE_ID), true);
  assert.equal(DESKTOP_PRODUCTION_ROUTE_IDS.includes(PROJECT_PLAYBOOKS_ROUTE_ID), true);
  assert.deepEqual(
    {
      path: backendStores.path,
      scope: backendStores.scope,
      permissions: backendStores.requiredPermission,
      localPolicy: backendStores.localPolicy,
    },
    {
      path: '/tenant/:tenantId/backend-stores',
      scope: ['tenant'],
      permissions: [['authenticated', 'tenant_member']],
      localPolicy: 'cloud_only',
    },
  );
  assert.deepEqual(
    {
      path: playbooks.path,
      scope: playbooks.scope,
      permissions: playbooks.requiredPermission,
      localPolicy: playbooks.localPolicy,
    },
    {
      path: '/tenant/:tenantId/project/:projectId/playbooks',
      scope: ['tenant', 'project'],
      permissions: [['authenticated', 'tenant_member']],
      localPolicy: 'cloud_only',
    },
  );
});

test('Electron vault-bound broker allowlists W4 endpoints, verifies observed scope, and hides credentials', async () => {
  const requests = [];
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/graph-stores?tenant_id=tenant-1',
      method: 'GET',
    },
    {
      async loadTrustedSession() {
        return {
          version: 1,
          api_base_url: 'https://cloud.memstack.test',
          runtime_mode: 'cloud',
          credential_kind: 'cloud_bearer',
          credential: 'vault-only-token',
          expires_at: null,
        };
      },
      async fetch(url, init) {
        requests.push({ url, init });
        const target = new URL(url);
        if (target.pathname === '/api/v1/workspace-context') {
          return jsonResponse({
            context: {
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              revision: 5,
            },
          });
        }
        return jsonResponse({ success: true, data: [] });
      },
    },
  );
  assert.deepEqual(result, { status: 200, body: { success: true, data: [] } });
  assert.equal(requests.length, 2);
  assert.equal(
    new Headers(requests[0].init.headers).get('Authorization'),
    'Bearer vault-only-token',
  );
  assert.equal(JSON.stringify(result).includes('vault-only-token'), false);

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/auth/oauth/github/callback',
        method: 'POST',
        body: { code: 'must-never-enter-renderer' },
      },
      {
        async loadTrustedSession() {
          throw new Error('must reject before vault access');
        },
        async fetch() {
          throw new Error('must reject before network');
        },
      },
    ),
    /cloud request endpoint is not allowed/u,
  );
});

test('Electron vault-bound broker strictly allowlists the identity observation endpoint', async () => {
  const requests = [];
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/auth/me',
      method: 'GET',
    },
    cloudRequestDependencies((url, init) => {
      requests.push({ url, init });
      const target = new URL(url);
      if (target.pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            revision: 5,
          },
        });
      }
      return jsonResponse({ user_id: 'user-1', roles: [] });
    }),
  );

  assert.deepEqual(result, {
    status: 200,
    body: { user_id: 'user-1', roles: [] },
  });
  assert.equal(requests.length, 2);
  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/auth/me?include=credentials',
        method: 'GET',
      },
      {
        async loadTrustedSession() {
          throw new Error('identity query must reject before vault access');
        },
        async fetch() {
          throw new Error('identity query must reject before network access');
        },
      },
    ),
    /cloud request endpoint is not allowed/u,
  );
  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/auth/me',
        method: 'POST',
        body: {},
      },
      {
        async loadTrustedSession() {
          throw new Error('identity mutation must reject before vault access');
        },
        async fetch() {
          throw new Error('identity mutation must reject before network access');
        },
      },
    ),
    /cloud request endpoint is not allowed/u,
  );
});

test('Electron vault-bound broker admits only observed tenant/project/workspace HTTP scopes', async () => {
  const requests = [];
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/messages',
      method: 'POST',
      body: {
        content: 'hello',
        sender_type: 'human',
        mentions: [],
        context_items: [],
      },
    },
    cloudRequestDependencies((url, init) => {
      requests.push({ url, init });
      const target = new URL(url);
      if (target.pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: 'workspace-1',
            revision: 5,
          },
        });
      }
      return jsonResponse({ id: 'message-1', workspace_id: 'workspace-1' }, 201);
    }),
  );

  assert.deepEqual(result, {
    status: 201,
    body: { id: 'message-1', workspace_id: 'workspace-1' },
  });
  assert.equal(requests.length, 2);

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/tenants/tenant-1/projects/project-other/workspaces?limit=500&offset=0',
        method: 'GET',
      },
      cloudRequestDependencies((url) => {
        if (new URL(url).pathname === '/api/v1/workspace-context') {
          return jsonResponse({
            context: {
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              workspace_id: 'workspace-1',
              revision: 5,
            },
          });
        }
        throw new Error('cross-project request must reject before target network access');
      }),
    ),
    /cloud request project scope mismatch/u,
  );
});

test('Electron vault-bound broker allowlists exact project cohorts and rejects arbitrary project actions', async () => {
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/projects/project-1/my-work',
      method: 'GET',
    },
    cloudRequestDependencies((url) => {
      const target = new URL(url);
      if (target.pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: null,
            revision: 5,
          },
        });
      }
      return jsonResponse({ items: [] });
    }),
  );
  assert.deepEqual(result, { status: 200, body: { items: [] } });

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/projects/project-1/admin/raw-sql',
        method: 'POST',
        body: { query: 'not allowed' },
      },
      {
        async loadTrustedSession() {
          throw new Error('unknown project action must reject before vault access');
        },
        async fetch() {
          throw new Error('unknown project action must reject before network access');
        },
      },
    ),
    /cloud request endpoint is not allowed/u,
  );
});

test('Electron vault-bound broker accepts exact identity catalogs and rejects query expansion', async () => {
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/projects?page=1&page_size=100&tenant_id=tenant-1',
      method: 'GET',
    },
    cloudRequestDependencies((url) => {
      const target = new URL(url);
      if (target.pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: null,
            revision: 5,
          },
        });
      }
      return jsonResponse({ projects: [], total: 0, page: 1, page_size: 100 });
    }),
  );
  assert.equal(result.status, 200);

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/projects?page=1&page_size=100&tenant_id=tenant-1&include_secrets=true',
        method: 'GET',
      },
      {
        async loadTrustedSession() {
          throw new Error('expanded query must reject before vault access');
        },
        async fetch() {
          throw new Error('expanded query must reject before network access');
        },
      },
    ),
    /cloud request endpoint is not allowed/u,
  );
});

test('Electron vault-bound broker scopes Agent HTTP cohorts by the observed project', async () => {
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/agent/conversations/conversation-1/messages?project_id=project-1&limit=50',
      method: 'GET',
    },
    cloudRequestDependencies((url) => {
      const target = new URL(url);
      if (target.pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: 'workspace-1',
            revision: 5,
          },
        });
      }
      return jsonResponse({ items: [] });
    }),
  );
  assert.equal(result.status, 200);

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/agent/conversations/conversation-1/messages?project_id=project-other&limit=50',
        method: 'GET',
      },
      cloudRequestDependencies((url) => {
        if (new URL(url).pathname === '/api/v1/workspace-context') {
          return jsonResponse({
            context: {
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              workspace_id: 'workspace-1',
              revision: 5,
            },
          });
        }
        throw new Error('cross-project Agent request must not reach the target');
      }),
    ),
    /cloud request project scope mismatch/u,
  );
});

test('Electron vault-bound broker permits exact workspace projections but no arbitrary workspace tail', async () => {
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/workspaces/workspace-1/tasks',
      method: 'GET',
    },
    cloudRequestDependencies((url) => {
      const target = new URL(url);
      if (target.pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: 'workspace-1',
            revision: 5,
          },
        });
      }
      return jsonResponse({ tasks: [] });
    }),
  );
  assert.equal(result.status, 200);

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/workspaces/workspace-1/raw-database',
        method: 'GET',
      },
      {
        async loadTrustedSession() {
          throw new Error('unknown workspace action must reject before vault access');
        },
        async fetch() {
          throw new Error('unknown workspace action must reject before network access');
        },
      },
    ),
    /cloud request endpoint is not allowed/u,
  );
});

test('Electron cloud broker stops oversized streams before buffering the full response', async () => {
  let deliveredChunks = 0;
  let streamCancelled = false;
  const oversizedBody = new ReadableStream({
    pull(controller) {
      deliveredChunks += 1;
      controller.enqueue(new Uint8Array(256 * 1024).fill(0x61));
      if (deliveredChunks >= 32) controller.close();
    },
    cancel() {
      streamCancelled = true;
    },
  });

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/graph-stores?tenant_id=tenant-1',
        method: 'GET',
      },
      cloudRequestDependencies((url) => {
        const target = new URL(url);
        if (target.pathname === '/api/v1/workspace-context') {
          return jsonResponse({
            context: {
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              revision: 5,
            },
          });
        }
        return new Response(oversizedBody, {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }),
    ),
    /cloud response is too large/u,
  );

  assert.equal(streamCancelled, true);
  assert.ok(deliveredChunks <= 10, `stream delivered ${deliveredChunks} chunks before rejection`);
});

test('Electron cloud broker rejects responses that reflect the vault credential', async () => {
  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/graph-stores?tenant_id=tenant-1',
        method: 'GET',
      },
      cloudRequestDependencies((url) => {
        const target = new URL(url);
        if (target.pathname === '/api/v1/workspace-context') {
          return jsonResponse({
            context: {
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              revision: 5,
            },
          });
        }
        return jsonResponse({ detail: 'vault-only-token' });
      }),
    ),
    /cloud response contains protected credential/u,
  );
});

test('cloud request execution leases are owner-bound, cancellable, and released', () => {
  const registry = new CloudRequestExecutionRegistry({ timeoutMs: 30_000 });
  const lease = registry.begin(7, 'request_1234567890');

  assert.equal(lease.signal.aborted, false);
  assert.equal(registry.cancel(8, 'request_1234567890'), false);
  assert.equal(registry.cancel(7, 'request_1234567890'), true);
  assert.equal(lease.signal.aborted, true);
  lease.release();
  assert.equal(registry.cancel(7, 'request_1234567890'), false);
});

test('cloud request execution leases abort at the privileged-process deadline', async () => {
  const registry = new CloudRequestExecutionRegistry({ timeoutMs: 5 });
  const lease = registry.begin(7, 'request_timeout_1234');
  await new Promise((resolve) => lease.signal.addEventListener('abort', resolve, { once: true }));

  assert.equal(lease.signal.aborted, true);
  assert.match(String(lease.signal.reason), /cloud request timed out/u);
  assert.equal(registry.cancel(7, 'request_timeout_1234'), false);
  lease.release();
});

test('renderer cloud broker propagates AbortSignal through an owner-scoped cancel command', async () => {
  const originalWindow = globalThis.window;
  const commands = [];
  let resolveRequest;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        invoke(command, args) {
          commands.push({ command, args });
          if (command === 'cloud_request') {
            return new Promise((resolve) => {
              resolveRequest = resolve;
            });
          }
          return Promise.resolve({ cancelled: true });
        },
      },
    },
  };

  try {
    const broker = desktopVaultBoundCloudRequestBroker();
    assert.ok(broker);
    const controller = new AbortController();
    const pending = broker.requestJson({
      path: '/api/v1/workspace-context',
      signal: controller.signal,
    });
    await new Promise((resolve) => setImmediate(resolve));
    controller.abort();

    await assert.rejects(pending, { name: 'AbortError' });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(commands[0].command, 'cloud_request');
    assert.equal(commands[1].command, 'cloud_request_cancel');
    assert.equal(commands[0].args.requestId, commands[1].args.requestId);
    assert.match(commands[0].args.requestId, /^[A-Za-z0-9_-]{16,128}$/u);
    resolveRequest({ status: 200, body: { ignored: true } });
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('shared desktop fetch adapter preserves mutation authority while keeping Cloud credentials privileged', async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          commands.push({ command, args });
          return { status: 200, body: { revision: 8 } };
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('vault-only Cloud adapter must not use renderer fetch');
  };

  try {
    assert.equal(desktopApiAuthenticationAvailable(cloudConfig), true);
    const response = await desktopApiFetch(
      cloudConfig,
      '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agent-policy',
      {
        method: 'PATCH',
        headers: new Headers({
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-Expected-Revision': '7',
          'Idempotency-Key': 'mutation_1234567890', // gitleaks:allow -- deterministic fixture
        }),
        body: JSON.stringify({ expected_revision: 7, capability_mode: 'work' }),
        credentials: 'omit',
      },
    );
    assert.deepEqual(await response.json(), { revision: 8 });
    assert.deepEqual(commands[0].args.request, {
      path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agent-policy',
      method: 'PATCH',
      body: { expected_revision: 7, capability_mode: 'work' },
      mutation: {
        expected_revision: 7,
        idempotency_key: 'mutation_1234567890', // gitleaks:allow -- deterministic fixture
      },
    });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('shared desktop fetch adapter serializes bounded FormData without renderer credentials', async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          commands.push({ command, args });
          return { status: 201, body: { uploaded: true } };
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('vault-only Cloud FormData must not use renderer fetch');
  };

  try {
    const form = new FormData();
    form.append('file', new Blob(['hello'], { type: 'text/plain' }), 'guide.txt');
    form.append('parent_path', '/docs');
    const response = await desktopApiFetch(
      cloudConfig,
      '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration/mutations/files/upload',
      { method: 'POST', body: form },
    );
    assert.deepEqual(await response.json(), { uploaded: true });
    assert.deepEqual(commands[0].args.request, {
      path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration/mutations/files/upload',
      method: 'POST',
      form: [
        {
          kind: 'file',
          name: 'file',
          filename: 'guide.txt',
          mime_type: 'text/plain',
          bytes_base64: 'aGVsbG8=',
        },
        { kind: 'text', name: 'parent_path', value: '/docs' },
      ],
    });

    const oversized = new FormData();
    oversized.append(
      'file',
      new Blob([new Uint8Array(512 * 1024 + 1)], {
        type: 'application/octet-stream',
      }),
      'oversized.bin',
    );
    await assert.rejects(
      desktopApiFetch(
        cloudConfig,
        '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration/mutations/files/upload',
        { method: 'POST', body: oversized },
      ),
      /cloud_request_body_too_large/u,
    );
    assert.equal(commands.length, 1);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('Electron Cloud FormData contract rejects invalid filename and MIME before vault access', async () => {
  const dependencies = {
    async loadTrustedSession() {
      throw new Error('invalid FormData must reject before vault access');
    },
    async fetch() {
      throw new Error('invalid FormData must reject before network access');
    },
  };
  const base = {
    path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration/mutations/files/upload',
    method: 'POST',
  };
  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        ...base,
        form: [
          {
            kind: 'file',
            name: 'file',
            filename: '../secret.txt',
            mime_type: 'text/plain',
            bytes_base64: 'aGVsbG8=',
          },
        ],
      },
      dependencies,
    ),
    /cloud request filename is invalid/u,
  );
  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        ...base,
        form: [
          {
            kind: 'file',
            name: 'file',
            filename: 'safe.txt',
            mime_type: 'text plain',
            bytes_base64: 'aGVsbG8=',
          },
        ],
      },
      dependencies,
    ),
    /cloud request MIME type is invalid/u,
  );
});

test('privileged Cloud binary responses are endpoint-bound, size-capped, and reconstructed safely', async () => {
  const requests = [];
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/artifacts/artifact-1/content/bytes',
      method: 'GET',
      response: { kind: 'binary', max_bytes: 64 },
    },
    cloudRequestDependencies((url, init) => {
      requests.push({ url, init });
      if (new URL(url).pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: null,
            revision: 5,
          },
        });
      }
      return new Response(Uint8Array.from([0, 1, 2, 3]), {
        status: 200,
        headers: {
          'Content-Type': 'image/png',
          'Content-Disposition': 'attachment; filename="plot.png"',
        },
      });
    }),
  );
  assert.equal(requests.length, 2);
  assert.deepEqual(result, {
    status: 200,
    body: {
      kind: 'binary',
      bytes_base64: 'AAECAw==',
      size_bytes: 4,
      mime_type: 'image/png',
      filename: 'plot.png',
    },
  });

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/workspace-context',
        method: 'GET',
        response: { kind: 'binary', max_bytes: 64 },
      },
      cloudRequestDependencies(() => jsonResponse({})),
    ),
    /cloud request endpoint is not allowed/u,
  );
});

test('shared desktop fetch adapter reconstructs only exact privileged binary envelopes', async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          commands.push({ command, args });
          return {
            status: 200,
            body: {
              kind: 'binary',
              bytes_base64: 'AAECAw==',
              size_bytes: 4,
              mime_type: 'image/png',
              filename: 'plot.png',
            },
          };
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('vault-only Cloud binary requests must not use renderer fetch');
  };
  try {
    const response = await desktopApiFetch(
      cloudConfig,
      '/api/v1/artifacts/artifact-1/content/bytes',
      { method: 'GET' },
      { responseType: 'binary', maxBytes: 64 },
    );
    assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [0, 1, 2, 3]);
    assert.equal(response.headers.get('content-type'), 'image/png');
    assert.equal(response.headers.get('content-disposition'), 'attachment; filename="plot.png"');
    assert.deepEqual(commands[0].args.request.response, {
      kind: 'binary',
      max_bytes: 64,
    });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('privileged deployment progress remains credential-free through a bounded event-stream envelope', async () => {
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/deploys/deploy-1/progress',
      method: 'GET',
      response: { kind: 'event-stream', max_bytes: 65_536 },
    },
    cloudRequestDependencies((url) => {
      if (new URL(url).pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: null,
            revision: 5,
          },
        });
      }
      return new Response('data: {"status":"running"}\n\n', {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }),
  );
  assert.deepEqual(result, {
    status: 200,
    body: {
      kind: 'event-stream',
      text: 'data: {"status":"running"}\n\n',
      size_bytes: 28,
      mime_type: 'text/event-stream',
    },
  });

  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke() {
          return result;
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('vault-only event streams must not use renderer fetch');
  };
  try {
    const response = await desktopApiFetch(
      cloudConfig,
      '/api/v1/deploys/deploy-1/progress',
      { method: 'GET' },
      { responseType: 'event-stream', maxBytes: 65_536 },
    );
    assert.equal(response.headers.get('content-type'), 'text/event-stream');
    assert.equal(await response.text(), 'data: {"status":"running"}\n\n');
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('privileged event streams reject endpoint, MIME, size, secret, and renderer-envelope drift', async () => {
  const withoutVault = {
    async loadTrustedSession() {
      throw new Error('invalid event-stream requests must reject before vault access');
    },
    async fetch() {
      throw new Error('invalid event-stream requests must reject before network access');
    },
  };
  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/tasks/recent',
        method: 'GET',
        response: { kind: 'event-stream', max_bytes: 64 },
      },
      withoutVault,
    ),
    /cloud request endpoint is not allowed/u,
  );

  for (const [body, headers, maxBytes, expected] of [
    ['data: {}\n\n', { 'Content-Type': 'application/json' }, 64, /MIME type is invalid/u],
    [
      'data: {"token":"vault-only-token"}\n\n',
      { 'Content-Type': 'text/event-stream' },
      64,
      /protected credential/u,
    ],
    ['data: {"status":"running"}\n\n', { 'Content-Type': 'text/event-stream' }, 16, /too large/u],
  ]) {
    await assert.rejects(
      executeVaultBoundCloudRequest(
        {
          path: '/api/v1/deploys/deploy-1/progress',
          method: 'GET',
          response: { kind: 'event-stream', max_bytes: maxBytes },
        },
        cloudRequestDependencies((url) => {
          if (new URL(url).pathname === '/api/v1/workspace-context') {
            return jsonResponse({
              context: {
                tenant_id: 'tenant-1',
                project_id: 'project-1',
                workspace_id: null,
                revision: 5,
              },
            });
          }
          return new Response(body, { headers });
        }),
      ),
      expected,
    );
  }

  const originalWindow = globalThis.window;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke() {
          return {
            status: 200,
            body: {
              kind: 'event-stream',
              text: 'data: {}\n\n',
              size_bytes: 10,
              mime_type: 'text/event-stream',
              credential: 'must-not-cross',
            },
          };
        },
      },
    },
  };
  try {
    await assert.rejects(
      desktopApiFetch(
        cloudConfig,
        '/api/v1/deploys/deploy-1/progress',
        { method: 'GET' },
        { responseType: 'event-stream', maxBytes: 64 },
      ),
      /cloud_event_stream_response_contract_invalid/u,
    );
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('privileged Cloud fetch forwards only validated revision and idempotency headers', async () => {
  const calls = [];
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agent-policy',
      method: 'PATCH',
      body: { expected_revision: 7, capability_mode: 'work' },
      mutation: {
        expected_revision: 7,
        idempotency_key: 'mutation_1234567890', // gitleaks:allow -- deterministic fixture
      },
    },
    cloudRequestDependencies((url, init) => {
      calls.push({ url, init });
      if (new URL(url).pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: 'workspace-1',
            revision: 5,
          },
        });
      }
      return jsonResponse({ revision: 8 });
    }),
  );
  assert.equal(result.status, 200);
  const headers = new Headers(calls[1].init.headers);
  assert.equal(headers.get('X-Expected-Revision'), '7');
  assert.equal(headers.get('Idempotency-Key'), 'mutation_1234567890');

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agent-policy',
        method: 'PATCH',
        body: { expected_revision: 7 },
        mutation: { expected_revision: -1, idempotency_key: 'bad' },
      },
      {
        async loadTrustedSession() {
          throw new Error('invalid mutation must reject before vault access');
        },
        async fetch() {
          throw new Error('invalid mutation must reject before network access');
        },
      },
    ),
    /cloud request mutation is invalid/u,
  );
});

test('shared desktop fetch adapter preserves idempotency-only mutation authority', async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          commands.push({ command, args });
          return { status: 201, body: { id: 'project-2' } };
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('vault-only Cloud adapter must not use renderer fetch');
  };

  try {
    const response = await desktopApiFetch(cloudConfig, '/api/v1/projects/', {
      method: 'POST',
      headers: new Headers({
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'Idempotency-Key': 'project-create-12345678',
      }),
      body: JSON.stringify({ tenant_id: 'tenant-1', name: 'Project 2' }),
    });
    assert.deepEqual(await response.json(), { id: 'project-2' });
    assert.deepEqual(commands[0].args.request.mutation, {
      kind: 'idempotency-only',
      idempotency_key: 'project-create-12345678',
    });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('privileged Cloud fetch never fabricates a revision for idempotency-only mutations', async () => {
  const calls = [];
  const result = await executeVaultBoundCloudRequest(
    {
      path: '/api/v1/projects/',
      method: 'POST',
      body: { tenant_id: 'tenant-1', name: 'Project 2' },
      mutation: {
        kind: 'idempotency-only',
        idempotency_key: 'project-create-12345678',
      },
    },
    cloudRequestDependencies((url, init) => {
      calls.push({ url, init });
      if (new URL(url).pathname === '/api/v1/workspace-context') {
        return jsonResponse({
          context: {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: null,
            revision: 5,
          },
        });
      }
      return jsonResponse({ id: 'project-2' }, 201);
    }),
  );
  assert.equal(result.status, 201);
  const headers = new Headers(calls[1].init.headers);
  assert.equal(headers.has('X-Expected-Revision'), false);
  assert.equal(headers.get('Idempotency-Key'), 'project-create-12345678');

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/projects/',
        method: 'POST',
        body: { tenant_id: 'tenant-1', name: 'Project 2' },
        mutation: {
          kind: 'idempotency-only',
          expected_revision: 0,
          idempotency_key: 'project-create-12345678',
        },
      },
      {
        async loadTrustedSession() {
          throw new Error('invalid mutation must reject before vault access');
        },
        async fetch() {
          throw new Error('invalid mutation must reject before network access');
        },
      },
    ),
    /cloud request mutation is invalid/u,
  );
});

test('Electron broker admits exact remaining custom-client cohorts and rejects query expansion', async () => {
  const requests = [
    {
      path: '/api/v1/auth/device/approve',
      method: 'POST',
      body: { user_code: 'ABCD-EFGH' },
    },
    {
      path: '/api/v1/invitations/accept/invitation-token',
      method: 'POST',
      body: {},
    },
    {
      path: '/api/v1/tenants/',
      method: 'POST',
      body: { name: 'Tenant', slug: 'tenant', plan: 'free' },
    },
    { path: '/api/v1/instance-templates/?page=1&page_size=20', method: 'GET' },
    {
      path: '/api/v1/instance-templates/',
      method: 'POST',
      body: { tenant_id: 'tenant-1', name: 'Template', slug: 'template' },
    },
    { path: '/api/v1/instance-templates/template-1', method: 'GET' },
    { path: '/api/v1/instance-templates/template-1/items', method: 'GET' },
    { path: '/api/v1/instance-templates/template-1/publish', method: 'POST' },
    {
      path: '/api/v1/instance-templates/template-1/clone',
      method: 'POST',
      body: { new_name: 'Template copy' },
    },
    { path: '/api/v1/instance-templates/template-1', method: 'DELETE' },
    { path: '/api/v1/clusters/?page=1&page_size=20', method: 'GET' },
    { path: '/api/v1/clusters/cluster-1/health', method: 'GET' },
    {
      path: '/api/v1/deploys/?instance_id=instance-1&page=1&page_size=10',
      method: 'GET',
    },
    { path: '/api/v1/deploys/deploy-1', method: 'GET' },
    {
      path: '/api/v1/instances/?page=1&page_size=20&status=running',
      method: 'GET',
    },
    { path: '/api/v1/instances/instance-1/restart', method: 'POST' },
    { path: '/api/v1/instances/instance-1', method: 'DELETE' },
    { path: '/api/v1/projects/sandboxes?limit=100&offset=0', method: 'GET' },
    { path: '/api/v1/projects/project-1/sandbox/stats', method: 'GET' },
    {
      path: '/api/v1/skills/evolution/overview?tenant_id=tenant-1',
      method: 'GET',
    },
    {
      path: '/api/v1/skills/evolution/config?tenant_id=tenant-1',
      method: 'GET',
    },
    {
      path: '/api/v1/skills/evolution/config?tenant_id=tenant-1',
      method: 'PUT',
      body: { enabled: true },
    },
    { path: '/api/v1/skills/evolution/run?tenant_id=tenant-1', method: 'POST' },
    {
      path: '/api/v1/skills/evolution/jobs/job-1/apply?tenant_id=tenant-1',
      method: 'POST',
    },
    { path: '/api/v1/users/me', method: 'PUT', body: { name: 'Admin' } },
    {
      path: '/api/v1/auth/force-change-password',
      method: 'POST',
      body: { old_password: 'old', new_password: 'new' },
    },
    {
      path: '/api/v1/channels/tenants/tenant-1/plugins/channel-catalog',
      method: 'GET',
    },
    {
      path: '/api/v1/channels/tenants/tenant-1/plugins/channel-catalog/slack/schema',
      method: 'GET',
    },
    { path: '/api/v1/channels/projects/project-1/configs', method: 'GET' },
    {
      path: '/api/v1/channels/projects/project-1/configs',
      method: 'POST',
      body: { channel_type: 'slack' },
    },
    {
      path: '/api/v1/channels/configs/config-1',
      method: 'PUT',
      body: { enabled: true },
    },
    { path: '/api/v1/channels/configs/config-1/test', method: 'POST' },
    { path: '/api/v1/channels/configs/config-1', method: 'DELETE' },
    {
      path: '/api/v1/subagents/templates/list?tenant_id=tenant-1&limit=12&offset=0&category=ops&query=agent',
      method: 'GET',
    },
    {
      path: '/api/v1/subagents/templates/categories?tenant_id=tenant-1',
      method: 'GET',
    },
    {
      path: '/api/v1/subagents/templates/template-1?tenant_id=tenant-1',
      method: 'GET',
    },
    {
      path: '/api/v1/subagents/templates/template-1/install?tenant_id=tenant-1',
      method: 'POST',
    },
    {
      path: '/api/v1/subagents/templates/seed?tenant_id=tenant-1',
      method: 'POST',
    },
    { path: '/api/v1/tenants/tenant-1/stats', method: 'GET' },
    { path: '/api/v1/tenants/tenant-1/analytics?period=30d', method: 'GET' },
    { path: '/api/v1/tasks/stats', method: 'GET' },
    { path: '/api/v1/tasks/queue-depth', method: 'GET' },
    {
      path: '/api/v1/tasks/recent?limit=50&offset=0&status=running',
      method: 'GET',
    },
    { path: '/api/v1/tasks/task-1/retry', method: 'POST' },
    { path: '/api/v1/tasks/retry-pending?limit=10', method: 'POST' },
    { path: '/api/v1/agent/bindings?tenant_id=tenant-1', method: 'GET' },
    { path: '/api/v1/agent/config?tenant_id=tenant-1', method: 'GET' },
    {
      path: '/api/v1/agent/config?tenant_id=tenant-1&expected_revision=3',
      method: 'PUT',
      body: { max_iterations: 12 },
    },
    {
      path: '/api/v1/agent/trace/runs/tenant/tenant-1?limit=20',
      method: 'GET',
    },
    {
      path: '/api/v1/agent/trace/runs/tenant/tenant-1/active/count',
      method: 'GET',
    },
    { path: '/api/v1/system/info', method: 'GET' },
    { path: '/api/v1/search-enhanced/capabilities', method: 'GET' },
    {
      path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration/capabilities',
      method: 'GET',
    },
    {
      path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration/authority',
      method: 'GET',
    },
    {
      path: '/api/v1/admin/pool/status?scope=tenant&tenant_id=tenant-1',
      method: 'GET',
    },
    {
      path: '/api/v1/admin/pool/instances/instance-1/pause?scope=tenant&tenant_id=tenant-1',
      method: 'POST',
    },
    { path: '/api/v1/admin/dlq/messages?limit=50&offset=0', method: 'GET' },
    { path: '/api/v1/admin/dlq/messages/message-1/retry', method: 'POST' },
    {
      path: '/api/v1/admin/dlq/cleanup/expired?older_than_hours=24',
      method: 'POST',
    },
    { path: '/api/v1/projects/project-1/sandbox/capabilities', method: 'GET' },
    {
      path: '/api/v1/projects/project-1/sandbox/desktop/session?resolution=1600x900',
      method: 'POST',
    },
    {
      path: '/api/v1/projects/project-1/sandbox/terminal/sessions',
      method: 'POST',
      body: { run_id: 'run-1', expected_run_revision: 3 },
    },
    {
      path: '/api/v1/projects/project-1/sandbox/terminal/sessions/session-1/resume',
      method: 'POST',
      body: { resume_token: 'resume-1' },
    },
    {
      path: '/api/v1/projects/project-1/cron-jobs/job-1/run',
      method: 'POST',
      body: { expected_revision: 3, idempotency_key: 'run-key-12345678' },
    },
    { path: '/api/v1/tenants/tenant-1/billing', method: 'GET' },
    {
      path: '/api/v1/tenants/tenant-1/invitations?limit=50&offset=0',
      method: 'GET',
    },
    {
      path: '/api/v1/tenants/tenant-1/trust/policies?workspace_id=workspace-1',
      method: 'GET',
    },
    {
      path: '/api/v1/tenants/tenant-1/audit-logs/filter?limit=20&offset=0&actor=user-1',
      method: 'GET',
    },
    { path: '/api/v1/acp/tenants/tenant-1/status', method: 'GET' },
    {
      path: '/api/v1/events?tenant_id=tenant-1&page=1&page_size=20',
      method: 'GET',
    },
    { path: '/api/v1/tenant-webhooks/tenant-1', method: 'GET' },
    {
      path: '/api/v1/agent/workflows/patterns?tenant_id=tenant-1&page=1&page_size=50',
      method: 'GET',
    },
    {
      path: '/api/v1/genes/?tenant_id=tenant-1&page=1&page_size=20',
      method: 'GET',
    },
  ];

  for (const request of requests) {
    const result = await executeVaultBoundCloudRequest(
      request,
      cloudRequestDependencies((url) => {
        if (new URL(url).pathname === '/api/v1/workspace-context') {
          return jsonResponse({
            context: {
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              workspace_id: 'workspace-1',
              revision: 5,
            },
          });
        }
        return jsonResponse({ ok: true });
      }),
    );
    assert.equal(result.status, 200, request.path);
  }

  await assert.rejects(
    executeVaultBoundCloudRequest(
      {
        path: '/api/v1/admin/pool/status?scope=tenant&tenant_id=tenant-1&target=https%3A%2F%2Fevil.test',
        method: 'GET',
      },
      {
        async loadTrustedSession() {
          throw new Error('expanded query must reject before vault access');
        },
        async fetch() {
          throw new Error('expanded query must reject before network access');
        },
      },
    ),
    /cloud request endpoint is not allowed/u,
  );
});

test('Backend Stores loads both planes through a secret-free vault-bound broker contract', async () => {
  const requests = [];
  const broker = recordingBroker(requests, async (request) => {
    const target = new URL(request.path, 'https://cloud.memstack.test');
    if (target.pathname === '/api/v1/workspace-context') {
      return {
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 8,
        },
        membership_role: 'admin',
      };
    }
    if (target.pathname.endsWith('/types')) {
      return {
        success: true,
        data: [
          {
            type: target.pathname.includes('graph') ? 'neo4j' : 'memstack_pgvector',
            display_name: 'Default',
            connection_fields: [],
            index_fields: [],
          },
        ],
      };
    }
    return {
      success: true,
      data: [storePayload(target.pathname.includes('graph') ? 'graph-1' : 'retrieval-1')],
    };
  });
  const snapshot = await createBackendStoresClient(cloudConfig, broker).load(tenantScope);
  assert.equal(snapshot.scopeRevision, 8);
  assert.equal(snapshot.membershipRole, 'admin');
  assert.deepEqual(
    snapshot.graph.stores.map((store) => store.id),
    ['graph-1'],
  );
  assert.deepEqual(
    snapshot.retrieval.stores.map((store) => store.id),
    ['retrieval-1'],
  );
  assert.equal(snapshot.allowedActions.includes('create'), true);

  assert.equal(requests.length, 5);
  for (const request of requests) {
    const target = new URL(request.path, 'https://cloud.memstack.test');
    assert.equal(Object.hasOwn(request, 'headers'), false);
    if (!target.pathname.endsWith('/types') && target.pathname !== '/api/v1/workspace-context') {
      assert.equal(target.searchParams.get('tenant_id'), 'tenant-1');
    }
  }
});

test('Backend Stores rejects masked secrets before mutations and fails closed in Local', async () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    throw new Error('network must not be reached');
  };
  try {
    const cloud = createBackendStoresClient(cloudConfig);
    await assert.rejects(
      cloud.update(tenantScope, 'graph', 'graph-1', {
        connectionConfig: { password: '***' },
      }),
      (error) => error.payload.reason_code === 'backend_stores_masked_secret_rejected',
    );
    await assert.rejects(
      createBackendStoresClient(localConfig).load({
        authority: 'local',
        tenantId: 'tenant-1',
      }),
      (error) =>
        error.status === 503 &&
        error.payload.reason_code === 'local_backend_stores_cloud_authority_unavailable',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(fetchCalls, 0);
});

test('Backend Stores uses Cloud authority from Local-online through the vault broker', async () => {
  const requests = [];
  const broker = recordingBroker(requests, async (request) => {
    const target = new URL(request.path, 'https://cloud.memstack.test');
    if (target.pathname === '/api/v1/workspace-context') {
      return {
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 13,
        },
        membership_role: 'admin',
      };
    }
    if (target.pathname.endsWith('/types')) return { success: true, data: [] };
    return { success: true, data: [] };
  });

  const snapshot = await createBackendStoresClient(localConfig, broker).load(tenantScope);

  assert.equal(snapshot.authority, 'cloud');
  assert.equal(snapshot.scopeRevision, 13);
  assert.equal(snapshot.allowedActions.includes('create'), true);
  assert.equal(requests.length, 5);
});

test('Backend Stores renders mutation controls only for explicitly allowed actions', () => {
  const mutationCalls = [];
  const controller = {
    async create() {
      mutationCalls.push('create');
    },
    async update() {
      mutationCalls.push('update');
    },
    async remove() {
      mutationCalls.push('delete');
    },
    async testDraft() {
      mutationCalls.push('test-draft');
      return { success: true, version: null };
    },
    async testStore() {
      mutationCalls.push('test-store');
      return { success: true, version: null };
    },
  };
  const memberMarkup = renderBackendStores(
    backendStoresViewModel(['view', 'list'], 'tenant_member'),
    controller,
  );

  assert.match(memberMarkup, />graph-1</u);
  assert.doesNotMatch(memberMarkup, />Create backend store</u);
  assert.doesNotMatch(memberMarkup, />Test configuration</u);
  assert.doesNotMatch(memberMarkup, />Test</u);
  assert.doesNotMatch(memberMarkup, />Edit</u);
  assert.doesNotMatch(memberMarkup, />Delete</u);
  assert.deepEqual(mutationCalls, []);

  const adminMarkup = renderBackendStores(
    backendStoresViewModel(['view', 'list', 'create', 'update', 'delete', 'test'], 'admin'),
    controller,
  );
  assert.match(adminMarkup, />Create backend store</u);
  assert.match(adminMarkup, />Test configuration</u);
  assert.match(adminMarkup, />Test</u);
  assert.match(adminMarkup, />Edit</u);
  assert.match(adminMarkup, />Delete</u);
  assert.deepEqual(mutationCalls, []);
});

test('Backend Stores controller aborts stale scope loads and exposes CRUD/test actions', async () => {
  const deferred = [];
  const client = {
    load(scope, options) {
      return new Promise((resolve) => deferred.push({ scope, signal: options.signal, resolve }));
    },
    async create() {},
    async update() {},
    async remove() {},
    async testDraft() {
      return { success: true, version: '5.26' };
    },
    async testStore() {
      return { success: true, version: '5.26' };
    },
  };
  const controller = createBackendStoresController({
    client,
    initialScope: tenantScope,
  });
  const first = controller.load(tenantScope);
  const nextScope = Object.freeze({ authority: 'cloud', tenantId: 'tenant-2' });
  const second = controller.load(nextScope);
  assert.equal(deferred[0].signal.aborted, true);
  deferred[0].resolve(backendSnapshot('tenant-1'));
  deferred[1].resolve(backendSnapshot('tenant-2'));
  await Promise.all([first, second]);
  assert.equal(controller.getSnapshot().scope.tenantId, 'tenant-2');
  assert.equal(controller.getSnapshot().state, 'empty');
  assert.deepEqual(controller.getSnapshot().allowedActions, [
    'view',
    'list',
    'create',
    'update',
    'delete',
    'test',
  ]);
  controller.stop();
});

test('Project Playbooks validates project scope and parses playbooks plus verdicts', async () => {
  const requests = [];
  const broker = recordingBroker(requests, async (request) => {
    const target = new URL(request.path, 'https://cloud.memstack.test');
    if (target.pathname === '/api/v1/workspace-context') {
      return {
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 12,
        },
      };
    }
    if (target.pathname.endsWith('/reflection-verdicts')) {
      return {
        items: [
          {
            id: 'verdict-1',
            project_id: 'project-1',
            action: 'create',
            playbook_id: 'playbook-1',
            rationale: 'Observed repeated recovery path',
            proposed_payload: null,
            created_at: '2026-08-10T00:00:00Z',
          },
        ],
      };
    }
    return {
      items: [
        {
          id: 'playbook-1',
          project_id: 'project-1',
          name: 'Recover runtime',
          status: 'active',
          trigger: {
            description: 'Runtime drift',
            friction_kinds: [],
            lane_transitions: [],
          },
          steps: [{ order: 1, instruction: 'Inspect authority', rationale: null }],
          hit_count: 3,
          last_used_at: null,
          created_at: '2026-08-09T00:00:00Z',
          updated_at: '2026-08-10T00:00:00Z',
        },
      ],
    };
  });
  const snapshot = await createProjectPlaybooksClient(cloudConfig, broker).load(projectScope);
  assert.equal(snapshot.scopeRevision, 12);
  assert.equal(snapshot.playbooks[0].name, 'Recover runtime');
  assert.equal(snapshot.verdicts[0].action, 'create');
  assert.deepEqual(snapshot.allowedActions, ['view', 'list', 'refresh', 'review-verdicts']);
  assert.equal(requests.length, 3);
  for (const request of requests.slice(1)) {
    const target = new URL(request.path, 'https://cloud.memstack.test');
    assert.equal(target.searchParams.get('limit'), '200');
  }
});

test('Project Playbooks fails closed in Local and ignores stale project responses', async () => {
  const localClient = createProjectPlaybooksClient(localConfig);
  await assert.rejects(
    localClient.load({
      authority: 'local',
      tenantId: 'tenant-1',
      projectId: 'project-1',
    }),
    (error) =>
      error.status === 503 &&
      error.payload.reason_code === 'local_project_playbooks_cloud_authority_unavailable',
  );

  const deferred = [];
  const controller = createProjectPlaybooksController({
    authority: 'cloud',
    client: {
      load(scope, options) {
        return new Promise((resolve) => deferred.push({ scope, signal: options.signal, resolve }));
      },
    },
    initialScope: projectScope,
  });
  const first = controller.load(projectScope);
  const secondScope = Object.freeze({
    ...projectScope,
    projectId: 'project-2',
  });
  const second = controller.load(secondScope);
  assert.equal(deferred[0].signal.aborted, true);
  deferred[0].resolve(playbooksSnapshot('project-1'));
  deferred[1].resolve(playbooksSnapshot('project-2'));
  await Promise.all([first, second]);
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');
  assert.equal(controller.getSnapshot().state, 'empty');
  controller.stop();
});

test('Project Playbooks refresh events are project-scoped and unsubscribe cleanly', () => {
  const sent = [];
  let closed = 0;
  let observed = 0;
  const socket = {
    readyState: 0,
    onopen: null,
    onmessage: null,
    onerror: null,
    onclose: null,
    send(payload) {
      sent.push(JSON.parse(payload));
    },
    close() {
      closed += 1;
      this.readyState = 3;
    },
  };
  const source = createProjectPlaybooksEventSource({
    openSocket(scope) {
      assert.deepEqual(scope, projectScope);
      return socket;
    },
  });
  const unsubscribe = source.subscribe(projectScope, () => {
    observed += 1;
  });

  socket.readyState = 1;
  socket.onopen();
  assert.deepEqual(sent, [{ type: 'subscribe_project_events', project_id: 'project-1' }]);
  socket.onmessage({
    data: JSON.stringify({
      type: 'reflection_complete',
      project_id: 'project-2',
    }),
  });
  socket.onmessage({
    data: JSON.stringify({
      type: 'workspace_updated',
      project_id: 'project-1',
    }),
  });
  socket.onmessage({
    data: JSON.stringify({
      type: 'reflection_complete',
      project_id: 'project-1',
    }),
  });
  assert.equal(observed, 1);

  unsubscribe();
  assert.deepEqual(sent.at(-1), {
    type: 'unsubscribe_project_events',
    project_id: 'project-1',
  });
  assert.equal(closed, 1);
  socket.onmessage?.({
    data: JSON.stringify({
      type: 'reflection_complete',
      project_id: 'project-1',
    }),
  });
  assert.equal(observed, 1);
});

test('Project Playbooks Local-online event source uses the trusted Cloud origin and cleans up', async () => {
  const opened = [];
  const sent = [];
  const closed = [];
  let transportListener = null;
  let refreshes = 0;
  let projectionLoads = 0;
  const transport = {
    subscribe(listener) {
      transportListener = listener;
      return () => {
        transportListener = null;
      };
    },
    async open(input) {
      opened.push(input);
      await authorizeVaultBoundCloudSocket(input.request, cloudSocketDependencies());
      queueMicrotask(() => {
        transportListener?.({
          socketId: input.socketId,
          type: 'open',
          protocol: 'memstack.auth',
        });
      });
    },
    async send(input) {
      sent.push({ ...input, frame: { ...input.frame } });
    },
    async close(input) {
      closed.push(input);
      queueMicrotask(() => {
        transportListener?.({
          socketId: input.socketId,
          type: 'close',
          code: input.code,
          reason: input.reason,
          wasClean: true,
        });
      });
    },
  };
  const source = createCloudProjectPlaybooksEventSource(localConfig, {
    projectionClient: {
      async load(signal) {
        projectionLoads += 1;
        assert.equal(signal.aborted, false);
        return { apiBaseUrl: 'https://cloud.memstack.test' };
      },
    },
    transport: () => transport,
    sessionId: () => 'playbooks_cloud_session_1',
  });
  const unsubscribe = source.subscribe(projectScope, () => {
    refreshes += 1;
  });

  await waitFor(() => sent.length === 1);
  assert.equal(projectionLoads, 1);
  assert.equal(opened.length, 1);
  assert.equal(new URL(opened[0].request.url).origin, 'wss://cloud.memstack.test');
  assert.notEqual(new URL(opened[0].request.url).origin, 'ws://127.0.0.1:43117');
  assert.deepEqual(opened[0].request.scope, {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: null,
    conversation_id: null,
  });
  assert.deepEqual(JSON.parse(sent[0].frame.text), {
    type: 'subscribe_project_events',
    project_id: 'project-1',
  });

  transportListener({
    socketId: opened[0].socketId,
    type: 'message',
    frame: {
      binary: false,
      text: JSON.stringify({
        type: 'reflection_complete',
        project_id: 'project-1',
      }),
    },
  });
  assert.equal(refreshes, 1);

  unsubscribe();
  await waitFor(() => closed.length === 1);
  assert.deepEqual(JSON.parse(sent.at(-1).frame.text), {
    type: 'unsubscribe_project_events',
    project_id: 'project-1',
  });
  assert.equal(closed[0].reason, 'project_playbooks_unsubscribe');
});

test('Project Playbooks event cleanup aborts a pending trusted-session projection', async () => {
  let projectionSignal = null;
  let socketOpens = 0;
  const source = createCloudProjectPlaybooksEventSource(localConfig, {
    projectionClient: {
      load(signal) {
        projectionSignal = signal;
        return new Promise(() => {});
      },
    },
    transport: () => ({
      subscribe() {
        return () => {};
      },
      async open() {
        socketOpens += 1;
      },
      async send() {},
      async close() {},
    }),
    sessionId: () => 'playbooks_cloud_session_2',
  });

  const unsubscribe = source.subscribe(projectScope, () => {});
  await waitFor(() => projectionSignal !== null);
  unsubscribe();

  assert.equal(projectionSignal.aborted, true);
  assert.equal(socketOpens, 0);
});

test('Project Playbooks route binds reflection refresh and native Cloud socket cleanup', () => {
  assert.match(playbooksRouteSource, /binding\.events\.subscribe\(binding\.scope/u);
  assert.match(playbooksRouteSource, /binding\.controller\.retry\(\)/u);
  assert.match(playbooksRouteSource, /unsubscribe\(\)[\s\S]*binding\.controller\.stop\(\)/u);
  assert.match(appRouteRegistrySource, /createCloudProjectPlaybooksEventSource\(currentConfig\)/u);
});

test('Project Playbooks uses Cloud authority from Local-online through the vault broker', async () => {
  const requests = [];
  const broker = recordingBroker(requests, async (request) => {
    const target = new URL(request.path, 'https://cloud.memstack.test');
    if (target.pathname === '/api/v1/workspace-context') {
      return {
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 14,
        },
      };
    }
    return { items: [] };
  });

  const snapshot = await createProjectPlaybooksClient(localConfig, broker).load(projectScope);

  assert.equal(snapshot.authority, 'cloud');
  assert.equal(snapshot.scopeRevision, 14);
  assert.equal(requests.length, 3);
});

test('W4 route modules keep stable identity and native content ownership', async () => {
  const backend = await createBackendStoresRouteModuleLoader({
    createBinding: () => ({
      controller: createBackendStoresController({
        client: stubBackendClient(),
        initialScope: tenantScope,
      }),
      scope: tenantScope,
    }),
  })();
  const playbooks = await createProjectPlaybooksRouteModuleLoader({
    createBinding: () => ({
      controller: createProjectPlaybooksController({
        authority: 'cloud',
        client: {
          async load() {
            return playbooksSnapshot('project-1');
          },
        },
        initialScope: projectScope,
      }),
      events: createProjectPlaybooksEventSource({
        openSocket() {
          throw new Error('event socket must not open while loading the route module');
        },
      }),
      scope: projectScope,
    }),
  })();
  assert.deepEqual(
    [backend, playbooks].map(({ routeId, capability, disposition, contentPolicy }) => ({
      routeId,
      capability,
      disposition,
      contentPolicy,
    })),
    [
      {
        routeId: 'backend-stores',
        capability: 'backend-stores',
        disposition: 'implemented',
        contentPolicy: 'route_content',
      },
      {
        routeId: 'project-playbooks',
        capability: 'project-playbooks',
        disposition: 'implemented',
        contentPolicy: 'route_content',
      },
    ],
  );
});

function storePayload(id) {
  return {
    id,
    tenant_id: 'tenant-1',
    name: id,
    engine_type: id.startsWith('graph') ? 'neo4j' : 'memstack_pgvector',
    status: 'ready',
    health_status: null,
    detected_version: null,
    connection_config: {},
    index_config: {},
    created_at: null,
    updated_at: null,
    source: 'user',
    readonly: false,
  };
}

function renderBackendStores(model, controller) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(BackendStoresPage, {
        model,
        controller,
        onRetry() {},
      }),
    ),
  );
}

function backendStoresViewModel(allowedActions, membershipRole) {
  return Object.freeze({
    routeId: 'backend-stores',
    state: 'ready',
    scope: tenantScope,
    reasonCode: null,
    retryVisible: true,
    busyAction: null,
    allowedActions: Object.freeze([...allowedActions]),
    membershipRole,
    graph: Object.freeze({
      stores: Object.freeze([
        Object.freeze({
          id: 'graph-1',
          tenantId: 'tenant-1',
          name: 'graph-1',
          engineType: 'neo4j',
          status: 'ready',
          healthStatus: null,
          detectedVersion: '5.26',
          connectionConfig: Object.freeze({}),
          indexConfig: Object.freeze({}),
          createdAt: null,
          updatedAt: null,
          source: 'user',
          readonly: false,
        }),
      ]),
      types: Object.freeze([]),
    }),
    retrieval: Object.freeze({
      stores: Object.freeze([]),
      types: Object.freeze([]),
    }),
  });
}

function cloudSocketDependencies() {
  return {
    async loadTrustedSession() {
      return {
        version: 1,
        api_base_url: 'https://cloud.memstack.test',
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: 'vault-only-token',
        expires_at: null,
      };
    },
    async fetch(url, init) {
      assert.equal(url, 'https://cloud.memstack.test/api/v1/workspace-context');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer vault-only-token');
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          workspace_id: null,
        },
      });
    },
  };
}

async function waitFor(predicate) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error('condition_not_reached');
}

function backendSnapshot(tenantId) {
  const scope = Object.freeze({ authority: 'cloud', tenantId });
  const data = Object.freeze({
    scopeRevision: 1,
    membershipRole: 'admin',
    graph: Object.freeze({
      stores: Object.freeze([]),
      types: Object.freeze([]),
    }),
    retrieval: Object.freeze({
      stores: Object.freeze([]),
      types: Object.freeze([]),
    }),
  });
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: Object.freeze(['view', 'list', 'create', 'update', 'delete', 'test']),
    data,
    ...data,
  });
}

function playbooksSnapshot(projectId) {
  const scope = Object.freeze({ ...projectScope, projectId });
  return Object.freeze({
    scope,
    scopeRevision: 1,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    allowedActions: Object.freeze(['view', 'list', 'refresh', 'review-verdicts']),
    playbooks: Object.freeze([]),
    verdicts: Object.freeze([]),
  });
}

function stubBackendClient() {
  return {
    async load() {
      return backendSnapshot('tenant-1');
    },
    async create() {},
    async update() {},
    async remove() {},
    async testDraft() {
      return { success: true, version: null };
    },
    async testStore() {
      return { success: true, version: null };
    },
  };
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function cloudRequestDependencies(fetch) {
  return {
    async loadTrustedSession() {
      return {
        version: 1,
        api_base_url: 'https://cloud.memstack.test',
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: 'vault-only-token',
        expires_at: null,
      };
    },
    fetch,
  };
}

function recordingBroker(requests, handler) {
  return Object.freeze({
    async requestJson(request) {
      requests.push({
        path: request.path,
        method: request.method ?? 'GET',
        ...(request.body === undefined ? {} : { body: request.body }),
      });
      return handler(request);
    },
    async requestNoContent(request) {
      requests.push({
        path: request.path,
        method: request.method ?? 'GET',
        ...(request.body === undefined ? {} : { body: request.body }),
      });
      await handler(request);
    },
  });
}
