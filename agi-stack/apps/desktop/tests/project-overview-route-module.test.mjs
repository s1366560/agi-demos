import assert from 'node:assert/strict';
import { copyFileSync, mkdirSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledProjectDirectory =
  '/tmp/agistack-desktop-test-dist/src/features/project';
mkdirSync(compiledProjectDirectory, { recursive: true });
copyFileSync(
  new URL('../src/features/project/ProjectOverviewPage.css', import.meta.url),
  `${compiledProjectDirectory}/ProjectOverviewPage.css`,
);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  buildProjectOverviewPresentation,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/project/projectOverviewPresentationModel.js'
);
const {
  createDesktopProductionRouteRegistry,
  PROJECT_CRON_JOBS_ROUTE_ID,
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
  TENANT_OVERVIEW_ROUTE_ID,
  TENANT_PROJECTS_ROUTE_ID,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js'
);
const {
  createProjectOverviewRouteModuleLoader,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/project/projectOverviewRouteModule.js'
);

const factorySource = readFileSync(
  new URL(
    '../src/features/project/projectOverviewRouteModule.tsx',
    import.meta.url,
  ),
  'utf8',
);

const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const routeContext = Object.freeze({
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
});

test('factory stays lazy and publishes the exact implemented route module contract', async () => {
  let bindingCalls = 0;
  const loader = createProjectOverviewRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return binding(cloudScope);
    },
  });

  assert.equal(typeof loader, 'function');
  assert.equal(bindingCalls, 0);

  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {
      [PROJECT_OVERVIEW_ROUTE_ID]: loader,
      [PROJECT_SEARCH_ROUTE_ID]: implementedSearchLoader(),
      [PROJECT_CRON_JOBS_ROUTE_ID]: implementedCronJobsLoader(),
      [TENANT_OVERVIEW_ROUTE_ID]: implementedTenantLoader(),
      [TENANT_PROJECTS_ROUTE_ID]: implementedRouteLoader(TENANT_PROJECTS_ROUTE_ID),
    },
  });
  const module = await registry.byId.get(PROJECT_OVERVIEW_ROUTE_ID).loader();

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
      routeId: 'project-project-overview',
      capability: 'project-project-overview',
      localPolicy: 'native_equivalent',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      surfaceType: 'function',
    },
  );
});

function implementedRouteLoader(routeId) {
  return async () =>
    Object.freeze({
      routeId,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      capability: routeId,
      localPolicy: 'native_equivalent',
      Surface() {
        return null;
      },
    });
}

function implementedSearchLoader() {
  return async () =>
    Object.freeze({
      routeId: PROJECT_SEARCH_ROUTE_ID,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      capability: PROJECT_SEARCH_ROUTE_ID,
      localPolicy: 'native_equivalent',
      Surface() {
        return null;
      },
    });
}

function implementedCronJobsLoader() {
  return async () =>
    Object.freeze({
      routeId: PROJECT_CRON_JOBS_ROUTE_ID,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      capability: PROJECT_CRON_JOBS_ROUTE_ID,
      localPolicy: 'native_equivalent',
      Surface() {
        return null;
      },
    });
}

function implementedTenantLoader() {
  return async () => ({
    routeId: TENANT_OVERVIEW_ROUTE_ID,
    capability: TENANT_OVERVIEW_ROUTE_ID,
    localPolicy: 'native_equivalent',
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    Surface() {
      return null;
    },
  });
}

test('surface binds only the structured route context to controller authority', async () => {
  const receivedContexts = [];
  const controller = controllerFor(cloudScope);
  const loader = createProjectOverviewRouteModuleLoader({
    createBinding(context) {
      receivedContexts.push(context);
      return { controller, scope: cloudScope };
    },
  });
  const module = await loader();

  const markup = renderRoute(module, routeContext);

  assert.equal(receivedContexts.length, 1);
  assert.deepEqual(receivedContexts[0], routeContext);
  assert.match(markup, /data-authority="cloud"/u);
  assert.match(markup, /data-state="loading"/u);
  assert.match(markup, /project-1/u);
  assert.equal(controller.calls.load, 0);
  assert.match(factorySource, /useProjectOverviewController\(/u);
  assert.match(factorySource, /<ProjectOverviewPage/u);
  assert.doesNotMatch(
    factorySource,
    /window\.location|document\.location|new URL\(|URLSearchParams|RegExp\(|\.match\(/u,
  );
});

test('missing tenant or project context fails closed without creating a binding', async () => {
  let bindingCalls = 0;
  const module = await createProjectOverviewRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return binding(cloudScope);
    },
  })();

  for (const context of [
    { projectId: 'project-1' },
    { tenantId: 'tenant-1' },
    { tenantId: ' ', projectId: 'project-1' },
    { tenantId: 'tenant-1', projectId: '\n' },
  ]) {
    const markup = renderRoute(module, context);
    assert.match(markup, /data-state="unavailable"/u);
    assert.match(markup, /project_overview_route_context_unavailable/u);
  }

  assert.equal(bindingCalls, 0);
});

test('binding scope drift fails closed before the controller hook is mounted', async () => {
  const controller = controllerFor(cloudScope);
  const module = await createProjectOverviewRouteModuleLoader({
    createBinding() {
      return {
        controller,
        scope: {
          ...cloudScope,
          projectId: 'project-other',
        },
      };
    },
  })();

  const markup = renderRoute(module, routeContext);

  assert.match(markup, /data-state="unavailable"/u);
  assert.match(markup, /project_overview_route_binding_scope_mismatch/u);
  assert.equal(controller.calls.load, 0);
});

test('page and hook code load behind the route loader boundary', () => {
  assert.match(factorySource, /import\('\.\/ProjectOverviewPage'\)/u);
  assert.match(factorySource, /import\('\.\/useProjectOverviewController'\)/u);
  assert.doesNotMatch(
    factorySource,
    /import\s+\{\s*ProjectOverviewPage\s*\}\s+from/u,
  );
  assert.doesNotMatch(
    factorySource,
    /import\s+\{\s*useProjectOverviewController\s*\}\s+from/u,
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

function binding(scope) {
  return {
    controller: controllerFor(scope),
    scope,
  };
}

function controllerFor(scope) {
  const calls = {
    load: 0,
    retry: 0,
    cancel: 0,
  };
  const model = buildProjectOverviewPresentation({
    kind: 'loading',
    scope,
    scopeSwitch: false,
  });
  return {
    calls,
    getSnapshot() {
      return model;
    },
    subscribe() {
      return () => {};
    },
    async load() {
      calls.load += 1;
    },
    async retry() {
      calls.retry += 1;
    },
    cancel() {
      calls.cancel += 1;
    },
    stop() {
      calls.cancel += 1;
    },
  };
}
