import { tenantSkillDefinitionsOperationsV2Fixture } from './tenantSkillOperationsV2Fixture.mjs';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

import { projectOverviewOperationsV2Fixture } from './projectOverviewOperationsV2Fixture.mjs';
import { projectAgentDashboardOperationsV2Fixture } from './projectAgentDashboardOperationsV2Fixture.mjs';
import { projectAgentLogsOperationsV2Fixture } from './projectAgentLogsOperationsV2Fixture.mjs';
import { projectAgentPatternsOperationsV2Fixture } from './projectAgentPatternsOperationsV2Fixture.mjs';
import { projectCommunitiesOperationsV2Fixture } from './projectCommunitiesOperationsV2Fixture.mjs';
import { projectMemoriesOperationsV2Fixture } from './projectMemoriesOperationsV2Fixture.mjs';
import { projectTeamOperationsV2Fixture } from './projectTeamOperationsV2Fixture.mjs';
import { projectSchemaOperationsV2Fixture } from './projectSchemaOperationsV2Fixture.mjs';
import { projectMaintenanceOperationsV2Fixture } from './projectMaintenanceOperationsV2Fixture.mjs';
import { projectSettingsOperationsV2Fixture } from './projectSettingsOperationsV2Fixture.mjs';
import { projectEntitiesOperationsV2Fixture } from './projectEntitiesOperationsV2Fixture.mjs';
import { projectGraphOperationsV2Fixture } from './projectGraphOperationsV2Fixture.mjs';
import { projectBlackboardOperationsV2Fixture } from './projectBlackboardOperationsV2Fixture.mjs';
import { projectWorkspacesClientV2Fixture } from './projectWorkspacesClientV2Fixture.mjs';
import { runtimePoolOperationsV2Fixture } from './runtimePoolOperationsV2Fixture.mjs';
import { runtimeClustersOperationsV2Fixture } from './runtimeClustersOperationsV2Fixture.mjs';
import { runtimeInstancesOperationsV2Fixture } from './runtimeInstancesOperationsV2Fixture.mjs';
import { runtimeDeploymentsOperationsV2Fixture } from './runtimeDeploymentsOperationsV2Fixture.mjs';
import { tenantAnalyticsOperationsV2Fixture } from './tenantAnalyticsOperationsV2Fixture.mjs';
import { tenantAgentBindingsOperationsV2Fixture } from './tenantAgentBindingsOperationsV2Fixture.mjs';
import { tenantProjectsOperationsV2Fixture } from './tenantProjectsOperationsV2Fixture.mjs';
import { tenantTasksOperationsV2Fixture } from './tenantTasksOperationsV2Fixture.mjs';
import { tenantAgentDashboardOperationsV2Fixture } from './tenantAgentDashboardOperationsV2Fixture.mjs';
import { tenantAgentDefinitionsOperationsV2Fixture } from './tenantAgentDefinitionsOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const {
  createAgentWorkspaceAuthorityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/agent-workspace/agentWorkspaceAuthorityClient.js');
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
  workspaceRoot: '/workspace',
});

test('Agent Workspace authority observes the scoped Cloud conversation catalog', async () => {
  const calls = [];
  await withFetch(
    async (input, init) => {
      calls.push({ input: String(input), init });
      return pageResponse();
    },
    async () => {
      const observation = await createAgentWorkspaceAuthorityClient(cloudConfig).probe();
      assert.deepEqual(observation, expectedObservation('cloud'));
    },
  );

  assert.equal(
    calls[0]?.input,
    'https://cloud.memstack.test/api/v1/agent/conversations' +
      '?project_id=project-1&status=active&limit=1&offset=0',
  );
  const headers = new Headers(calls[0]?.init?.headers);
  assert.equal(headers.get('Authorization'), 'Bearer trusted-session');
  assert.equal(headers.get('X-Agistack-Launch'), null);
  assert.equal(calls[0]?.init?.credentials, 'omit');
});

test('Agent Workspace authority keeps Local launch authority separate from the session', async () => {
  const config = Object.freeze({
    ...cloudConfig,
    apiBaseUrl: 'http://127.0.0.1:4777',
    apiKey: 'local-session',
    localApiToken: 'private-launch',
    mode: 'local',
  });
  let headers = null;
  await withFetch(
    async (_input, init) => {
      headers = new Headers(init?.headers);
      return pageResponse();
    },
    async () => {
      const observation = await createAgentWorkspaceAuthorityClient(config).probe();
      assert.deepEqual(observation, expectedObservation('local'));
    },
  );
  assert.equal(headers.get('Authorization'), 'Bearer local-session');
  assert.equal(headers.get('X-Agistack-Launch'), 'private-launch');
});

test('Workbench fails closed when Agent Workspace authority has no revision', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response('{}', { status: 503 });
  try {
    for (const [mode, authoritySource] of [
      ['cloud', 'cloud_service'],
      ['local', 'sidecar'],
    ]) {
      const config = Object.freeze({
        ...cloudConfig,
        mode,
        localApiToken: mode === 'local' ? 'private-launch' : '',
      });
      const client = createDesktopWorkbenchCapabilityClient(
        {
          async getAutomationCapabilities() {
            throw new Error('unrelated authority unavailable');
          },
        },
        config,
        {
          projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
          tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2Fixture(),
          tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2Fixture(),
          projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
          projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
          projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
          projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
          projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
          projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
          projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
          projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
          projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
          projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
          projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
          projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
          runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
          runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
          runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
          runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
          instanceTemplatesOperationsV2: {
            async probe({ config }) {
              return config.mode === 'local'
                ? {
                    availability: 'not_applicable',
                    reasonCode: 'local_instance_template_authority_unavailable',
                    allowedActions: [],
                    authorityRevision: null,
                  }
                : {
                    availability: 'available',
                    reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
                    allowedActions: ['view', 'list', 'create', 'delete', 'publish', 'clone'],
                    authorityRevision: null,
                  };
            },
          },
          deadLetterQueueOperationsV2: {
            async probe({ config }) {
              return config.mode === 'local'
                ? {
                    availability: 'not_applicable',
                    reasonCode: 'cloud_message_bus_dlq_not_applicable',
                    allowedActions: [],
                    authorityRevision: null,
                  }
                : {
                    availability: 'available',
                    reasonCode: null,
                    allowedActions: ['view', 'list'],
                    authorityRevision: null,
                  };
            },
          },
          backendStoresOperationsV2: {
            async probeBackendStores({ config }) {
              return config.mode === 'local'
                ? {
                    availability: 'not_applicable',
                    reasonCode: 'local_backend_stores_cloud_authority_unavailable',
                    allowedActions: [],
                    authorityRevision: null,
                  }
                : {
                    availability: 'available',
                    reasonCode: null,
                    allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
                    authorityRevision: 23,
                  };
            },
          },
          projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          agentWorkspaceClient: {
            async probe() {
              return expectedObservation(mode);
            },
          },
        },
      );
      const snapshot = await client.loadSnapshot();
      assert.deepEqual(snapshot.capabilities['agent-workspace-tenant-agent-workspace'], {
        availability: 'unavailable',
        reason_code: 'capability_authority_revision_unavailable',
        service_version: '0.1.0',
        contract_version: '4.0.0',
        allowed_actions: [],
        scope: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          workspace_id: 'workspace-1',
          instance_id: null,
        },
        authority_revision: null,
        retryable: false,
        authority_source: authoritySource,
        supporting_authority_sources: [],
        provenance: 'observed',
      });
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Workbench consumes the revision-bound journey authority in production', async () => {
  const client = createDesktopWorkbenchCapabilityClient(
    {
      async getAutomationCapabilities() {
        throw new Error('unrelated authority unavailable');
      },
    },
    cloudConfig,
    {
      projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
      tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2Fixture(),
      tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2Fixture(),
      projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
      projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
      projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
      projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
      projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
      projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
      projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
      projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
      projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
      projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
      projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
      projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
      runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
      runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
      runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
      runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
      instanceTemplatesOperationsV2: {
        async probe({ config }) {
          return config.mode === 'local'
            ? {
                availability: 'not_applicable',
                reasonCode: 'local_instance_template_authority_unavailable',
                allowedActions: [],
                authorityRevision: null,
              }
            : {
                availability: 'available',
                reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
                allowedActions: ['view', 'list', 'create', 'delete', 'publish', 'clone'],
                authorityRevision: null,
              };
        },
      },
      deadLetterQueueOperationsV2: {
        async probe({ config }) {
          return config.mode === 'local'
            ? {
                availability: 'not_applicable',
                reasonCode: 'cloud_message_bus_dlq_not_applicable',
                allowedActions: [],
                authorityRevision: null,
              }
            : {
                availability: 'available',
                reasonCode: null,
                allowedActions: ['view', 'list'],
                authorityRevision: null,
              };
        },
      },
      backendStoresOperationsV2: {
        async probeBackendStores({ config }) {
          return config.mode === 'local'
            ? {
                availability: 'not_applicable',
                reasonCode: 'local_backend_stores_cloud_authority_unavailable',
                allowedActions: [],
                authorityRevision: null,
              }
            : {
                availability: 'available',
                reasonCode: null,
                allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
                authorityRevision: 23,
              };
        },
      },
      projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
      tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

      tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
      tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
      tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
      tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
      agentWorkspaceJourneyClient: {
        async probe() {
          return journeySnapshot();
        },
      },
    },
  );
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response('{}', { status: 503 });
  try {
    const snapshot = await client.loadSnapshot();
    assert.deepEqual(snapshot.capabilities['agent-workspace-tenant-agent-workspace'], {
      availability: 'degraded',
      reason_code: 'agent_workspace_journeys_partial',
      service_version: '0.1.0',
      contract_version: '4.0.0',
      allowed_actions: ['list-conversations', 'restore-session'],
      scope: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: 'workspace-1',
        instance_id: null,
      },
      authority_revision: 7,
      retryable: false,
      authority_source: 'cloud_service',
      supporting_authority_sources: [],
      provenance: 'observed',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Workbench default production journey authority supports tenant-level scope', async () => {
  const calls = [];
  const config = Object.freeze({ ...cloudConfig, workspaceId: '' });
  await withFetch(productionJourneyFetch(calls), async () => {
    const client = createDesktopWorkbenchCapabilityClient(
      {
        async getAutomationCapabilities() {
          throw new Error('unrelated authority unavailable');
        },
      },
      config,
      {
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2Fixture(),
        tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2Fixture(),
        projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
        projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
        projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
        projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
        projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
        projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
        projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
        projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
        projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
        projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
        projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
        projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
        runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
        runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
        runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
        runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
        instanceTemplatesOperationsV2: {
          async probe({ config }) {
            return config.mode === 'local'
              ? {
                  availability: 'not_applicable',
                  reasonCode: 'local_instance_template_authority_unavailable',
                  allowedActions: [],
                  authorityRevision: null,
                }
              : {
                  availability: 'available',
                  reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
                  allowedActions: ['view', 'list', 'create', 'delete', 'publish', 'clone'],
                  authorityRevision: null,
                };
          },
        },
        deadLetterQueueOperationsV2: {
          async probe({ config }) {
            return config.mode === 'local'
              ? {
                  availability: 'not_applicable',
                  reasonCode: 'cloud_message_bus_dlq_not_applicable',
                  allowedActions: [],
                  authorityRevision: null,
                }
              : {
                  availability: 'available',
                  reasonCode: null,
                  allowedActions: ['view', 'list'],
                  authorityRevision: null,
                };
          },
        },
        backendStoresOperationsV2: {
          async probeBackendStores({ config }) {
            return config.mode === 'local'
              ? {
                  availability: 'not_applicable',
                  reasonCode: 'local_backend_stores_cloud_authority_unavailable',
                  allowedActions: [],
                  authorityRevision: null,
                }
              : {
                  availability: 'available',
                  reasonCode: null,
                  allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
                  authorityRevision: 23,
                };
          },
        },
        projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
        tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

        tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
        tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
      },
    );
    const snapshot = await client.loadSnapshot();
    const capability = snapshot.capabilities['agent-workspace-tenant-agent-workspace'];

    assert.equal(capability.availability, 'degraded');
    assert.equal(capability.reason_code, 'agent_workspace_journeys_partial');
    assert.equal(capability.authority_revision, 1);
    assert.equal(capability.authority_source, 'cloud_service');
    assert.equal(capability.provenance, 'observed');
    assert.deepEqual(capability.scope, {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
    });
    assert.ok(capability.allowed_actions.includes('restore-session'));
    assert.ok(capability.allowed_actions.includes('list-conversations'));
  });

  const catalog = calls.find(
    (call) => new URL(call.input).pathname === '/api/v1/agent/conversations',
  );
  assert.ok(catalog);
  assert.equal(new URL(catalog.input).searchParams.get('workspace_id'), null);
});

test('Agent Workspace scope and authority failures stay unavailable with stable reasons', async () => {
  assert.throws(
    () =>
      createAgentWorkspaceAuthorityClient({
        ...cloudConfig,
        projectId: '',
        workspaceId: '',
      }),
    /agent_workspace_scope_unavailable/u,
  );
  let probeCount = 0;
  const client = createDesktopWorkbenchCapabilityClient(
    {
      async getAutomationCapabilities() {
        throw new Error('unrelated authority unavailable');
      },
    },
    cloudConfig,
    {
      projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
      tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2Fixture(),
      tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2Fixture(),
      projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
      projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
      projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
      projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
      projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
      projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
      projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
      projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
      projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
      projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
      projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
      projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
      runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
      runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
      runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
      runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
      instanceTemplatesOperationsV2: {
        async probe({ config }) {
          return config.mode === 'local'
            ? {
                availability: 'not_applicable',
                reasonCode: 'local_instance_template_authority_unavailable',
                allowedActions: [],
                authorityRevision: null,
              }
            : {
                availability: 'available',
                reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
                allowedActions: ['view', 'list', 'create', 'delete', 'publish', 'clone'],
                authorityRevision: null,
              };
        },
      },
      deadLetterQueueOperationsV2: {
        async probe({ config }) {
          return config.mode === 'local'
            ? {
                availability: 'not_applicable',
                reasonCode: 'cloud_message_bus_dlq_not_applicable',
                allowedActions: [],
                authorityRevision: null,
              }
            : {
                availability: 'available',
                reasonCode: null,
                allowedActions: ['view', 'list'],
                authorityRevision: null,
              };
        },
      },
      backendStoresOperationsV2: {
        async probeBackendStores({ config }) {
          return config.mode === 'local'
            ? {
                availability: 'not_applicable',
                reasonCode: 'local_backend_stores_cloud_authority_unavailable',
                allowedActions: [],
                authorityRevision: null,
              }
            : {
                availability: 'available',
                reasonCode: null,
                allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
                authorityRevision: 23,
              };
        },
      },
      projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
      tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

      tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
      tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
      tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
      tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
      agentWorkspaceClient: {
        async probe() {
          probeCount += 1;
          throw new Error('authority unavailable');
        },
      },
    },
  );
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response('{}', { status: 503 });
  try {
    const snapshot = await client.loadSnapshot();
    assert.equal(probeCount, 1);
    assert.deepEqual(snapshot.capabilities['agent-workspace-tenant-agent-workspace'], {
      availability: 'unavailable',
      reason_code: 'agent_workspace_authority_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: 'workspace-1',
        instance_id: null,
      },
      authority_revision: null,
      retryable: false,
      authority_source: 'cloud_service',
      supporting_authority_sources: [],
      provenance: 'observed',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

function expectedObservation(authority) {
  return {
    authority,
    availability: authority === 'cloud' ? 'available' : 'degraded',
    reasonCode: authority === 'cloud' ? null : 'local_cloud_agent_authority_unavailable',
    serviceVersion: '0.1.0',
    contractVersion: '4.0.0',
    allowedActions: ['view', 'list-conversations'],
    scope: {
      authority,
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    },
    authorityRevision: null,
  };
}

function journeySnapshot() {
  const unavailable = {
    availability: 'unavailable',
    reasonCode: 'agent_workspace_journey_empty',
    observedActions: [],
  };
  return {
    authority: 'cloud',
    authoritySource: 'cloud_service',
    provenance: 'observed',
    authorityRevision: 7,
    scope: {
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    },
    journeys: {
      'bootstrap-and-scope': {
        availability: 'degraded',
        reasonCode: 'agent_workspace_journey_bootstrap_and_scope_partial',
        observedActions: ['restore-session'],
      },
      'conversation-lifecycle': {
        availability: 'degraded',
        reasonCode: 'agent_workspace_journey_conversation_lifecycle_partial',
        observedActions: ['list-conversations'],
      },
      'stream-and-run-control': unavailable,
      'hitl-and-a2ui': unavailable,
      'roster-and-subagents': unavailable,
      'work-review': unavailable,
      'content-and-export': unavailable,
      'local-runtime': unavailable,
    },
  };
}

function pageResponse() {
  return new Response(
    JSON.stringify({
      items: [],
      total: 0,
      has_more: false,
      offset: 0,
      limit: 1,
      next_offset: null,
    }),
    { status: 200, headers: { 'content-type': 'application/json' } },
  );
}

function productionJourneyFetch(calls) {
  return async (input, init) => {
    calls.push({ input: String(input), init });
    const url = new URL(String(input));
    const path = url.pathname;
    const payloadByPath = {
      '/api/v1/auth/me': {
        user_id: 'user-1',
        email: 'user@example.test',
        is_active: true,
      },
      '/api/v1/workspace-context': {
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 1,
          updated_at: '2026-08-05T00:00:00Z',
        },
        membership_role: 'owner',
      },
      '/api/v1/system/features': [],
      '/api/v1/tenants/': {
        tenants: [{ id: 'tenant-1', name: 'Tenant' }],
        total: 1,
        page: 1,
        page_size: 100,
      },
      '/api/v1/projects/': {
        projects: [{ id: 'project-1', tenant_id: 'tenant-1', name: 'Project' }],
        total: 1,
        page: 1,
        page_size: 100,
      },
      '/api/v1/agent/conversations': {
        items: [],
        total: 0,
        has_more: false,
        offset: 0,
        limit: 1,
        next_offset: null,
      },
      '/api/v1/projects/project-1/my-work': {
        project_id: 'project-1',
        items: [],
        total: 0,
      },
      '/api/v1/projects/project-1/activity/read-state': {
        project_id: 'project-1',
        authority_revision: 0,
        entries: [],
      },
      '/api/v1/artifacts': { artifacts: [], total: 0 },
      '/api/v1/projects/project-1/sandbox/capabilities': {
        terminal_interactive: { availability: 'unavailable' },
        kasm_vnc: { availability: 'unavailable' },
      },
      '/api/v1/projects/project-1/sandbox': {
        project_id: 'project-1',
        status: 'unavailable',
        is_healthy: false,
        terminal_url: null,
        desktop_url: null,
      },
    };
    if (Object.hasOwn(payloadByPath, path)) {
      return new Response(JSON.stringify(payloadByPath[path]), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(JSON.stringify({ detail: 'unavailable' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    });
  };
}

async function withFetch(fetchImplementation, operation) {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = fetchImplementation;
  try {
    return await operation();
  } finally {
    globalThis.fetch = previousFetch;
  }
}
