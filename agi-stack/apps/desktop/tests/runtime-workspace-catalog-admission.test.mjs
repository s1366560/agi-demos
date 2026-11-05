import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiled = '/tmp/agistack-desktop-test-dist/apps/desktop';
const { DesktopApiClient, DesktopApiError } = require(`${compiled}/src/api/client.js`);
const { selectRuntimeWorkspaceAfterCatalog, workspaceCatalogFailureAllowsUnboundRuntime } = require(
  `${compiled}/src/features/workspace/runtimeWorkspaceCatalogAdmission.js`,
);

test('real HTTP missing workspace catalog remains an error while unbound chat catalog works', async () => {
  const paths = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url, 'http://localhost');
    paths.push(url.pathname);
    response.setHeader('Content-Type', 'application/json');
    if (url.pathname.endsWith('/workspaces')) {
      response.writeHead(404).end(JSON.stringify({ detail: 'Not a preview host' }));
    } else if (url.pathname === '/api/v1/agent/conversations') {
      assert.equal(url.searchParams.get('unbound_only'), 'true');
      assert.equal(url.searchParams.has('workspace_id'), false);
      response.end(
        JSON.stringify({
          items: [],
          total: 0,
          has_more: false,
          next_offset: null,
          limit: Number(url.searchParams.get('limit')),
          offset: Number(url.searchParams.get('offset')),
        }),
      );
    } else {
      response.writeHead(500).end(JSON.stringify({ detail: 'unexpected fixture request' }));
    }
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    const config = {
      mode: 'cloud',
      workspaceId: '',
      tenantId: 'tenant',
      projectId: 'project',
      apiBaseUrl: `http://127.0.0.1:${server.address().port}`,
      apiKey: 'owned-fixture',
      localApiToken: '',
    };
    const client = new DesktopApiClient(config);
    let catalogFailure;
    try {
      await client.listWorkspacesForProject('project', 'tenant');
      assert.fail('missing catalog must not become an empty successful catalog');
    } catch (error) {
      catalogFailure = error;
    }
    assert.ok(catalogFailure instanceof DesktopApiError);
    assert.equal(catalogFailure.status, 404);
    assert.equal(workspaceCatalogFailureAllowsUnboundRuntime(config, catalogFailure), true);
    assert.deepEqual(catalogFailure.payload, { detail: 'Not a preview host' });
    assert.equal(catalogFailure.message, 'Not a preview host');
    const conversations = await client.listConversations('project', {
      unboundOnly: true,
    });
    assert.deepEqual(conversations.items, []);
    assert.equal(paths.length, 2);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('unavailable workspace catalog cannot restore an old workspace selection', () => {
  let preferenceReads = 0;
  const oldSelection = () => {
    preferenceReads += 1;
    return 'previous-python-workspace';
  };
  assert.equal(
    selectRuntimeWorkspaceAfterCatalog(
      { mode: 'cloud', workspaceId: '' },
      new DesktopApiError('missing', 404, { detail: 'Not a preview host' }),
      oldSelection,
    ),
    '',
  );
  assert.equal(preferenceReads, 0);
  assert.equal(
    selectRuntimeWorkspaceAfterCatalog(
      { mode: 'cloud', workspaceId: '' },
      null,
      () => 'current-catalog-workspace',
    ),
    'current-catalog-workspace',
  );
});

for (const [name, config, error] of [
  [
    'bound cloud workspace',
    { mode: 'cloud', workspaceId: 'workspace' },
    new DesktopApiError('missing', 404, { detail: 'missing' }),
  ],
  [
    'local runtime',
    { mode: 'local', workspaceId: '' },
    new DesktopApiError('missing', 404, { detail: 'missing' }),
  ],
  ...[0, 400, 401, 403, 409, 422, 429, 500, 502, 503].map((status) => [
    `critical HTTP ${status}`,
    { mode: 'cloud', workspaceId: '' },
    new DesktopApiError('failure', status, { detail: 'failure' }),
  ]),
  [
    'generation denial',
    { mode: 'cloud', workspaceId: '' },
    new Error('desktop_renderer_generation_retired'),
  ],
  ['untyped status field', { mode: 'cloud', workspaceId: '' }, { status: 404 }],
  [
    'structured license failure',
    { mode: 'cloud', workspaceId: '' },
    new DesktopApiError('license', 404, {
      detail: { code: 'license_required' },
    }),
  ],
  [
    'structured scope failure',
    { mode: 'cloud', workspaceId: '' },
    new DesktopApiError('scope', 404, { code: 'scope_resource_unavailable' }),
  ],
  ...[null, [], {}, { detail: null }, { detail: 'missing', error: 'permission_denied' }].map(
    (payload, index) => [
      `non-diagnostic 404 payload ${index}`,
      { mode: 'cloud', workspaceId: '' },
      new DesktopApiError('missing', 404, payload),
    ],
  ),
]) {
  test(`runtime retains ${name} as a failure`, () => {
    assert.equal(workspaceCatalogFailureAllowsUnboundRuntime(config, error), false);
  });
}
