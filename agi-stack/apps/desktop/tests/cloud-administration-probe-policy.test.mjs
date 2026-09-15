import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
function dependencies(projectTenant = 'tenant-1') {
  const calls = [];
  return {
    calls,
    loadTrustedSession: async () => ({ version: 1, api_base_url: 'https://cloud.test', runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'test-only', expires_at: '2099-09-14T00:00:00Z' }),
    fetch: async (url) => {
      const target = new URL(url); calls.push(target.pathname + target.search);
      const body = target.pathname === '/api/v1/workspace-context'
        ? { context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 1 } }
        : target.pathname === '/api/v1/projects/project-2'
          ? { id: 'project-2', tenant_id: projectTenant }
          : { items: [] };
      return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
    },
  };
}
const reads = [
  '/api/v1/agent/definitions?tenant_id=tenant-1&scope=tenant&enabled_only=true&limit=100',
  ...['entities', 'edges', 'mappings'].map((part) => `/api/v1/projects/project-1/schema/${part}`),
  ...['maintenance/status', 'data/stats', 'maintenance/embeddings/status'].map((part) => `/api/v1/${part}?tenant_id=tenant-1&project_id=project-1`),
];
for (const path of reads) test(`native administration probe reaches authenticated transport: ${path}`, async () => {
  const deps = dependencies();
  assert.equal((await executeVaultBoundCloudRequest({ path, method: 'GET' }, deps)).status, 200);
  assert.equal(deps.calls.at(-1), path);
  await assert.rejects(executeVaultBoundCloudRequest({ path: path.replace('tenant-1', 'foreign').replace('project-1', 'foreign'), method: 'GET' }, dependencies()), /scope mismatch/);
  await assert.rejects(executeVaultBoundCloudRequest({ path, method: 'POST' }, dependencies()), /endpoint is not allowed/);
  await assert.rejects(executeVaultBoundCloudRequest({ path: path + (path.includes('?') ? '&' : '?') + 'extra=1', method: 'GET' }, dependencies()), /endpoint is not allowed/);
});
test('tenant catalog membership observes authoritative project ownership before another project read', async () => {
  const path = '/api/v1/projects/project-2/members?tenant_id=tenant-1';
  const deps = dependencies();
  assert.equal((await executeVaultBoundCloudRequest({ path, method: 'GET' }, deps)).status, 200);
  assert.deepEqual(deps.calls, ['/api/v1/workspace-context', '/api/v1/projects/project-2?tenant_id=tenant-1', path]);
  const foreign = dependencies('foreign');
  await assert.rejects(executeVaultBoundCloudRequest({ path, method: 'GET' }, foreign), /catalog project scope observation failed/);
  assert.equal(foreign.calls.includes(path), false);
  await assert.rejects(executeVaultBoundCloudRequest({ path: '/api/v1/projects/project-2/members', method: 'GET' }, dependencies()), /project scope mismatch/);
});

test('real project administration and tenant catalog clients traverse the vault policy with valid authority', async () => {
  const root = '/tmp/agistack-desktop-test-dist/src/';
  const { DEFAULT_CONFIG } = require(root + 'types.js');
  const config = { ...DEFAULT_CONFIG, mode: 'cloud', apiKey: '', apiBaseUrl: 'https://cloud.test', tenantId: 'tenant-1', projectId: 'project-1' };
  const scope = { authority: 'cloud', tenantId: 'tenant-1', projectId: 'project-1' };
  const project = (id) => ({ id, tenant_id: 'tenant-1', name: id, description: '', owner_id: 'user-1', member_ids: ['user-1'], is_public: false,
    memory_rules: { max_episodes: 100, retention_days: 30, auto_refresh: true, refresh_interval: 24 },
    graph_config: { max_nodes: 100, max_edges: 100, similarity_threshold: 0.7, community_detection: true },
    sandbox_config: { sandbox_type: 'docker' }, agent_conversation_mode: 'threaded', created_at: '2026-09-14T00:00:00Z', updated_at: null, stats: {} });
  const deps = dependencies();
  const seen = [];
  deps.fetch = async (url) => {
    const target = new URL(url); seen.push(target.pathname + target.search);
    const path = target.pathname;
    let body;
    if (path === '/api/v1/workspace-context') body = { context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 1 }, membership_role: 'owner' };
    else if (path === '/api/v1/auth/me') body = { user_id: 'user-1' };
    else if (path.endsWith('/members')) body = { members: [{ user_id: 'user-1', role: 'owner' }], total: 1 };
    else if (path.includes('/schema/')) body = [];
    else if (path === '/api/v1/data/stats') body = { entity_count: 0, episodic_count: 0, community_count: 0, edge_count: 0 };
    else if (path === '/api/v1/maintenance/status') body = { stats: { entities: 0, episodes: 0, communities: 0, old_episodes: 0 }, recommendations: [], last_checked: null };
    else if (path === '/api/v1/maintenance/embeddings/status') body = { current_provider: 'fixture', current_dimension: 1, existing_dimension: 1, is_compatible: true, missing_embeddings: 0 };
    else if (path === '/api/v1/projects/') body = { projects: [project('project-1'), project('project-2')], total: 2, page: 1, page_size: 20, owner_ids: ['user-1'] };
    else if (path === '/api/v1/projects/project-1') body = project('project-1');
    else if (path === '/api/v1/projects/project-2') body = project('project-2');
    else if (path.includes('/sandbox')) return new Response('{}', { status: 404, headers: { 'content-type': 'application/json' } });
    else throw new Error('unexpected fixture route ' + path);
    return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
  };
  const originalWindow = globalThis.window;
  globalThis.window = { __MEMSTACK_DESKTOP__: { core: { invoke: async (command, args) => {
    assert.equal(command, 'cloud_request');
    return executeVaultBoundCloudRequest(args.request, deps);
  } } } };
  try {
    for (const name of ['Schema', 'Maintenance', 'Settings']) {
      const factory = require(root + `plugins/desktopProject${name}HttpProjectionV2.js`)[`createDesktopProject${name}HttpAuthorityV2`];
      const snapshot = await factory(config, scope).load();
      assert.equal(snapshot.membershipRole, 'owner');
      assert.equal(snapshot.scopeRevision, 1);
    }
    const { applyDesktopTenantProjectsAuthorityV2 } = require(root + 'plugins/desktopTenantProjectsAuthorityModuleV2.js');
    let service;
    applyDesktopTenantProjectsAuthorityV2({ provide: (_, value) => { service = value; } }, { strategy: 'desktop-api-fetch' });
    const catalog = await service.bindOperation(config, { authority: 'cloud', tenantId: 'tenant-1' }).list();
    assert.equal(catalog.projects.length, 2);
    assert.ok(seen.includes('/api/v1/projects/project-2/members?tenant_id=tenant-1'));
    assert.ok(seen.includes('/api/v1/projects/project-2?tenant_id=tenant-1'));
    assert.ok(seen.includes('/api/v1/projects/project-1?tenant_id=tenant-1'));
    for (const path of reads.slice(1)) assert.ok(seen.includes(path), path);
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
