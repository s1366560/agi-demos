import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
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
import { tenantAnalyticsOperationsV2Fixture } from './tenantAnalyticsOperationsV2Fixture.mjs';
import { tenantAgentBindingsOperationsV2Fixture } from './tenantAgentBindingsOperationsV2Fixture.mjs';
import { tenantProjectsOperationsV2Fixture } from './tenantProjectsOperationsV2Fixture.mjs';
import { tenantTasksOperationsV2Fixture } from './tenantTasksOperationsV2Fixture.mjs';
import { tenantAgentDashboardOperationsV2Fixture } from './tenantAgentDashboardOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');
const {
  DESKTOP_CAPABILITY_NAMES,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  createDesktopProductionRouteRegistry,
  registerDesktopProductionRouteLoaders,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const registrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);

const ROUTE_IDS = Object.freeze([
  'project-project-team',
  'project-project-memories',
  'project-project-entities',
  'project-project-communities',
  'project-project-graph',
]);
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

test('Project Knowledge production routes own real loaders and App bindings', () => {
  for (const routeId of ROUTE_IDS) {
    assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(routeId), true, routeId);
  }
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders(
      Object.fromEntries(
        ROUTE_IDS.map((routeId) => [routeId, implementedLoader(routeId)]),
      ),
    ),
  });
  for (const routeId of ROUTE_IDS) {
    assert.deepEqual(registry.byId.get(routeId)?.structuralReadiness, {
      status: 'ready',
    });
  }
  for (const symbol of [
    'createProjectTeamRouteModuleLoader',
    'createProjectMemoriesRouteModuleLoader',
    'createProjectEntitiesRouteModuleLoader',
    'createProjectCommunitiesRouteModuleLoader',
    'createProjectGraphRouteModuleLoader',
    'createProjectTeamController',
    'createProjectMemoriesController',
    'createProjectEntitiesController',
    'createProjectCommunitiesController',
    'createProjectGraphController',
  ]) {
    assert.match(registrySource, new RegExp(symbol, 'u'), symbol);
    assert.doesNotMatch(appSource, new RegExp(symbol, 'u'), symbol);
  }
  assert.doesNotMatch(
    registrySource,
    /project-knowledge[\s\S]{0,500}(?:WebView|<webview|<iframe|openExternal|window\.open)/iu,
  );
  assert.match(registrySource, /createDesktopProjectGraphClientV2/u);
  assert.match(registrySource, /createDesktopProjectCommunitiesClientV2/u);
  assert.match(registrySource, /createDesktopProjectEntitiesClientV2/u);
  assert.match(registrySource, /createDesktopProjectMemoriesClientV2/u);
  assert.match(registrySource, /createDesktopProjectTeamClientV2/u);
  assert.match(registrySource, /projectCommunitiesOperationsV2/u);
  assert.match(registrySource, /projectEntitiesOperationsV2/u);
  assert.match(registrySource, /projectGraphOperationsV2/u);
  assert.match(registrySource, /projectMemoriesOperationsV2/u);
  assert.match(registrySource, /projectTeamOperationsV2/u);
  assert.match(
    appSource,
    /projectCommunitiesOperationsV2:\s*desktopProjectCommunitiesOperationsV2/gu,
  );
  assert.match(
    appSource,
    /projectEntitiesOperationsV2:\s*desktopProjectEntitiesOperationsV2/gu,
  );
  assert.match(
    appSource,
    /projectGraphOperationsV2:\s*desktopProjectGraphOperationsV2/gu,
  );
  assert.match(
    appSource,
    /projectMemoriesOperationsV2:\s*desktopProjectMemoriesOperationsV2/gu,
  );
  assert.match(
    appSource,
    /projectTeamOperationsV2:\s*desktopProjectTeamOperationsV2/gu,
  );
  assert.doesNotMatch(registrySource, /createProjectGraphClient/u);
  assert.doesNotMatch(registrySource, /createProjectCommunitiesClient/u);
  assert.doesNotMatch(registrySource, /createProjectEntitiesClient/u);
  assert.doesNotMatch(registrySource, /createProjectMemoriesClient/u);
  assert.doesNotMatch(registrySource, /createProjectTeamClient/u);
});

test('Cloud Snapshot v4 observes all five scoped Project Knowledge authorities', async () => {
  const snapshot = await loadSnapshot(
    cloudConfig,
    projectTeamOperationsV2Fixture({ scopeRevision: 7 }),
    projectMemoriesOperationsV2Fixture({ scopeRevision: 7 }),
    projectEntitiesOperationsV2Fixture({ scopeRevision: 7 }),
    projectCommunitiesOperationsV2Fixture({ scopeRevision: 7 }),
    projectGraphOperationsV2Fixture({ scopeRevision: 7 }),
  );

  for (const routeId of ROUTE_IDS) {
    const capability = snapshot.capabilities[routeId];
    assert.equal(capability.provenance, 'observed', routeId);
    assert.equal(capability.authority_source, 'cloud_service', routeId);
    assert.equal(capability.scope.tenant_id, 'tenant-1', routeId);
    assert.equal(capability.scope.project_id, 'project-1', routeId);
    assert.equal(capability.contract_version, '4.0.0', routeId);
  }
  assert.deepEqual(pick(snapshot, 'project-project-team'), {
    availability: 'degraded',
    reason_code: 'desktop_project_team_actions_partial',
    allowed_actions: ['view', 'list-members', 'list-agent-teammates'],
  });
  assert.deepEqual(pick(snapshot, 'project-project-memories'), {
    availability: 'degraded',
    reason_code: 'desktop_project_memories_actions_partial',
    allowed_actions: ['view', 'list'],
  });
  assert.deepEqual(pick(snapshot, 'project-project-entities'), {
    availability: 'degraded',
    reason_code: 'desktop_project_entities_actions_partial',
    allowed_actions: ['view', 'list'],
  });
  assert.deepEqual(pick(snapshot, 'project-project-communities'), {
    availability: 'degraded',
    reason_code: 'desktop_project_communities_actions_partial',
    allowed_actions: ['view', 'list'],
  });
  assert.deepEqual(pick(snapshot, 'project-project-graph'), {
    availability: 'degraded',
    reason_code: 'desktop_project_graph_actions_partial',
    allowed_actions: ['view'],
  });
});

test('Local Snapshot keeps Project Knowledge unavailable until sidecar authority is observed', async () => {
  let loadCalls = 0;
  const teamOperations = {
    async loadProjectTeam() {
      loadCalls += 1;
      throw new Error('Local Team V2 authority must not be probed');
    },
  };
  const graphOperations = {
    async loadProjectGraph() {
      loadCalls += 1;
      throw new Error('Local Graph V2 authority must not be probed');
    },
  };
  const entitiesOperations = {
    async loadProjectEntities() {
      loadCalls += 1;
      throw new Error('Local Entities V2 authority must not be probed');
    },
    async loadProjectEntityRelationships() {
      loadCalls += 1;
      throw new Error('Local Entities V2 authority must not be probed');
    },
  };
  const communitiesOperations = {
    async loadProjectCommunities() {
      loadCalls += 1;
      throw new Error('Local Communities V2 authority must not be probed');
    },
  };
  const memoriesOperations = {
    async loadProjectMemories() {
      loadCalls += 1;
      throw new Error('Local Memories V2 authority must not be probed');
    },
  };
  const snapshot = await loadSnapshot(
    { ...cloudConfig, mode: 'local', localApiToken: 'private-launch' },
    teamOperations,
    memoriesOperations,
    entitiesOperations,
    communitiesOperations,
    graphOperations,
  );
  const reasons = {
    'project-project-team': 'local_project_team_authority_unavailable',
    'project-project-memories': 'local_project_memories_authority_unavailable',
    'project-project-entities': 'local_project_entities_authority_unavailable',
    'project-project-communities': 'local_project_communities_authority_unavailable',
    'project-project-graph': 'local_project_graph_authority_unavailable',
  };
  for (const routeId of ROUTE_IDS) {
    const capability = snapshot.capabilities[routeId];
    assert.equal(capability.availability, 'unavailable', routeId);
    assert.equal(capability.reason_code, reasons[routeId], routeId);
    assert.equal(capability.provenance, 'declared', routeId);
    assert.equal(capability.authority_source, 'renderer', routeId);
    assert.deepEqual(capability.allowed_actions, [], routeId);
  }
  assert.equal(loadCalls, 0);
});

test('Capability catalog contains every Project Knowledge ID exactly once per declaration', () => {
  for (const routeId of ROUTE_IDS) {
    assert.equal(DESKTOP_CAPABILITY_NAMES.includes(routeId), true, routeId);
  }
});

async function loadSnapshot(
  config,
  projectTeamOperationsV2,
  projectMemoriesOperationsV2,
  projectEntitiesOperationsV2,
  projectCommunitiesOperationsV2,
  projectGraphOperationsV2,
) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ reason_code: 'unrelated_authority_unavailable' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    });
  try {
    return await createDesktopWorkbenchCapabilityClient(
      {
        async getAutomationCapabilities() {
          throw new Error('unrelated authority unavailable');
        },
      },
      config,
      {
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
        projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
        projectCommunitiesOperationsV2,
        projectTeamOperationsV2,
        projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
        projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
        projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
        projectMemoriesOperationsV2,
        projectEntitiesOperationsV2,
        projectGraphOperationsV2,
        projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
        projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
        runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
        runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
        runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
        projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
        tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

        tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
        tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
      },
    ).loadSnapshot();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function implementedLoader(routeId) {
  return async () => ({
    routeId,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: routeId,
    localPolicy: 'native_equivalent',
    Surface: () => null,
  });
}

function pick(snapshot, routeId) {
  const capability = snapshot.capabilities[routeId];
  return {
    availability: capability.availability,
    reason_code: capability.reason_code,
    allowed_actions: [...capability.allowed_actions],
  };
}
