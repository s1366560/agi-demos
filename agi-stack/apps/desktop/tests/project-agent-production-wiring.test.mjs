import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

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
    assert.match(appSource, new RegExp(symbol, 'u'), symbol);
  }
});

test('Project Agent Snapshot observes Cloud and declares Local authority', async () => {
  const cloud = await loadSnapshot(cloudConfig, clients('cloud'));
  for (const routeId of routeIds) {
    const capability = cloud.capabilities[routeId];
    assert.equal(capability.provenance, 'observed', routeId);
    assert.equal(capability.authority_source, 'cloud_service', routeId);
    assert.equal(capability.availability, 'available', routeId);
    assert.equal(capability.authority_revision, 23, routeId);
  }

  let calls = 0;
  const localClients = Object.fromEntries(
    routeIds.map((routeId) => [
      routeId,
      {
        async load() {
          calls += 1;
          throw new Error(routeId);
        },
      },
    ]),
  );
  const local = await loadSnapshot(
    { ...cloudConfig, mode: 'local', localApiToken: 'private-launch' },
    localClients,
  );
  assert.equal(calls, 0);
  for (const routeId of routeIds) {
    const capability = local.capabilities[routeId];
    assert.equal(capability.provenance, 'declared', routeId);
    assert.equal(capability.authority_source, 'renderer', routeId);
    assert.equal(capability.availability, 'unavailable', routeId);
  }
});

async function loadSnapshot(config, projectAgentClients) {
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
      { projectAgentClients },
    ).loadSnapshot();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function clients(authority) {
  return Object.fromEntries(
    routeIds.map((routeId) => [
      routeId,
      {
        async load(scope) {
          assert.deepEqual(scope, {
            authority,
            tenantId: 'tenant-1',
            projectId: 'project-1',
          });
          return {
            scope,
            scopeRevision: 23,
            authority,
            availability: 'available',
            reasonCode: null,
            allowedActions: ['view'],
          };
        },
      },
    ]),
  );
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
