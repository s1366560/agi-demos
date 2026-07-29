import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createLocalSearchClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/search/localSearchClient.js');
const {
  createManagedResourcesClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/managedResourcesClient.js');
const {
  createMcpAppHostClient,
  createMcpAppsClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/mcpAppsClient.js');
const {
  createWorkspaceCollaborationClient,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceCollaborationClient.js',
);
const {
  createDesktopArtifactClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/desktopArtifactClient.js');
const {
  createAutomationClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/automations/automationClientPort.js');

test('narrow domain clients expose only their contract and preserve authority calls', async () => {
  const calls = [];
  const search = createLocalSearchClient({
    getCapability: async () => ({
      mode: 'keyword_degraded',
      reason_code: 'local_search_keyword_only',
      projection_revision: 7,
      backfill_cursor: null,
    }),
    search: async (request, scope) => {
      calls.push(['search', request, scope]);
      return {
        results: [],
        total: 0,
        query: request.mode === 'community' ? '' : request.query,
        searchType: request.mode,
        facets: null,
        limit: request.limit,
        offset: 0,
      };
    },
  });
  assert.deepEqual(Object.keys(search).sort(), ['getCapability', 'search']);
  assert.equal((await search.getCapability()).mode, 'keyword_degraded');

  const managed = createManagedResourcesClient({
    list: async (scope, kind) => {
      calls.push(['managed.list', scope, kind]);
      return [];
    },
    getVersions: async () => [],
    mutate: async () => {
      throw new Error('not used');
    },
  });
  assert.deepEqual(Object.keys(managed).sort(), ['getVersions', 'list', 'mutate']);
  await managed.list({ tenant_id: 'tenant-1', project_id: 'project-1' }, 'skill');

  const mcp = createMcpAppsClient({
    listApps: async (projectId) => {
      calls.push(['mcp.list', projectId]);
      return [];
    },
    listTools: async () => [],
    callTool: async () => null,
    listResources: async () => [],
    readResource: async () => null,
  });
  assert.deepEqual(Object.keys(mcp).sort(), [
    'callTool',
    'listApps',
    'listResources',
    'listTools',
    'readResource',
  ]);
  await mcp.listApps('project-1');
  const host = createMcpAppHostClient({
    callMCPAppTool: async (...args) => {
      calls.push(['mcp.host.call', ...args]);
      return { content: [], is_error: false };
    },
  });
  assert.deepEqual(Object.keys(host), ['callMCPAppTool']);
  await host.callMCPAppTool('app-1', 'render', {}, 'desktop-mcp-tool-call:narrow-1');

  assert.deepEqual(
    calls.map(([name]) => name),
    ['managed.list', 'mcp.list', 'mcp.host.call'],
  );
});

test('workspace and artifact clients retain revision and idempotency authority', async () => {
  const calls = [];
  const workspaceState = {
    workspace_id: 'workspace-1',
    surface: 'goals',
    authority: 'cloud',
    status: 'ready',
    revision: 3,
    cursor: 'cursor-3',
    data: { goals: [] },
    reason_code: null,
  };
  const workspace = createWorkspaceCollaborationClient({
    getSurface: async (...args) => {
      calls.push(['workspace.get', ...args]);
      return workspaceState;
    },
    refetchAuthority: async () => workspaceState,
    mutateSurface: async (...args) => {
      calls.push(['workspace.mutate', ...args]);
      return { ...workspaceState, revision: 4 };
    },
  });
  assert.equal(
    (await workspace.getSurface('workspace-1', 'goals', 'cursor-2')).revision,
    3,
  );
  assert.equal(
    (
      await workspace.mutateSurface('workspace-1', 'goals', {
        action: 'create_goal',
        expected_revision: 3,
        idempotency_key: 'goal-create-1',
        payload: { title: 'Parity' },
      })
    ).revision,
    4,
  );

  const artifact = createDesktopArtifactClient({
    loadContent: async () => ({
      contract_version: 2,
      artifact_id: 'artifact-1',
      revision: 2,
      content_hash: 'sha256:server',
      mime_type: 'text/markdown',
      content: '# Server',
    }),
    saveContent: async (artifactId, command) => {
      calls.push(['artifact.save', artifactId, command]);
      return {
        artifact_id: artifactId,
        revision: command.expected_revision + 1,
        content_hash: command.content_hash,
        duplicate: false,
      };
    },
    download: async () => new Blob(),
  });
  const receipt = await artifact.saveContent('artifact-1', {
    contract_version: 2,
    expected_revision: 2,
    content_hash: 'sha256:draft',
    idempotency_key: 'artifact-save-1',
    content: '# Draft',
  });
  assert.equal(receipt.revision, 3);
  assert.deepEqual(
    calls.map(([name]) => name),
    ['workspace.get', 'workspace.mutate', 'artifact.save'],
  );
});

test('AutomationClient is the unified narrow name for the existing guarded adapter', () => {
  assert.equal(typeof createAutomationClient, 'function');
});
