import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceRosterClientProviderV2,
  DesktopWorkspaceRosterClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceRosterClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace roster client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceRosterClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopWorkspaceRosterClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_workspace_roster_client_unpublished');
      assert.equal(error.message, 'desktop_workspace_roster_client_unpublished');
      return true;
    },
  );
});

test('publications and operation bindings pin frozen two-method workspace roster clients', async () => {
  const provider = createDesktopWorkspaceRosterClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:43901',
    'publication-session',
    'publication-launch',
    'tenant-1',
    'project-1',
    'workspace-1',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43902',
    'operation-session',
    'operation-launch',
    'tenant / operation',
    'project / operation',
    'workspace / operation',
  );
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiKey = 'mutated-session';
  operationConfig.localApiToken = 'mutated-launch';
  operationConfig.tenantId = 'mutated-tenant';
  operationConfig.projectId = 'mutated-project';
  operationConfig.workspaceId = 'mutated-workspace';
  const next = provider.publish({
    config: runtimeConfig(
      'http://127.0.0.1:43903',
      'next-session',
      'next-launch',
      'tenant-2',
      'project-2',
      'workspace-2',
    ),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    const payload = url.pathname.endsWith('/members')
      ? [workspaceMember('workspace / operation')]
      : [workspaceAgent('workspace / operation')];
    return json(payload);
  };

  try {
    const [members, agents] = await Promise.all([
      operationClient.listWorkspaceMembers(controller.signal),
      operationClient.listWorkspaceAgents(controller.signal),
    ]);

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(next), true);
    assert.notEqual(publication, next);
    assert.notEqual(publication.client, next.client);
    assert.equal(provider.resolve(), next);
    assert.deepEqual(Object.keys(publication.client), [
      'listWorkspaceMembers',
      'listWorkspaceAgents',
    ]);
    assert.deepEqual(Object.keys(operationClient), [
      'listWorkspaceMembers',
      'listWorkspaceAgents',
    ]);
    assert.equal(members[0].user_email, 'member@example.com');
    assert.equal(agents[0].display_name, 'Planner');
    assert.equal(calls.length, 2);
    assert.deepEqual(
      calls.map(({ url }) => `${url.pathname}?${url.searchParams.toString()}`).sort(),
      [
        '/api/v1/tenants/tenant%20%2F%20operation/projects/project%20%2F%20operation/' +
          'workspaces/workspace%20%2F%20operation/agents?active_only=false&limit=500&offset=0',
        '/api/v1/tenants/tenant%20%2F%20operation/projects/project%20%2F%20operation/' +
          'workspaces/workspace%20%2F%20operation/members?limit=500&offset=0',
      ],
    );
    for (const call of calls) {
      assert.equal(call.url.origin, 'http://127.0.0.1:43902');
      assert.equal(call.init.signal, controller.signal);
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer operation-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed workspace roster publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceRosterClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_roster_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_roster_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(
  apiBaseUrl,
  apiKey,
  localApiToken,
  tenantId,
  projectId,
  workspaceId,
) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    apiKey,
    localApiToken,
    tenantId,
    projectId,
    workspaceId,
    mode: 'local',
  };
}

function workspaceMember(workspaceId) {
  return {
    id: 'member-1',
    workspace_id: workspaceId,
    user_id: 'user-1',
    user_email: 'member@example.com',
    role: 'owner',
    invited_by: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: null,
  };
}

function workspaceAgent(workspaceId) {
  return {
    id: 'binding-1',
    workspace_id: workspaceId,
    agent_id: 'agent-1',
    display_name: 'Planner',
    description: null,
    config: {},
    is_active: true,
    hex_q: null,
    hex_r: null,
    theme_color: null,
    label: null,
    status: 'idle',
    created_at: '2026-09-01T00:00:00Z',
    updated_at: null,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
