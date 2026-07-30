import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CLOUD_PROJECT_OVERVIEW_LATEST_MEMORIES_QUERY,
  readCloudProjectOverview,
} from '/tmp/agistack-desktop-test-dist/src/features/project/projectOverviewClient.js';

test('Cloud project overview reads detail, stats, and latest-memory authority', async () => {
  const scope = {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const signal = new AbortController().signal;
  const calls = [];
  const project = {
    id: 'project-1',
    tenant_id: 'tenant-1',
    name: 'Desktop parity',
    description: 'Native project overview',
    created_at: '2026-07-30T00:00:00Z',
    updated_at: '2026-07-30T01:00:00Z',
  };
  const stats = {
    memory_count: 8,
    storage_used: 1024,
    storage_limit: 8192,
    active_nodes: 4,
    collaborators: 3,
  };
  const memory = {
    id: 'memory-1',
    project_id: 'project-1',
    title: 'Parity contract',
    content: 'Project Overview uses explicit authority.',
    content_type: 'text',
    status: 'ACTIVE',
    metadata: {},
    created_at: '2026-07-30T00:30:00Z',
    updated_at: null,
  };
  const client = {
    async getProject(requestedScope, options) {
      calls.push(['project', requestedScope, options]);
      return project;
    },
    async getProjectStats(requestedScope, options) {
      calls.push(['stats', requestedScope, options]);
      return stats;
    },
    async listMemories(requestedScope, query, options) {
      calls.push(['memories', requestedScope, query, options]);
      return {
        memories: [memory],
        total: 1,
        page: 1,
        page_size: 5,
      };
    },
  };

  const result = await readCloudProjectOverview(client, scope, { signal });

  assert.equal(scope.authority, 'cloud');
  assert.deepEqual(CLOUD_PROJECT_OVERVIEW_LATEST_MEMORIES_QUERY, {
    page: 1,
    page_size: 5,
  });
  assert.deepEqual(calls, [
    ['project', scope, { signal }],
    ['stats', scope, { signal }],
    ['memories', scope, { page: 1, page_size: 5 }, { signal }],
  ]);
  assert.deepEqual(result, {
    kind: 'ready',
    snapshot: {
      scope,
      project,
      stats,
      latestMemories: [memory],
      latestMemoriesTotal: 1,
    },
  });
});

test('project overview returns explicit empty authority when project detail is absent', async () => {
  const scope = {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-missing',
  };
  const client = {
    getProject: async () => null,
    getProjectStats: async () => ({
      memory_count: 0,
      storage_used: 0,
      storage_limit: 0,
      active_nodes: 0,
      collaborators: 0,
    }),
    listMemories: async () => ({
      memories: [],
      total: 0,
      page: 1,
      page_size: 5,
    }),
  };

  assert.deepEqual(await readCloudProjectOverview(client, scope), { kind: 'empty' });
});

test('project overview forwards structured scope without inferring runtime mode or URL', async () => {
  const scope = {
    authority: 'cloud',
    tenantId: 'local://tenant-authority',
    projectId: 'https://example.invalid/project',
  };
  const seenScopes = [];
  const client = {
    getProject: async (requestedScope) => {
      seenScopes.push(requestedScope);
      return {
        id: requestedScope.projectId,
        tenant_id: requestedScope.tenantId,
        name: 'Opaque identifiers',
        description: null,
        created_at: null,
        updated_at: null,
      };
    },
    getProjectStats: async (requestedScope) => {
      seenScopes.push(requestedScope);
      return {
        memory_count: 0,
        storage_used: 0,
        storage_limit: 0,
        active_nodes: 0,
        collaborators: 0,
      };
    },
    listMemories: async (requestedScope) => {
      seenScopes.push(requestedScope);
      return {
        memories: [],
        total: 0,
        page: 1,
        page_size: 5,
      };
    },
  };

  const result = await readCloudProjectOverview(client, scope);

  assert.equal(result.kind, 'ready');
  assert.deepEqual(seenScopes, [scope, scope, scope]);
  assert.deepEqual(result.snapshot.scope, scope);
});
