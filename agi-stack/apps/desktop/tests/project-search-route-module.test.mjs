import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createDesktopProductionRouteRegistry,
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js'
);
const {
  createProjectSearchRouteModuleLoader,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/search/projectSearchRouteModule.js'
);

const factorySource = readFileSync(
  new URL(
    '../src/features/search/projectSearchRouteModule.tsx',
    import.meta.url,
  ),
  'utf8',
);

const routeContext = Object.freeze({
  tenantId: 'tenant-1',
  projectId: 'project-1',
});

test('factory stays lazy and publishes the exact Project Advanced Search route contract', async () => {
  let bindingCalls = 0;
  const loader = createProjectSearchRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return binding();
    },
  });

  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {
      [PROJECT_OVERVIEW_ROUTE_ID]: implementedOverviewLoader(),
      [PROJECT_SEARCH_ROUTE_ID]: loader,
    },
  });
  const module = await registry.byId.get(PROJECT_SEARCH_ROUTE_ID).loader();

  assert.equal(bindingCalls, 0);
  assert.deepEqual(
    {
      routeId: module.routeId,
      capability: module.capability,
      localPolicy: module.localPolicy,
      disposition: module.disposition,
      availability: module.availability,
      reasonCode: module.reasonCode,
      surfaceType: typeof module.Surface,
    },
    {
      routeId: 'project-project-search',
      capability: 'project-project-search',
      localPolicy: 'native_equivalent',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      surfaceType: 'function',
    },
  );
});

test('surface reuses DesktopSearch and binds only exact tenant and project context', async () => {
  const receivedContexts = [];
  const module = await createProjectSearchRouteModuleLoader({
    createBinding(context) {
      receivedContexts.push(context);
      return binding();
    },
  })();

  const markup = renderRoute(module, routeContext);

  assert.deepEqual(receivedContexts, [routeContext]);
  assert.match(markup, /class="desktop-search"/u);
  assert.match(markup, /Project One/u);
  assert.match(factorySource, /import\('\.\/DesktopSearch'\)/u);
  assert.match(factorySource, /<DesktopSearch/u);
  assert.doesNotMatch(
    factorySource,
    /window\.location|document\.location|new URL\(|URLSearchParams|RegExp\(|\.match\(/u,
  );
});

test('missing tenant or project context fails closed without creating a binding', async () => {
  let bindingCalls = 0;
  const module = await createProjectSearchRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return binding();
    },
  })();

  for (const context of [
    { projectId: 'project-1' },
    { tenantId: 'tenant-1' },
    { tenantId: ' ', projectId: 'project-1' },
    { tenantId: 'tenant-1', projectId: '\n' },
  ]) {
    const markup = renderRoute(module, context);
    assert.match(markup, /data-reason-code="project_search_route_context_unavailable"/u);
  }
  assert.equal(bindingCalls, 0);
});

test('binding scope drift fails closed before exposing the search authority', async () => {
  const calls = [];
  const module = await createProjectSearchRouteModuleLoader({
    createBinding() {
      return binding({
        scope: {
          tenantId: 'tenant-1',
          projectId: 'project-other',
        },
        api: {
          async searchProject() {
            calls.push('search');
            throw new Error('search authority must stay unreachable');
          },
        },
      });
    },
  })();

  const markup = renderRoute(module, routeContext);

  assert.match(
    markup,
    /data-reason-code="project_search_route_binding_scope_mismatch"/u,
  );
  assert.deepEqual(calls, []);
});

test('DesktopSearch code loads only behind the production route loader boundary', () => {
  assert.match(factorySource, /import\('\.\/DesktopSearch'\)/u);
  assert.doesNotMatch(
    factorySource,
    /import\s+\{\s*DesktopSearch\s*\}\s+from/u,
  );
});

function renderRoute(module, context) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { module, context }),
    ),
  );
}

function binding(overrides = {}) {
  return {
    api: {
      async searchProject() {
        return { search_type: 'advanced', total: 0, results: [] };
      },
    },
    scope: routeContext,
    projectName: 'Project One',
    capability: availableCapability(),
    capabilityLoading: false,
    ...overrides,
  };
}

function availableCapability() {
  return Object.freeze({
    availability: 'available',
    status: 'available',
    available: true,
    reason_code: null,
    service_version: '3.0.0',
    contract_version: '3.0.0',
    allowed_actions: Object.freeze(['advanced']),
    scope: Object.freeze({
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: 7,
  });
}

function implementedOverviewLoader() {
  return async () =>
    Object.freeze({
      routeId: PROJECT_OVERVIEW_ROUTE_ID,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      capability: PROJECT_OVERVIEW_ROUTE_ID,
      localPolicy: 'native_equivalent',
      Surface() {
        return null;
      },
    });
}
