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
require.extensions['.css'] = () => {};
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');
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
const routeIds = Object.freeze([
  'project-agent-dashboard',
  'project-agent-logs',
  'project-agent-patterns',
]);
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

test('Project Agent production routes own native loaders and App bindings', async () => {
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders(
      Object.fromEntries(
        routeIds.map((routeId) => [routeId, implementedLoader(routeId)]),
      ),
    ),
  });
  for (const routeId of routeIds) {
    assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(routeId), true, routeId);
    assert.deepEqual(registry.byId.get(routeId)?.structuralReadiness, {
      status: 'ready',
    });
    assert.equal((await registry.byId.get(routeId).loader()).localPolicy, 'native_equivalent');
  }
  for (const symbol of [
    'createProjectAgentDashboardRouteModuleLoader',
    'createProjectAgentLogsRouteModuleLoader',
    'createProjectAgentPatternsRouteModuleLoader',
    'createProjectAgentDashboardController',
    'createProjectAgentLogsController',
    'createProjectAgentPatternsController',
  ]) {
    assert.match(registrySource, new RegExp(symbol, 'u'), symbol);
    assert.doesNotMatch(appSource, new RegExp(symbol, 'u'), symbol);
  }
  assert.match(registrySource, /createDesktopProjectAgentDashboardClientV2/u);
  assert.match(registrySource, /projectAgentDashboardOperationsV2/u);
  assert.match(appSource, /createDesktopProjectAgentDashboardOperationsV2/u);
  assert.match(
    appSource,
    /projectAgentDashboardOperationsV2:\s*desktopProjectAgentDashboardOperationsV2/u,
  );
  assert.match(registrySource, /createDesktopProjectAgentLogsClientV2/u);
  assert.match(registrySource, /projectAgentLogsOperationsV2/u);
  assert.match(appSource, /createDesktopProjectAgentLogsOperationsV2/u);
  assert.match(
    appSource,
    /projectAgentLogsOperationsV2:\s*desktopProjectAgentLogsOperationsV2/u,
  );
  assert.match(registrySource, /createDesktopProjectAgentPatternsClientV2/u);
  assert.match(registrySource, /projectAgentPatternsOperationsV2/u);
  assert.match(appSource, /createDesktopProjectAgentPatternsOperationsV2/u);
  assert.match(
    appSource,
    /projectAgentPatternsOperationsV2:\s*desktopProjectAgentPatternsOperationsV2/u,
  );
  assert.doesNotMatch(registrySource, /createProjectAgentDashboardClient/u);
  assert.doesNotMatch(appSource, /createProjectAgentDashboardClient/u);
  assert.doesNotMatch(registrySource, /createProjectAgentLogsClient/u);
  assert.doesNotMatch(appSource, /createProjectAgentLogsClient/u);
  assert.doesNotMatch(registrySource, /createProjectAgentPatternsClient/u);
  assert.doesNotMatch(appSource, /createProjectAgentPatternsClient/u);
  assert.doesNotMatch(registrySource, /projectAgentClients\?/u);
  assert.doesNotMatch(appSource, /projectAgentClients\?/u);
});

test('Project Agent Snapshot observes Cloud and declares Local authority', async () => {
  const cloud = await loadSnapshot(cloudConfig);
  for (const routeId of routeIds) {
    const capability = cloud.capabilities[routeId];
    assert.equal(capability.provenance, 'observed', routeId);
    assert.equal(capability.authority_source, 'cloud_service', routeId);
    assert.equal(capability.availability, 'available', routeId);
    assert.equal(capability.authority_revision, 23, routeId);
  }

  const local = await loadSnapshot({
    ...cloudConfig,
    mode: 'local',
    localApiToken: 'private-launch',
  });
  for (const routeId of routeIds) {
    const capability = local.capabilities[routeId];
    assert.equal(capability.provenance, 'declared', routeId);
    assert.equal(capability.authority_source, 'renderer', routeId);
    assert.equal(capability.availability, 'unavailable', routeId);
  }
});

async function loadSnapshot(config) {
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
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture({
          scopeRevision: 23,
        }),
        projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
        projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture({
          scopeRevision: 23,
        }),
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
