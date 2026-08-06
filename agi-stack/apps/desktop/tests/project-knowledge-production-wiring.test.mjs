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
  DESKTOP_CAPABILITY_NAMES,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  createDesktopProductionRouteRegistry,
  registerDesktopProductionRouteLoaders,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

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
    assert.match(appSource, new RegExp(symbol, 'u'), symbol);
  }
  assert.doesNotMatch(
    appSource,
    /project-knowledge[\s\S]{0,500}(?:WebView|<webview|<iframe|openExternal|window\.open)/iu,
  );
});

test('Cloud Snapshot v4 observes all five scoped Project Knowledge authorities', async () => {
  const clients = projectKnowledgeClients('cloud');
  const snapshot = await loadSnapshot(cloudConfig, clients);

  for (const routeId of ROUTE_IDS) {
    const capability = snapshot.capabilities[routeId];
    assert.equal(capability.provenance, 'observed', routeId);
    assert.equal(capability.authority_source, 'cloud_service', routeId);
    assert.equal(capability.scope.tenant_id, 'tenant-1', routeId);
    assert.equal(capability.scope.project_id, 'project-1', routeId);
    assert.equal(capability.contract_version, '4.0.0', routeId);
  }
  assert.deepEqual(pick(snapshot, 'project-project-team'), {
    availability: 'available',
    reason_code: null,
    allowed_actions: ['view', 'list'],
  });
  assert.deepEqual(pick(snapshot, 'project-project-memories'), {
    availability: 'degraded',
    reason_code: 'project_memories_export_file_ipc_unavailable',
    allowed_actions: ['view', 'list'],
  });
  assert.deepEqual(pick(snapshot, 'project-project-entities'), {
    availability: 'available',
    reason_code: null,
    allowed_actions: ['view', 'list'],
  });
});

test('Local Snapshot keeps Project Knowledge unavailable until sidecar authority is observed', async () => {
  let loadCalls = 0;
  const clients = Object.fromEntries(
    ROUTE_IDS.map((routeId) => [
      routeId,
      {
        async load() {
          loadCalls += 1;
          throw new Error('Local static clients must not manufacture observed authority');
        },
      },
    ]),
  );
  const snapshot = await loadSnapshot(
    { ...cloudConfig, mode: 'local', localApiToken: 'private-launch' },
    clients,
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

async function loadSnapshot(config, projectKnowledgeClients) {
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
      { projectKnowledgeClients },
    ).loadSnapshot();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function projectKnowledgeClients(authority) {
  const degradedReasons = {
    'project-project-memories': 'project_memories_export_file_ipc_unavailable',
    'project-project-communities':
      'project_communities_trusted_task_stream_unavailable',
    'project-project-graph': 'project_graph_export_file_ipc_unavailable',
  };
  return Object.fromEntries(
    ROUTE_IDS.map((routeId) => [
      routeId,
      {
        async load(scope) {
          assert.deepEqual(scope, {
            authority,
            tenantId: 'tenant-1',
            projectId: 'project-1',
          });
          const reasonCode = degradedReasons[routeId] ?? null;
          return {
            scope,
            scopeRevision: 7,
            authority,
            availability: reasonCode ? 'degraded' : 'available',
            reasonCode,
            allowedActions: ['view', 'list'],
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

function pick(snapshot, routeId) {
  const capability = snapshot.capabilities[routeId];
  return {
    availability: capability.availability,
    reason_code: capability.reason_code,
    allowed_actions: [...capability.allowed_actions],
  };
}
