import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiled = '/tmp/agistack-project-agent-test-dist/src/features/project-agent';
const { PROJECT_AGENT_CAPABILITY_IDS, loadProjectAgentCapabilities } = require(
  `${compiled}/projectAgentCapabilityAuthority.js`,
);

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
});

test('Project Agent capability authority observes scoped Cloud clients', async () => {
  const projection = await loadProjectAgentCapabilities(clients('cloud'), cloudConfig);
  for (const routeId of PROJECT_AGENT_CAPABILITY_IDS) {
    assert.equal(projection[routeId].availability, 'available', routeId);
    assert.equal(projection[routeId].authority_revision, 11, routeId);
    assert.equal(projection[routeId].contract_version, '4.0.0', routeId);
    assert.deepEqual(projection[routeId].scope, {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
    });
  }
});

test('Project Agent capability authority declares stable Local unavailability without loading', async () => {
  let calls = 0;
  const localClients = Object.fromEntries(
    PROJECT_AGENT_CAPABILITY_IDS.map((routeId) => [
      routeId,
      {
        async load() {
          calls += 1;
          throw new Error('Local authority must fail before network access');
        },
      },
    ]),
  );
  const projection = await loadProjectAgentCapabilities(localClients, {
    ...cloudConfig,
    mode: 'local',
    localApiToken: 'private-launch',
  });
  assert.equal(calls, 0);
  assert.equal(
    projection['project-agent-dashboard'].reason_code,
    'local_project_agent_dashboard_authority_unavailable',
  );
  assert.equal(
    projection['project-agent-logs'].reason_code,
    'local_project_agent_logs_authority_unavailable',
  );
  assert.equal(
    projection['project-agent-patterns'].reason_code,
    'local_project_agent_patterns_authority_unavailable',
  );
});

test('Project Agent capability authority rejects mismatched observations', async () => {
  const mismatched = clients('cloud');
  mismatched['project-agent-logs'] = {
    async load() {
      return snapshot('cloud', { projectId: 'other-project' });
    },
  };
  const projection = await loadProjectAgentCapabilities(mismatched, cloudConfig);
  assert.equal(
    projection['project-agent-logs'].reason_code,
    'project_agent_logs_authority_contract_invalid',
  );
});

function clients(authority) {
  return Object.fromEntries(
    PROJECT_AGENT_CAPABILITY_IDS.map((routeId) => [
      routeId,
      {
        async load() {
          return snapshot(authority);
        },
      },
    ]),
  );
}

function snapshot(authority, overrides = {}) {
  return {
    scope: {
      authority,
      tenantId: 'tenant-1',
      projectId: 'project-1',
      ...overrides,
    },
    scopeRevision: 11,
    authority,
    availability: 'available',
    reasonCode: null,
    allowedActions: ['view'],
  };
}
