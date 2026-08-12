import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  createAccessibilityAuthorityFixture,
  resolveAccessibilityAuthorityResponse,
} from '../browser-qa/accessibility-authority-fixture.mjs';

const scope = Object.freeze({
  tenantId: 'accessibility-tenant',
  projectId: 'accessibility-project',
  workspaceId: 'accessibility-workspace',
});

test('accessibility authority fixture returns scoped admin identity and revision', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const user = fixture.resolve({ method: 'GET', url: 'http://127.0.0.1/api/v1/auth/me' });
  const context = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/workspace-context',
  });

  assert.equal(user.status, 200);
  assert.equal(user.body.user_id, 'accessibility-admin');
  assert.equal(user.body.is_active, true);
  assert.deepEqual(user.body.global_roles, ['system_admin']);
  assert.equal(context.body.context.tenant_id, scope.tenantId);
  assert.equal(context.body.context.project_id, scope.projectId);
  assert.equal(context.body.context.revision, 1);
  assert.equal(context.body.membership_role, 'admin');
});

test('accessibility authority fixture switches role without accepting renderer role input', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  fixture.setRole('member');

  const user = fixture.resolve({ method: 'GET', url: 'http://127.0.0.1/api/v1/auth/me' });
  const context = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/workspace-context',
  });

  assert.equal(user.body.user_id, 'accessibility-member');
  assert.deepEqual(user.body.global_roles, []);
  assert.equal(user.body.is_superuser, false);
  assert.equal(context.body.membership_role, 'member');
  assert.equal(fixture.observation().role, 'member');
  assert.equal(fixture.observation().authorityRevision, 2);
});

test('accessibility authority response rejects unknown paths instead of inventing capability', () => {
  assert.equal(
    resolveAccessibilityAuthorityResponse(
      { method: 'GET', url: 'http://127.0.0.1/api/v1/unknown' },
      { ...scope, role: 'admin', authorityRevision: 1 },
    ),
    null,
  );
});

test('accessibility authority fixture exposes valid login catalogs and tenant overview', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const login = fixture.resolve({
    method: 'POST',
    url: 'http://127.0.0.1/api/v1/auth/token',
  });
  const tenants = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/tenants?page=1&page_size=100',
  });
  const projects = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/projects?page=1&page_size=100&tenant_id=${scope.tenantId}`,
  });
  const overview = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/stats`,
  });

  assert.match(login.body.access_token, /^ms_sk_[0-9a-f]{64}$/u);
  assert.equal(tenants.body.tenants[0].id, scope.tenantId);
  assert.equal(projects.body.projects[0].id, scope.projectId);
  assert.equal(overview.body.tenant_info.organization_id, 'Accessibility QA');
  assert.equal(overview.body.authority_revision, 1);
  assert.equal(overview.body.storage.percentage, 0);
  assert.deepEqual(overview.body.members, { total: 1, new_added: 0 });
  assert.deepEqual(overview.body.projects.list, []);
});

test('accessibility authority fixture exposes the Cloud Projects capability authority', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const projects = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/projects/?tenant_id=${scope.tenantId}&page=1&page_size=1`,
  });
  const members = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/projects/${scope.projectId}/members`,
  });

  assert.equal(projects.status, 200);
  assert.equal(projects.body.projects[0].tenant_id, scope.tenantId);
  assert.equal(projects.body.projects[0].owner_id, 'accessibility-admin');
  assert.equal(projects.body.page_size, 1);
  assert.deepEqual(members.body.members, [
    {
      user_id: 'accessibility-admin',
      email: 'admin@accessibility.invalid',
      name: 'Accessibility admin',
      role: 'owner',
      permissions: { read: true, write: true },
      created_at: '2026-01-01T00:00:00Z',
    },
  ]);

  const definitions = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/agent/definitions?include_total=true&limit=50&offset=0' +
      `&tenant_id=${scope.tenantId}&project_id=${scope.projectId}`,
  });
  assert.equal(definitions.body.definitions[0].project_id, scope.projectId);

  fixture.setRole('member');
  const memberAuthority = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/projects/${scope.projectId}/members`,
  });
  assert.deepEqual(memberAuthority.body.members, [
    {
      user_id: 'accessibility-member',
      email: 'member@accessibility.invalid',
      name: 'Accessibility member',
      role: 'member',
      permissions: { read: true, write: false },
      created_at: '2026-01-01T00:00:00Z',
    },
  ]);
});

test('accessibility authority fixture exposes scoped Cloud Project Overview reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const project = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/projects/${scope.projectId}` +
      `?tenant_id=${scope.tenantId}`,
  });
  const settingsProject = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/projects/${scope.projectId}`,
  });
  const stats = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/projects/${scope.projectId}/stats`,
  });
  const memories = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/memories/?page=1&page_size=5' +
      `&project_id=${scope.projectId}`,
  });

  assert.equal(project.status, 200);
  assert.equal(project.body.id, scope.projectId);
  assert.equal(project.body.tenant_id, scope.tenantId);
  assert.equal(project.body.owner_id, 'accessibility-admin');
  assert.equal(project.body.is_public, false);
  assert.deepEqual(project.body.memory_rules, {
    max_episodes: 1000,
    retention_days: 365,
    auto_refresh: true,
    refresh_interval: 60,
  });
  assert.deepEqual(project.body.graph_config, {
    max_nodes: 10000,
    max_edges: 50000,
    similarity_threshold: 0.8,
    community_detection: true,
  });
  assert.deepEqual(project.body.sandbox_config, { sandbox_type: 'docker' });
  assert.equal(project.body.agent_conversation_mode, 'workspace');
  assert.equal(settingsProject.body.id, scope.projectId);
  assert.deepEqual(settingsProject.body.memory_rules, project.body.memory_rules);
  assert.equal(stats.body.project_id, scope.projectId);
  assert.equal(stats.body.tenant_id, scope.tenantId);
  assert.equal(stats.body.memory_count, 0);
  assert.deepEqual(memories.body.memories, []);
  assert.equal(memories.body.total, 0);
  assert.equal(
    fixture.resolve({
      method: 'GET',
      url:
        `http://127.0.0.1/api/v1/projects/${scope.projectId}` +
        '?tenant_id=other-tenant',
    }),
    null,
  );
});

test('accessibility authority fixture represents an unconfigured project sandbox as not found', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  for (const suffix of ['/sandbox', '/sandbox/stats']) {
    const result = fixture.resolve({
      method: 'GET',
      url: `http://127.0.0.1/api/v1/projects/${scope.projectId}${suffix}`,
    });

    assert.equal(result.status, 404);
    assert.deepEqual(result.body, {
      detail: 'project_sandbox_not_configured',
      reason_code: 'project_sandbox_not_configured',
    });
  }
});

test('accessibility authority fixture exposes complete Project Knowledge empty reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const requests = [
    [
      'http://127.0.0.1/api/v1/memories/?' +
        `project_id=${scope.projectId}&page=1&page_size=50`,
      {
        tenant_id: scope.tenantId,
        project_id: scope.projectId,
        memories: [],
        total: 0,
        page: 1,
        page_size: 50,
      },
    ],
    [
      'http://127.0.0.1/api/v1/graph/entities/?' +
        `tenant_id=${scope.tenantId}&project_id=${scope.projectId}&limit=50&offset=0`,
      { entities: [], total: 0, limit: 50, offset: 0 },
    ],
    [
      'http://127.0.0.1/api/v1/graph/entities/types?' +
        `tenant_id=${scope.tenantId}&project_id=${scope.projectId}`,
      { entity_types: [], total: 0 },
    ],
    [
      'http://127.0.0.1/api/v1/graph/communities/?' +
        `tenant_id=${scope.tenantId}&project_id=${scope.projectId}&limit=50&offset=0`,
      { communities: [], total: 0, limit: 50, offset: 0 },
    ],
    [
      'http://127.0.0.1/api/v1/graph/memory/graph?' +
        `tenant_id=${scope.tenantId}&project_id=${scope.projectId}&limit=1000`,
      { elements: { nodes: [], edges: [] } },
    ],
  ];

  for (const [url, expected] of requests) {
    const result = fixture.resolve({ method: 'GET', url });
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, expected);
  }
});

test('accessibility authority fixture exposes the current Search capability contract', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const result = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/search-enhanced/capabilities',
  });

  assert.equal(result.status, 200);
  assert.equal(result.body.service_version, '0.1.0');
  assert.equal(result.body.contract_version, '2.1.0');
  assert.deepEqual(result.body.graph_backend, {
    status: 'available',
    reason_code: null,
    retryable: false,
    allowed_actions: ['search', 'traverse', 'rebuild_communities'],
  });
  assert.equal(
    result.body.search_types.advanced.endpoint,
    '/api/v1/search-enhanced/advanced',
  );
  assert.deepEqual(Object.keys(result.body.search_types), [
    'semantic',
    'advanced',
    'graph_traversal',
    'community',
    'temporal',
    'faceted',
  ]);
});

test('accessibility authority fixture exposes scoped Cloud Cron Jobs reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const capabilities = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/projects/${scope.projectId}` +
      '/cron-jobs/capabilities',
  });
  const jobs = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/projects/${scope.projectId}` +
      '/cron-jobs?include_disabled=true&limit=100&offset=0',
  });

  assert.equal(capabilities.status, 200);
  assert.deepEqual(capabilities.body, {
    service_version: '0.1.0',
    contract_version: '2.0.0',
    schema_version: 1,
    read: true,
    revision_guarded: false,
    idempotency_guarded: false,
    durable_execution: false,
    supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
    create: {
      allowed: false,
      reason_code: 'durable_automation_runtime_unavailable',
    },
    edit: {
      allowed: false,
      reason_code: 'durable_automation_runtime_unavailable',
    },
    toggle: {
      allowed: false,
      reason_code: 'durable_automation_runtime_unavailable',
    },
    run_now: {
      allowed: false,
      reason_code: 'durable_automation_execution_unavailable',
    },
    delete: {
      allowed: false,
      reason_code: 'durable_automation_runtime_unavailable',
    },
  });
  assert.equal(jobs.status, 200);
  assert.deepEqual(jobs.body, { items: [], total: 0 });
});

test('accessibility authority fixture exposes scoped Project Agent empty reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const runs = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/agent/trace/runs/project/${scope.projectId}` +
      '?limit=8',
  });
  const active = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/agent/trace/runs/project/${scope.projectId}` +
      '/active/count',
  });
  const patterns = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/agent/workflows/patterns/project/${scope.projectId}` +
      '?page=1&page_size=100',
  });

  assert.deepEqual(runs.body, { project_id: scope.projectId, runs: [], total: 0 });
  assert.deepEqual(active.body, { project_id: scope.projectId, active_count: 0 });
  assert.deepEqual(patterns.body, {
    project_id: scope.projectId,
    tenant_id: scope.tenantId,
    scope_kind: 'tenant_shared',
    patterns: [],
    total: 0,
    page: 1,
    page_size: 100,
  });
});

test('accessibility authority fixture exposes empty project schema authorities', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  for (const resource of ['entities', 'edges', 'mappings']) {
    const result = fixture.resolve({
      method: 'GET',
      url:
        `http://127.0.0.1/api/v1/projects/${scope.projectId}/schema/` +
        resource,
    });
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, []);
  }
});

test('accessibility authority fixture exposes empty project channel authorities', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const catalog = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/channels/tenants/${scope.tenantId}` +
      '/plugins/channel-catalog',
  });
  const configs = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/channels/projects/${scope.projectId}/configs`,
  });

  assert.equal(catalog.status, 200);
  assert.deepEqual(catalog.body, { items: [] });
  assert.equal(configs.status, 200);
  assert.deepEqual(configs.body, { items: [] });
});

test('accessibility authority fixture exposes empty project maintenance authorities', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const expected = new Map([
    [
      '/api/v1/maintenance/status',
      {
        stats: { entities: 0, episodes: 0, communities: 0, old_episodes: 0 },
        recommendations: [],
        last_checked: '2026-01-01T00:00:00Z',
      },
    ],
    [
      '/api/v1/data/stats',
      { entity_count: 0, episodic_count: 0, community_count: 0, edge_count: 0 },
    ],
    [
      '/api/v1/maintenance/embeddings/status',
      {
        current_provider: 'accessibility-fixture',
        current_dimension: 0,
        existing_dimension: 0,
        is_compatible: true,
        missing_embeddings: 0,
      },
    ],
  ]);
  for (const [path, body] of expected) {
    const result = fixture.resolve({
      method: 'GET',
      url:
        `http://127.0.0.1${path}?tenant_id=${scope.tenantId}` +
        `&project_id=${scope.projectId}`,
    });
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, body);
  }
});

test('accessibility authority fixture provisions a complete selected workspace bootstrap', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const workspaceRoot =
    `/api/v1/tenants/${scope.tenantId}/projects/${scope.projectId}` +
    `/workspaces/${scope.workspaceId}`;
  const workspaces = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/projects/${scope.projectId}` +
      '/workspaces?limit=100&offset=0',
  });
  const messages = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1${workspaceRoot}/messages`,
  });
  const members = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1${workspaceRoot}/members?limit=100&offset=0`,
  });
  const agents = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1${workspaceRoot}/agents?active_only=false&limit=100&offset=0`,
  });
  const tasks = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/workspaces/${scope.workspaceId}/tasks`,
  });
  const conversations = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/agent/conversations?project_id=${scope.projectId}` +
      `&workspace_id=${scope.workspaceId}&status=active&limit=100&offset=0`,
  });
  const myWork = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/projects/${scope.projectId}/my-work`,
  });

  assert.equal(workspaces.body[0].id, scope.workspaceId);
  assert.deepEqual(messages.body, []);
  assert.deepEqual(members.body, []);
  assert.deepEqual(agents.body, []);
  assert.deepEqual(tasks.body, []);
  assert.deepEqual(conversations.body, {
    items: [],
    total: 0,
    has_more: false,
    offset: 0,
    limit: 100,
    next_offset: null,
  });
  assert.deepEqual(myWork.body.items, []);
});

test('accessibility authority fixture exposes revisioned Blackboard surface authority', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const workspaceRoot =
    `/api/v1/tenants/${scope.tenantId}/projects/${scope.projectId}` +
    `/workspaces/${scope.workspaceId}`;
  const authority = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1${workspaceRoot}/collaboration/authority`,
  });
  const objectives = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1${workspaceRoot}/objectives`,
  });

  assert.deepEqual(authority.body, {
    contract_version: '2.0.0',
    tenant_id: scope.tenantId,
    project_id: scope.projectId,
    workspace_id: scope.workspaceId,
    revision: 1,
    cursor: 'accessibility-workspace-revision-1',
  });
  assert.deepEqual(objectives.body, []);
});

test('accessibility authority fixture exposes the Cloud Agent Bindings capability authority', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const bindings = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/agent/bindings?tenant_id=${scope.tenantId}`,
  });
  const definitions = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/agent/definitions?tenant_id=${scope.tenantId}` +
      '&scope=tenant&enabled_only=true&limit=100',
  });

  assert.equal(bindings.status, 200);
  assert.deepEqual(bindings.body, []);
  assert.equal(definitions.body[0].tenant_id, scope.tenantId);
  assert.equal(definitions.body[0].project_id, null);
  assert.equal(definitions.body[0].enabled, true);
});

test('accessibility authority fixture exposes revisioned Tenant Agent Dashboard reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const config = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/agent/config?tenant_id=${scope.tenantId}`,
  });
  const permission = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/agent/config/can-modify?tenant_id=${scope.tenantId}`,
  });
  const catalog = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/agent/config/hooks/catalog?tenant_id=${scope.tenantId}`,
  });
  const runs = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/agent/trace/runs/tenant/${scope.tenantId}` +
      '?limit=20',
  });
  const active = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/agent/trace/runs/tenant/${scope.tenantId}` +
      '/active/count',
  });

  assert.equal(config.body.tenant_id, scope.tenantId);
  assert.equal(config.body.authority_revision, 1);
  assert.deepEqual(permission.body, { can_modify: true });
  assert.deepEqual(catalog.body, { hooks: [] });
  assert.deepEqual(runs.body, { tenant_id: scope.tenantId, runs: [], total: 0 });
  assert.deepEqual(active.body, { tenant_id: scope.tenantId, active_count: 0 });

  fixture.setRole('member');
  const memberPermission = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/agent/config/can-modify?tenant_id=${scope.tenantId}`,
  });
  assert.deepEqual(memberPermission.body, { can_modify: false });
});

test('accessibility authority fixture exposes a revisioned Skills collection', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const skills = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/skills/?tenant_id=${scope.tenantId}` +
      `&project_id=${scope.projectId}&limit=100&offset=0`,
  });

  assert.equal(skills.status, 200);
  assert.equal(skills.body.authority_revision, 1);
  assert.equal(skills.body.total, 1);
  assert.equal(skills.body.skills[0].tenant_id, scope.tenantId);
  assert.equal(skills.body.skills[0].project_id, scope.projectId);
});

test('accessibility authority fixture exposes a revisioned Plugins collection', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const plugins = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/channels/tenants/${scope.tenantId}/plugins`,
  });

  assert.equal(plugins.status, 200);
  assert.equal(plugins.body.authority_revision, 1);
  assert.deepEqual(plugins.body.items, []);
  assert.deepEqual(plugins.body.diagnostics, []);
});

test('accessibility authority fixture exposes a revisioned MCP Servers collection', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const servers = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/mcp?project_id=${scope.projectId}`,
  });

  assert.equal(servers.status, 200);
  assert.equal(servers.body.authority_revision, 1);
  assert.deepEqual(servers.body.servers, []);
});

test('accessibility authority fixture exposes scoped ACP status and runner pools', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const status = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/acp/tenants/${scope.tenantId}/status`,
  });
  const runnerPools = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/acp/tenants/${scope.tenantId}/runner-pools`,
  });

  assert.equal(status.status, 200);
  assert.equal(status.body.enabled, true);
  assert.equal(status.body.agentCount, 0);
  assert.deepEqual(status.body.agents, []);
  assert.deepEqual(status.body.sessions, []);
  assert.equal(runnerPools.status, 200);
  assert.deepEqual(runnerPools.body, []);
});

test('accessibility authority fixture exposes a revisioned tenant Genes collection', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const genes = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/genes/?tenant_id=${scope.tenantId}` +
      '&page=1&page_size=20',
  });

  assert.equal(genes.status, 200);
  assert.equal(genes.body.authority_revision, 1);
  assert.deepEqual(genes.body.genes, []);
  assert.equal(genes.body.total, 0);
  assert.equal(genes.body.page, 1);
  assert.equal(genes.body.page_size, 20);
});

test('accessibility authority fixture exposes revisioned tenant governance reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const members = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/members`,
  });
  const invitations = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/invitations` +
      '?limit=50&offset=0',
  });

  assert.equal(members.status, 200);
  assert.equal(members.body.authority_revision, 1);
  assert.equal(members.body.members[0].role, 'owner');
  assert.deepEqual(invitations.body.items, []);
  assert.equal(invitations.body.total, 0);
});

test('accessibility authority fixture exposes revisioned tenant trust policies', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const policies = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/trust/policies` +
      '?workspace_id=accessibility-workspace',
  });

  assert.equal(policies.status, 200);
  assert.equal(policies.body.authority_revision, 1);
  assert.deepEqual(policies.body.items, []);
});

test('accessibility authority fixture exposes scoped tenant decision records', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const decisions = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/trust/decision-records` +
      `?workspace_id=${scope.workspaceId}`,
  });

  assert.equal(decisions.status, 200);
  assert.deepEqual(decisions.body.items, []);
  assert.equal(decisions.body.authority_revision, 1);
  assert.equal(
    fixture.resolve({
      method: 'GET',
      url:
        `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/trust/decision-records` +
        '?workspace_id=other-workspace',
    }),
    null,
  );
});

test('accessibility authority fixture exposes revisioned tenant billing reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const billing = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/billing`,
  });
  const invoices = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/invoices`,
  });

  assert.equal(billing.status, 200);
  assert.equal(billing.body.tenant.id, scope.tenantId);
  assert.equal(billing.body.authority_revision, 1);
  assert.deepEqual(invoices.body.invoices, []);
  assert.equal(invoices.body.authority_revision, 1);
});

test('accessibility authority fixture exposes scoped tenant organization settings reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const tenantBase = `http://127.0.0.1/api/v1/tenants/${scope.tenantId}`;
  const tenant = fixture.resolve({ method: 'GET', url: tenantBase });
  const registries = fixture.resolve({ method: 'GET', url: `${tenantBase}/registries` });
  const smtp = fixture.resolve({ method: 'GET', url: `${tenantBase}/smtp-config` });
  const genePolicies = fixture.resolve({
    method: 'GET',
    url: `${tenantBase}/gene-policies`,
  });

  assert.equal(tenant.status, 200);
  assert.equal(tenant.body.id, scope.tenantId);
  assert.equal(tenant.body.owner_id, 'accessibility-admin');
  assert.deepEqual(registries.body, []);
  assert.equal(smtp.status, 200);
  assert.equal(smtp.body, null);
  assert.deepEqual(genePolicies.body, []);
  assert.equal(
    fixture.resolve({
      method: 'GET',
      url: 'http://127.0.0.1/api/v1/tenants/other-tenant/registries',
    }),
    null,
  );
});

test('accessibility authority fixture exposes revisioned tenant audit reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const page = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/audit-logs` +
      '?limit=20&offset=0',
  });
  const summary = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/audit-logs` +
      '/runtime-hooks/summary',
  });

  assert.equal(page.status, 200);
  assert.equal(page.body.authority_revision, 1);
  assert.deepEqual(page.body.items, []);
  assert.equal(page.body.limit, 20);
  assert.equal(summary.status, 200);
  assert.equal(summary.body.authority_revision, 1);
  assert.deepEqual(summary.body.action_counts, {});
});

test('accessibility authority fixture exposes a revisioned provider authority snapshot', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const providers = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/llm-providers/authority-snapshot?include_inactive=true',
  });

  assert.equal(providers.status, 200);
  assert.equal(providers.body.authority_revision, 1);
  assert.deepEqual(providers.body.providers, []);
  assert.equal(providers.body.types[0].provider_type, 'openai');
  assert.deepEqual(providers.body.types[0].auth_methods, ['api_key']);
});

test('accessibility authority fixture exposes scoped Cloud Webhooks reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const webhooks = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/tenant-webhooks/${scope.tenantId}`,
  });
  const eventTypes = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/events/types?tenant_id=${scope.tenantId}`,
  });

  assert.equal(webhooks.status, 200);
  assert.deepEqual(webhooks.body, []);
  assert.equal(eventTypes.status, 200);
  assert.deepEqual(eventTypes.body, ['agent.run.completed']);
  assert.equal(
    fixture.resolve({
      method: 'GET',
      url: 'http://127.0.0.1/api/v1/events/types?tenant_id=other-tenant',
    }),
    null,
  );
});

test('accessibility authority fixture exposes a revisioned tenant Events page', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const events = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/events?' +
      `tenant_id=${scope.tenantId}&page=1&page_size=20`,
  });

  assert.equal(events.status, 200);
  assert.equal(events.body.authority_revision, 1);
  assert.deepEqual(events.body.items, []);
  assert.equal(events.body.page, 1);
  assert.equal(events.body.page_size, 20);
});

test('accessibility authority fixture exposes revisioned scoped Runtime inventory', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const status = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/admin/pool/status' +
      `?scope=tenant&tenant_id=${scope.tenantId}`,
  });
  const instances = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/admin/pool/instances' +
      `?scope=tenant&tenant_id=${scope.tenantId}&page=1&page_size=100`,
  });
  const sandboxes = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/projects/sandboxes?limit=100&offset=0',
  });

  assert.equal(status.status, 200);
  assert.equal(status.body.tenant_id, scope.tenantId);
  assert.equal(status.body.authority_revision, 1);
  assert.deepEqual(instances.body.instances, []);
  assert.equal(instances.body.tenant_id, scope.tenantId);
  assert.deepEqual(sandboxes.body, { sandboxes: [], total: 0 });

  fixture.setRole('member');
  const memberStatus = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/admin/pool/status' +
      `?scope=tenant&tenant_id=${scope.tenantId}`,
  });
  const memberInstances = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/admin/pool/instances' +
      `?scope=tenant&tenant_id=${scope.tenantId}&page=1&page_size=100`,
  });

  assert.equal(memberStatus.status, 403);
  assert.equal(memberStatus.body.detail, 'global_admin_required');
  assert.equal(memberInstances.status, 403);
  assert.equal(memberInstances.body.detail, 'global_admin_required');
});

test('accessibility authority fixture exposes revisioned tenant Runtime Instances', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const admin = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/instances/?page=1&page_size=1',
  });

  assert.equal(admin.status, 200);
  assert.deepEqual(admin.body.instances, []);
  assert.equal(admin.body.authority_revision, 1);

  fixture.setRole('member');
  const member = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/instances/?page=1&page_size=20',
  });
  assert.equal(member.status, 200);
  assert.equal(member.body.authority_revision, 2);
});

test('accessibility authority fixture exposes revisioned tenant Runtime Clusters', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const clusters = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/clusters/?page=1&page_size=1',
  });

  assert.equal(clusters.status, 200);
  assert.deepEqual(clusters.body.clusters, []);
  assert.equal(clusters.body.authority_revision, 1);
});

test('accessibility authority fixture exposes revisioned tenant Runtime Deployments', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const deployments = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/deploys/' +
      `?tenant_id=${scope.tenantId}&page=1&page_size=1`,
  });

  assert.equal(deployments.status, 200);
  assert.deepEqual(deployments.body.deploys, []);
  assert.equal(deployments.body.authority_revision, 1);
});

test('accessibility authority fixture exposes revisioned Instance Templates', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const templates = fixture.resolve({
    method: 'GET',
    url: 'http://127.0.0.1/api/v1/instance-templates/?page=1&page_size=1',
  });

  assert.equal(templates.status, 200);
  assert.deepEqual(templates.body.templates, []);
  assert.equal(templates.body.authority_revision, 1);
});

test('accessibility authority fixture exposes a revisioned Template marketplace snapshot', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const templates = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/subagents/templates/list' +
      `?tenant_id=${scope.tenantId}&limit=12&offset=0`,
  });

  assert.equal(templates.status, 200);
  assert.equal(templates.body.authority_revision, 1);
  assert.equal(templates.body.total, 0);
  assert.deepEqual(templates.body.templates, []);
  assert.deepEqual(templates.body.categories, []);
});

test('accessibility authority fixture exposes revisioned Skill Evolution reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const overview = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/skills/evolution/overview' +
      `?tenant_id=${scope.tenantId}`,
  });
  const config = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/skills/evolution/config' +
      `?tenant_id=${scope.tenantId}`,
  });

  assert.equal(overview.status, 200);
  assert.equal(overview.body.authority_revision, 1);
  assert.equal(overview.body.stats.total_sessions, 0);
  assert.deepEqual(overview.body.skills, []);
  assert.equal(config.status, 200);
  assert.equal(config.body.enabled, true);
  assert.equal(config.body.publish_mode, 'review');
});

test('accessibility authority fixture exposes scoped Workflow Patterns reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const patterns = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/agent/workflows/patterns' +
      `?tenant_id=${scope.tenantId}&page=1&page_size=50`,
  });

  assert.equal(patterns.status, 200);
  assert.deepEqual(patterns.body, {
    patterns: [],
    total: 0,
    page: 1,
    page_size: 50,
  });
});

test('accessibility authority fixture exposes revision-bound tenant task reads', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const authority = fixture.resolve({
    method: 'GET',
    url:
      'http://127.0.0.1/api/v1/tasks/authority-revision' +
      `?tenant_id=${scope.tenantId}`,
  });
  const stats = fixture.resolve({
    method: 'GET',
    url: `http://127.0.0.1/api/v1/tasks/stats?tenant_id=${scope.tenantId}`,
  });
  const recent = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/tasks/recent?tenant_id=${scope.tenantId}` +
      '&limit=1&offset=0',
  });

  assert.deepEqual(authority.body, {
    tenant_id: scope.tenantId,
    authority_revision: 1,
  });
  assert.equal(stats.body.total, 0);
  assert.deepEqual(recent.body, {
    tasks: [],
    total: 0,
    limit: 1,
    offset: 0,
    has_more: false,
  });
  assert.equal(
    fixture.resolve({
      method: 'GET',
      url: 'http://127.0.0.1/api/v1/tasks/stats?tenant_id=other-tenant',
    }),
    null,
  );
});

test('accessibility authority fixture exposes the Cloud tenant analytics contract', () => {
  const fixture = createAccessibilityAuthorityFixture(scope);
  const analytics = fixture.resolve({
    method: 'GET',
    url:
      `http://127.0.0.1/api/v1/tenants/${scope.tenantId}/analytics` +
      '?period=30d',
  });

  assert.equal(analytics.status, 200);
  assert.equal(analytics.body.authority_revision, 1);
  assert.deepEqual(analytics.body.memoryGrowth, []);
  assert.deepEqual(analytics.body.projectStorage, []);
  assert.deepEqual(analytics.body.summary, {
    total_memories: 0,
    total_storage_bytes: 0,
    total_projects: 0,
    period_days: 30,
  });
});
