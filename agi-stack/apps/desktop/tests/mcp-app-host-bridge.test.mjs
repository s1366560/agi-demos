import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const {
  callMCPAppTool,
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

  assert.deepEqual(calls, [
    ['release-dashboard', 'approve_release', { release: '2026.07' }],
  ]);
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
    ['registered', 'registered-dashboard', 'approve_release', { release: '2026.07' }],
  ]);
  assert.equal(result.isError, false);
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
    ['project-selected', 'release-tools', 'approve_release', { release: '2026.07' }],
  ]);
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
    await client.callMCPAppTool('release-dashboard', 'approve_release', { release: '2026.07' });
    await client.callMCPAppToolDirect(
      'project-selected',
      'release-tools',
      'approve_release',
      { release: '2026.07' },
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
          path: '/api/v1/mcp/apps/release-dashboard/tool-call',
          method: 'POST',
          auth: 'Bearer cloud-session',
          body: { tool_name: 'approve_release', arguments: { release: '2026.07' } },
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
