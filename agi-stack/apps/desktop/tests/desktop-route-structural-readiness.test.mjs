import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const productionRouteModule = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js',
);
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
  createDesktopProductionRouteRegistry,
  registerDesktopProductionRouteLoader,
} = productionRouteModule;
const {
  AGENT_WORKSPACE_ROUTE_ID,
} = require('/tmp/agistack-desktop-test-dist/src/features/agent-workspace/agentWorkspaceRouteModule.js');
const {
  evaluateDesktopRouteAccess,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js');

const observedCapability = Object.freeze({
  availability: 'available',
  reason_code: null,
  service_version: '0.1.0',
  contract_version: '4.0.0',
  allowed_actions: Object.freeze(['view']),
  scope: Object.freeze({
    tenant_id: null,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  }),
  authority_revision: 1,
  authority_source: 'cloud_service',
  provenance: 'observed',
});
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

function access(definition) {
  return evaluateDesktopRouteAccess({
    match: Object.freeze({
      definition,
      context: Object.freeze({}),
      canonicalPath: definition.path,
    }),
    mode: 'cloud',
    permissions: new Set(definition.requiredPermission.flat()),
    capability: observedCapability,
  });
}

test('every production route is implemented and fails closed only when its App binding is absent', async () => {
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {},
  });
  assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.length, registry.definitions.length);
  assert.deepEqual(
    [...DESKTOP_IMPLEMENTED_ROUTE_IDS].sort(),
    registry.definitions.map(({ id }) => id).sort(),
  );
  for (const definition of registry.definitions) {
    assert.deepEqual(definition.structuralReadiness, {
      status: 'unavailable',
      reasonCode: 'desktop_route_structural_app_binding_missing',
    });
    assert.equal((await definition.loader()).disposition, 'planned');
  }
});

test('production App owns exactly one loader binding for every catalog route', () => {
  const symbolByRouteId = new Map(
    Object.entries(productionRouteModule).flatMap(([symbol, value]) =>
      symbol.endsWith('_ROUTE_ID') && typeof value === 'string' ? [[value, symbol]] : [],
    ),
  );
  symbolByRouteId.set(AGENT_WORKSPACE_ROUTE_ID, 'AGENT_WORKSPACE_ROUTE_ID');
  for (const routeId of DESKTOP_IMPLEMENTED_ROUTE_IDS) {
    const symbol = symbolByRouteId.get(routeId);
    assert.ok(symbol, `missing route symbol for ${routeId}`);
    const bindings = appSource.match(new RegExp(`\\[${symbol}\\]\\s*:`, 'gu')) ?? [];
    assert.equal(bindings.length, 1, `${routeId} must have exactly one App loader binding`);
  }
});

test('observed capability cannot bypass an absent App binding', () => {
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {},
  });
  for (const definition of registry.definitions) {
    assert.deepEqual(access(definition), {
      status: 'unavailable',
      reasonCode: 'desktop_route_structural_app_binding_missing',
      capability: null,
    });
  }
});

test('callable placeholders without registered loader identity fail closed', () => {
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {
      [PROJECT_OVERVIEW_ROUTE_ID]: async () => null,
    },
  });
  const definition = registry.byId.get(PROJECT_OVERVIEW_ROUTE_ID);
  assert.ok(definition);
  assert.deepEqual(definition.structuralReadiness, {
    status: 'unavailable',
    reasonCode: 'desktop_route_structural_loader_missing',
  });
  assert.deepEqual(access(definition), {
    status: 'unavailable',
    reasonCode: 'desktop_route_structural_loader_missing',
    capability: null,
  });
});

test('registered loader identity and App binding release the structural gate', () => {
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {
      [PROJECT_OVERVIEW_ROUTE_ID]: registerDesktopProductionRouteLoader(
        PROJECT_OVERVIEW_ROUTE_ID,
        async () => ({
          routeId: PROJECT_OVERVIEW_ROUTE_ID,
          disposition: 'implemented',
          availability: 'available',
          reasonCode: null,
          capability: PROJECT_OVERVIEW_ROUTE_ID,
          localPolicy: 'native_equivalent',
          Surface: () => null,
        }),
      ),
    },
  });
  const definition = registry.byId.get(PROJECT_OVERVIEW_ROUTE_ID);
  assert.ok(definition);
  assert.deepEqual(definition.structuralReadiness, { status: 'ready' });
  assert.equal(access(definition).status, 'allowed');
});

test('registered loader identity must match the App route binding', () => {
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {
      [PROJECT_OVERVIEW_ROUTE_ID]: registerDesktopProductionRouteLoader(
        PROJECT_SEARCH_ROUTE_ID,
        async () => null,
      ),
    },
  });
  const definition = registry.byId.get(PROJECT_OVERVIEW_ROUTE_ID);
  assert.ok(definition);
  assert.deepEqual(definition.structuralReadiness, {
    status: 'unavailable',
    reasonCode: 'desktop_route_structural_loader_missing',
  });
});
