import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const {
  callMCPAppTool,
  createMCPToolCallKeyStore,
  listMCPAppResources,
  mcpAppMessageText,
  readMCPAppResource,
  safeMCPAppExternalUrl,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/mcpAppHostBridge.js');

test('registered MCP App tool calls use the app-scoped proxy and normalize errors', async () => {
  const calls = [];
  const result = await callMCPAppTool(
    {
      callMCPAppTool: async (...args) => {
        calls.push(args);
        return {
          content: [{ type: 'text', text: 'failed safely' }],
          is_error: true,
          error_message: 'tool failed',
        };
      },
    },
    {
      projectId: 'project-cloud',
      appId: 'release-dashboard',
      serverName: 'release-tools',
      originalToolName: 'show_release_dashboard',
    },
    { name: 'approve_release', arguments: { release: '2026.07' } },
  );

  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].slice(0, 3), [
    'release-dashboard',
    'approve_release',
    { release: '2026.07' },
  ]);
  assert.match(calls[0][3], /^desktop-mcp-tool-call:/u);
  assert.deepEqual(result, {
    content: [{ type: 'text', text: 'failed safely' }],
    isError: true,
  });
});

test('synthetic MCP App resolves a registered app before falling back to a direct proxy', async () => {
  const calls = [];
  const client = {
    listMCPApps: async (projectId) => {
      calls.push(['list', projectId]);
      return [
        {
          id: 'registered-dashboard',
          server_name: 'release-tools',
          tool_name: 'approve_release',
        },
      ];
    },
    callMCPAppTool: async (...args) => {
      calls.push(['registered', ...args]);
      return { content: [{ type: 'text', text: 'approved' }], is_error: false };
    },
    callMCPAppToolDirect: async (...args) => {
      calls.push(['direct', ...args]);
      return { content: [], is_error: false };
    },
  };

  const result = await callMCPAppTool(
    client,
    {
      projectId: 'project-cloud',
      appId: '_synthetic_release_dashboard',
      serverName: 'release-tools',
      originalToolName: 'show_release_dashboard',
    },
    { name: 'approve_release', arguments: { release: '2026.07' } },
  );

  assert.deepEqual(calls, [
    ['list', 'project-cloud'],
    [
      'registered',
      'registered-dashboard',
      'approve_release',
      { release: '2026.07' },
      calls[1][4],
    ],
  ]);
  assert.match(calls[1][4], /^desktop-mcp-tool-call:/u);
  assert.equal(result.isError, false);
});

test('MCP App action retries and window restoration reuse one persisted idempotency key', async () => {
  const persisted = new Map();
  const storage = {
    getItem: (key) => persisted.get(key) ?? null,
    setItem: (key, value) => persisted.set(key, value),
    removeItem: (key) => persisted.delete(key),
  };
  let sequence = 0;
  const firstWindowKeys = createMCPToolCallKeyStore(storage, () => `window-key-${++sequence}`);
  const calls = [];
  const client = {
    callMCPAppTool: async (...args) => {
      calls.push(args);
      if (calls.length === 1) throw new TypeError('connection closed after dispatch');
      throw new Error('local_mcp_tool_call_indeterminate');
    },
  };
  const context = {
    projectId: 'project-window-restore',
    appId: 'release-dashboard-window-restore',
    serverName: 'release-tools',
    originalToolName: 'show_release_dashboard',
  };
  const params = {
    name: 'approve_release',
    arguments: { release: '2026.08', target: 'production' },
  };

  await assert.rejects(
    () => callMCPAppTool(client, context, params, firstWindowKeys),
    /connection closed after dispatch/u,
  );
  const restoredWindowKeys = createMCPToolCallKeyStore(
    storage,
    () => `window-key-${++sequence}`,
  );
  await assert.rejects(
    () =>
      callMCPAppTool(
        client,
        context,
        {
          name: 'approve_release',
          arguments: { target: 'production', release: '2026.08' },
        },
        restoredWindowKeys,
      ),
    /local_mcp_tool_call_indeterminate/u,
  );

  assert.equal(calls.length, 2);
  assert.equal(calls[0][3], calls[1][3]);
  assert.equal(calls[0][3], 'desktop-mcp-tool-call:window-key-1');
  assert.equal(
    persisted.size,
    1,
    'an indeterminate dispatch keeps the same permanent replay guard',
  );
});

test('a confirmed MCP tool receipt releases the persisted action key', async () => {
  const persisted = new Map();
  const keyStore = createMCPToolCallKeyStore(
    {
      getItem: (key) => persisted.get(key) ?? null,
      setItem: (key, value) => persisted.set(key, value),
      removeItem: (key) => persisted.delete(key),
    },
    () => 'confirmed-key',
  );
  await callMCPAppTool(
    {
      callMCPAppTool: async () => ({ content: [], is_error: false }),
    },
    {
      projectId: 'project-confirmed',
      appId: 'confirmed-app',
      serverName: 'confirmed-server',
      originalToolName: 'render',
    },
    { name: 'render', arguments: {} },
    keyStore,
  );
  assert.equal(persisted.size, 0);
});

test('synthetic MCP App direct fallback remains scoped to the selected cloud project', async () => {
  const calls = [];
  const result = await callMCPAppTool(
    {
      listMCPApps: async () => [],
      callMCPAppToolDirect: async (...args) => {
        calls.push(args);
        return { content: [{ type: 'text', text: 'approved' }], is_error: false };
      },
    },
    {
      projectId: 'project-selected',
      appId: '_synthetic_release_dashboard',
      serverName: 'release-tools',
      originalToolName: 'show_release_dashboard',
    },
    { name: 'approve_release', arguments: { release: '2026.07' } },
  );

  assert.deepEqual(calls, [
    [
      'project-selected',
      'release-tools',
      'approve_release',
      { release: '2026.07' },
      calls[0][4],
    ],
  ]);
  assert.match(calls[0][4], /^desktop-mcp-tool-call:/u);
  assert.equal(result.isError, false);
});

test('MCP resources use the active project scope and resource names are stable', async () => {
  const calls = [];
  const client = {
    readMCPAppResource: async (...args) => {
      calls.push(['read', ...args]);
      return {
        contents: [
          { uri: 'ui://release/dashboard', mimeType: 'text/html', text: '<p>ready</p>' },
        ],
      };
    },
    listMCPAppResources: async (...args) => {
      calls.push(['list', ...args]);
      return { resources: [{ uri: 'ui://release/dashboard' }] };
    },
  };

  const context = {
    projectId: 'project-selected',
    appId: 'release-dashboard',
    serverName: 'release-tools',
    originalToolName: 'show_release_dashboard',
  };
  const read = await readMCPAppResource(client, context, 'ui://release/dashboard');
  const listed = await listMCPAppResources(client, context);

  assert.equal(read.contents[0].text, '<p>ready</p>');
  assert.deepEqual(listed, {
    resources: [{ uri: 'ui://release/dashboard', name: 'ui://release/dashboard' }],
  });
  assert.deepEqual(calls, [
    ['read', 'project-selected', 'ui://release/dashboard', 'release-tools'],
    ['list', 'project-selected', 'release-tools'],
  ]);
});

test('MCP resource discovery preserves unavailable and protocol errors', async () => {
  const context = {
    projectId: 'project-selected',
    appId: 'release-dashboard',
    serverName: 'release-tools',
    originalToolName: 'show_release_dashboard',
  };

  await assert.rejects(
    () => listMCPAppResources({}, context),
    /MCP App resource proxy is unavailable/u,
  );
  await assert.rejects(
    () =>
      listMCPAppResources(
        {
          listMCPAppResources: async () => {
            throw new Error('malformed MCP response');
          },
        },
        context,
      ),
    /malformed MCP response/u,
  );
});

test('MCP App guest messages extract text and external links fail closed', () => {
  assert.equal(
    mcpAppMessageText({ role: 'user', content: [{ type: 'text', text: 'Deploy release' }] }),
    'Deploy release',
  );
  assert.equal(
    mcpAppMessageText({ role: 'user', content: { type: 'text', text: 'Legacy message' } }),
    'Legacy message',
  );
  assert.equal(safeMCPAppExternalUrl('https://docs.memstack.ai/release'), 'https://docs.memstack.ai/release');
  assert.equal(safeMCPAppExternalUrl('mailto:release@memstack.ai'), 'mailto:release@memstack.ai');
  assert.equal(safeMCPAppExternalUrl('javascript:alert(1)'), null);
  assert.equal(safeMCPAppExternalUrl('/relative'), null);
});

test('Desktop MCP App API methods preserve cloud auth and selected project in every request', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    calls.push({ url, init, body: init.body ? JSON.parse(String(init.body)) : undefined });
    if (url.pathname.endsWith('/mcp/apps')) return Response.json([]);
    if (url.pathname.endsWith('/resources/read')) return Response.json({ contents: [] });
    if (url.pathname.endsWith('/resources/list')) return Response.json({ resources: [] });
    if (url.pathname.endsWith('/credentials/provision')) {
      return Response.json({
        stored: true,
        credential_kind: 'header',
        credential_name: 'authorization',
        duplicate: false,
      });
    }
    if (url.pathname.endsWith('/mcp')) {
      return Response.json({
        id: 'server-1',
        tenant_id: 'tenant-selected',
        project_id: 'project-selected',
        name: 'release-tools',
        server_type: 'http',
        enabled: true,
        runtime_status: 'starting',
      });
    }
    return Response.json({ content: [], is_error: false });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'cloud-session',
      projectId: 'project-selected',
    });
    await client.listMCPApps('project-selected');
    await client.listMCPServers('project-selected');
    const provisioned = await client.provisionMCPServerCredential({
      project_id: 'project-selected',
      server_name: 'release-tools',
      server_type: 'http',
      transport_config: { url: 'https://mcp.memstack.test' },
      credential_kind: 'header',
      credential_name: 'authorization',
      secret: 'Bearer renderer-submitted-secret',
      idempotency_key: 'mcp-credential-action-1',
    });
    assert.equal(provisioned.stored, true);
    assert.equal('secret' in provisioned, false);
    assert.equal('reference' in provisioned, false);
    await client.createMCPServer({
      name: 'release-tools',
      server_type: 'http',
      transport_config: {
        url: 'https://mcp.memstack.test',
        credential_header_names: ['authorization'],
      },
      enabled: true,
      project_id: 'project-selected',
      idempotency_key: 'mcp-create-action-1',
    });
    await client.callMCPAppTool(
      'release-dashboard',
      'approve_release',
      { release: '2026.07' },
      'desktop-mcp-tool-call:registered-1',
    );
    await client.callMCPToolByServerId(
      'release-tools-server-id',
      'approve_release',
      { release: '2026.07' },
      'desktop-mcp-tool-call:server-id-1',
    );
    await client.callMCPAppToolDirect(
      'project-selected',
      'release-tools',
      'approve_release',
      { release: '2026.07' },
      'desktop-mcp-tool-call:direct-1',
    );
    await client.readMCPAppResource(
      'project-selected',
      'ui://release/dashboard',
      'release-tools',
    );
    await client.listMCPAppResources('project-selected', 'release-tools');

    assert.deepEqual(
      calls.map(({ url, init, body }) => ({
        path: `${url.pathname}${url.search}`,
        method: init.method ?? 'GET',
        auth: init.headers.get('Authorization'),
        body,
      })),
      [
        {
          path: '/api/v1/mcp/apps?project_id=project-selected',
          method: 'GET',
          auth: 'Bearer cloud-session',
          body: undefined,
        },
        {
          path: '/api/v1/mcp?project_id=project-selected',
          method: 'GET',
          auth: 'Bearer cloud-session',
          body: undefined,
        },
        {
          path: '/api/v1/mcp/credentials/provision',
          method: 'POST',
          auth: 'Bearer cloud-session',
          body: {
            project_id: 'project-selected',
            server_name: 'release-tools',
            server_type: 'http',
            transport_config: { url: 'https://mcp.memstack.test' },
            credential_kind: 'header',
            credential_name: 'authorization',
            secret: 'Bearer renderer-submitted-secret',
            idempotency_key: 'mcp-credential-action-1',
          },
        },
        {
          path: '/api/v1/mcp',
          method: 'POST',
          auth: 'Bearer cloud-session',
          body: {
            name: 'release-tools',
            server_type: 'http',
            transport_config: {
              url: 'https://mcp.memstack.test',
              credential_header_names: ['authorization'],
            },
            enabled: true,
            project_id: 'project-selected',
            idempotency_key: 'mcp-create-action-1',
          },
        },
        {
          path: '/api/v1/mcp/apps/release-dashboard/tool-call',
          method: 'POST',
          auth: 'Bearer cloud-session',
          body: {
            tool_name: 'approve_release',
            arguments: { release: '2026.07' },
            idempotency_key: 'desktop-mcp-tool-call:registered-1',
          },
        },
        {
          path: '/api/v1/mcp/tools/call',
          method: 'POST',
          auth: 'Bearer cloud-session',
          body: {
            server_id: 'release-tools-server-id',
            tool_name: 'approve_release',
            arguments: { release: '2026.07' },
            idempotency_key: 'desktop-mcp-tool-call:server-id-1',
          },
        },
        {
          path: '/api/v1/mcp/apps/proxy/tool-call',
          method: 'POST',
          auth: 'Bearer cloud-session',
          body: {
            project_id: 'project-selected',
            server_name: 'release-tools',
            tool_name: 'approve_release',
            arguments: { release: '2026.07' },
            idempotency_key: 'desktop-mcp-tool-call:direct-1',
          },
        },
        {
          path: '/api/v1/mcp/apps/resources/read',
          method: 'POST',
          auth: 'Bearer cloud-session',
          body: {
            project_id: 'project-selected',
            server_name: 'release-tools',
            uri: 'ui://release/dashboard',
          },
        },
        {
          path: '/api/v1/mcp/apps/resources/list',
          method: 'POST',
          auth: 'Bearer cloud-session',
          body: { project_id: 'project-selected', server_name: 'release-tools' },
        },
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
