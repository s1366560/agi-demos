import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

import { projectOverviewOperationsV2Fixture } from './projectOverviewOperationsV2Fixture.mjs';
import { projectAgentDashboardOperationsV2Fixture } from './projectAgentDashboardOperationsV2Fixture.mjs';
import { projectAgentLogsOperationsV2Fixture } from './projectAgentLogsOperationsV2Fixture.mjs';
import { projectAgentPatternsOperationsV2Fixture } from './projectAgentPatternsOperationsV2Fixture.mjs';
import { projectEntitiesOperationsV2Fixture } from './projectEntitiesOperationsV2Fixture.mjs';
import { projectGraphOperationsV2Fixture } from './projectGraphOperationsV2Fixture.mjs';
import { projectBlackboardOperationsV2Fixture } from './projectBlackboardOperationsV2Fixture.mjs';
import { projectWorkspacesClientV2Fixture } from './projectWorkspacesClientV2Fixture.mjs';
import { runtimePoolOperationsV2Fixture } from './runtimePoolOperationsV2Fixture.mjs';
import { tenantAnalyticsOperationsV2Fixture } from './tenantAnalyticsOperationsV2Fixture.mjs';
import { tenantAgentBindingsOperationsV2Fixture } from './tenantAgentBindingsOperationsV2Fixture.mjs';
import { tenantProjectsOperationsV2Fixture } from './tenantProjectsOperationsV2Fixture.mjs';
import { tenantTasksOperationsV2Fixture } from './tenantTasksOperationsV2Fixture.mjs';
import { tenantAgentDashboardOperationsV2Fixture } from './tenantAgentDashboardOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const {
  CANONICAL_DESKTOP_ROUTE_IDS,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopCanonicalRouteCatalog.js');
const {
  AGENT_WORKSPACE_ROUTE_ID,
} = require('/tmp/agistack-desktop-test-dist/src/features/agent-workspace/agentWorkspaceRouteModule.js');
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  BACKEND_STORES_ROUTE_ID,
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
  PROJECT_PLAYBOOKS_ROUTE_ID,
  PROJECT_SUPPORT_ROUTE_ID,
  TENANT_CREATION_ROUTE_ID,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');
const {
  DESKTOP_CAPABILITY_NAMES,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const localRouteContract = JSON.parse(
  readFileSync(new URL('../contracts/local-route-parity.v1.json', import.meta.url), 'utf8'),
);

const AUXILIARY_PRODUCTION_ROUTE_IDS = [
  PROJECT_SUPPORT_ROUTE_ID,
  BACKEND_STORES_ROUTE_ID,
  PROJECT_PLAYBOOKS_ROUTE_ID,
  DEVICE_APPROVAL_ROUTE_ID,
  TENANT_CREATION_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
];

test('production registry and runtime snapshot close route ownership without implying implementation', () => {
  const productionRouteIds = new Set([
    ...CANONICAL_DESKTOP_ROUTE_IDS,
    ...AUXILIARY_PRODUCTION_ROUTE_IDS,
  ]);
  const snapshotRouteIds = DESKTOP_CAPABILITY_NAMES.filter((name) => productionRouteIds.has(name));

  assert.equal(CANONICAL_DESKTOP_ROUTE_IDS.includes(AGENT_WORKSPACE_ROUTE_ID), true);
  assert.deepEqual([...snapshotRouteIds].sort(), [...productionRouteIds].sort());
  for (const routeId of DESKTOP_IMPLEMENTED_ROUTE_IDS) {
    assert.equal(productionRouteIds.has(routeId), true, routeId);
  }
  assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes('tenant-tenant-workspaces'), true);
  assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(AGENT_WORKSPACE_ROUTE_ID), true);
});

test('runtime snapshot declares tenant workspaces and canonical Agent Workspace authority', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ unavailable: true }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    });

  try {
    const client = createDesktopWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => {
          throw new Error('automation unavailable');
        },
      },
      {
        ...DEFAULT_CONFIG,
        mode: 'local',
        tenantId: 'local',
        projectId: 'local-project',
      },
      {
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
        projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
        projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
        projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
        projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
        projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
        runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
        projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
        tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

        tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
        tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
      },
    );
    const snapshot = await client.loadSnapshot();

    assert.deepEqual(snapshot.capabilities['tenant-tenant-workspaces'], {
      availability: 'unavailable',
      reason_code: 'renderer_capability_authority_unobserved',
      service_version: '0.1.0',
      contract_version: '3.0.0',
      allowed_actions: [],
      scope: {
        tenant_id: 'local',
        project_id: 'local-project',
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: null,
      retryable: false,
      authority_source: 'renderer',
      supporting_authority_sources: [],
      provenance: 'declared',
    });
    assert.notEqual(
      snapshot.capabilities[AGENT_WORKSPACE_ROUTE_ID].reason_code,
      'capability_not_declared',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Local route inventory owns both tenant workspace collection methods', () => {
  const routes = localRouteContract.routes.filter(({ area }) => area === 'tenant_workspaces');
  assert.deepEqual(
    routes.map(({ method, uri, authority }) => ({
      method,
      uri,
      authority,
    })),
    [
      {
        method: 'GET',
        uri: '/api/v1/tenants/local/projects/local-project/workspaces?limit=500&offset=0',
        authority: 'local_workspace_catalog',
      },
      {
        method: 'POST',
        uri: '/api/v1/tenants/local/projects/local-project/workspaces',
        authority: 'local_workspace_catalog',
      },
    ],
  );
});
