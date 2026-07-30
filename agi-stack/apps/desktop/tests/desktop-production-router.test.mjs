import assert from 'node:assert/strict';
import { copyFileSync, mkdirSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledNavigationDirectory =
  '/tmp/agistack-desktop-test-dist/src/features/navigation';
mkdirSync(compiledNavigationDirectory, { recursive: true });
copyFileSync(
  new URL(
    '../src/features/navigation/DesktopProductionRouter.css',
    import.meta.url,
  ),
  `${compiledNavigationDirectory}/DesktopProductionRouter.css`,
);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  DesktopProductionRouter,
  DesktopProductionRouterView,
  retryDesktopProductionRoute,
  returnToDesktopWorkbench,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/DesktopProductionRouter.js'
);
const { createDesktopRouteRegistry } = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js'
);

const source = readFileSync(
  new URL(
    '../src/features/navigation/DesktopProductionRouter.tsx',
    import.meta.url,
  ),
  'utf8',
);
const stylesheet = readFileSync(
  new URL(
    '../src/features/navigation/DesktopProductionRouter.css',
    import.meta.url,
  ),
  'utf8',
);
const messages = readFileSync(
  new URL(
    '../src/features/navigation/locales/desktopProductionRouterMessages.ts',
    import.meta.url,
  ),
  'utf8',
);
const globalStylesheet = readFileSync(
  new URL('../src/styles.css', import.meta.url),
  'utf8',
);

const routeContext = Object.freeze({
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const module = Object.freeze({
  routeId: 'project-project-overview',
  capability: 'project-project-overview',
  localPolicy: 'native_equivalent',
  disposition: 'implemented',
  availability: 'available',
  reasonCode: null,
  Surface({ module: routeModule, context }) {
    return React.createElement('output', {
      'data-surface-route': routeModule.routeId,
      'data-surface-tenant': context.tenantId,
      'data-surface-project': context.projectId,
    });
  },
});
const registry = createDesktopRouteRegistry([
  {
    id: 'project-project-overview',
    path: '/tenant/:tenantId/project/:projectId',
    scope: ['tenant', 'project'],
    navGroup: 'project-workspace',
    capability: 'project-project-overview',
    requiredPermission: ['authenticated', 'project_member'],
    localPolicy: 'native_equivalent',
    loader: async () => module,
  },
]);
const match = Object.freeze({
  definition: registry.definitions[0],
  context: routeContext,
  canonicalPath: '/tenant/tenant-1/project/project-1',
});
const capability = Object.freeze({
  availability: 'available',
  reason_code: null,
  service_version: '3.0.0',
  contract_version: '3.0.0',
  allowed_actions: ['view'],
  scope: {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: null,
    instance_id: null,
  },
  authority_revision: 4,
});

test('production router delegates to the React host and keeps legacy children mounted', () => {
  const location = hashLocation('');
  const markup = render(
    React.createElement(
      DesktopProductionRouter,
      {
        registry,
        location: location.port,
        mode: 'cloud',
        permissions: new Set(['authenticated', 'project_member']),
        resolveCapability: () => capability,
        switchScope: async () => {},
        navigation: { clearHash() {} },
      },
      React.createElement('article', { 'data-legacy': true }, 'Legacy workbench'),
    ),
  );

  assert.match(markup, /data-legacy="true"/u);
  assert.match(markup, /Legacy workbench/u);
  assert.doesNotMatch(markup, /desktop-production-route-stage/u);
  assert.match(source, /useDesktopHashRouteHost\(/u);
  assert.match(source, /const hostOptions = useMemo</u);
  assert.doesNotMatch(source, /useState|features\/session|stores\//u);
});

test('ready and degraded states render the exact module Surface and route context', () => {
  for (const status of ['ready', 'degraded']) {
    const markup = renderView({
      state: {
        status,
        match,
        capability: {
          ...capability,
          availability: status === 'degraded' ? 'degraded' : 'available',
          reason_code:
            status === 'degraded' ? 'project_overview_read_only' : null,
        },
        module,
      },
    });

    assert.match(
      markup,
      /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u,
    );
    assert.match(markup, /data-legacy="true"/u);
    assert.match(markup, new RegExp(`data-route-state="${status}"`, 'u'));
    assert.match(markup, /data-surface-route="project-project-overview"/u);
    assert.match(markup, /data-surface-tenant="tenant-1"/u);
    assert.match(markup, /data-surface-project="project-1"/u);
    assert.match(markup, /aria-label="Route breadcrumb"/u);
    assert.match(markup, /Return to workbench/u);
  }
});

test('empty and non-canonical hashes retain legacy while canonical failures take over', () => {
  for (const state of [
    {
      status: 'malformed',
      location: '',
      reasonCode: 'desktop_route_malformed',
    },
    {
      status: 'not_found',
      location: '#/legacy/workbench',
      reasonCode: 'desktop_route_not_found',
    },
  ]) {
    const markup = renderView({ state });
    assert.match(markup, /data-legacy="true"/u);
    assert.doesNotMatch(markup, /desktop-production-route-stage/u);
  }

  for (const [state, expected] of [
    [
      {
        status: 'malformed',
        location: '#/tenant/%E0%A4%A/project/project-1',
        reasonCode: 'desktop_route_malformed',
      },
      'Route could not be restored',
    ],
    [
      {
        status: 'not_found',
        location: '#/tenant/tenant-1/not-a-route',
        reasonCode: 'desktop_route_not_found',
      },
      'Native route not found',
    ],
  ]) {
    const markup = renderView({ state });
    assert.match(
      markup,
      /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u,
    );
    assert.match(markup, /data-legacy="true"/u);
    assert.match(markup, new RegExp(expected, 'u'));
    assert.match(markup, new RegExp(state.reasonCode, 'u'));
  }
});

test('loading, forbidden, unavailable, and error states expose structured boundaries', () => {
  const cases = [
    [
      {
        status: 'loading',
        match,
        capability,
        attempt: 2,
      },
      ['Loading native route', 'project-project-overview'],
    ],
    [
      {
        status: 'forbidden',
        match,
        reasonCode: 'desktop_route_permission_denied',
        missingPermissions: ['project_member'],
      },
      ['Permission required', 'desktop_route_permission_denied', 'project_member'],
    ],
    [
      {
        status: 'unavailable',
        match,
        reasonCode: 'project_overview_authority_unavailable',
        capability: null,
      },
      ['Native route unavailable', 'project_overview_authority_unavailable', 'Retry'],
    ],
    [
      {
        status: 'error',
        match,
        reasonCode: 'desktop_route_module_load_failed',
        retryable: true,
      },
      ['Native route failed', 'desktop_route_module_load_failed', 'Retry'],
    ],
  ];

  for (const [state, expectedValues] of cases) {
    const markup = renderView({ state });
    for (const expected of expectedValues) {
      assert.match(markup, new RegExp(expected, 'u'));
    }
  }
});

test('breadcrumb return and retry actions use only the injected ports', async () => {
  let clearCalls = 0;
  let retryCalls = 0;
  returnToDesktopWorkbench({
    clearHash() {
      clearCalls += 1;
    },
  });
  assert.equal(clearCalls, 1);

  await retryDesktopProductionRoute(async () => {
      retryCalls += 1;
  });
  assert.equal(retryCalls, 1);
  assert.match(
    source,
    /data-action="return-workbench"[\s\S]*returnToDesktopWorkbench/u,
  );
  assert.match(
    source,
    /data-action="retry-route"[\s\S]*retryDesktopProductionRoute/u,
  );
});

test('router styling and copy remain native, responsive, and bilingual', () => {
  assert.doesNotMatch(
    source,
    /<iframe|<webview|shell\.openExternal|window\.open|href=/iu,
  );
  assert.match(stylesheet, /var\(--desktop-surface-3\)/u);
  assert.match(stylesheet, /@media \(max-width:/u);
  assert.match(stylesheet, /:focus-visible/u);
  assert.match(messages, /desktopProductionRouterEnUS/u);
  assert.match(messages, /desktopProductionRouterZhCN/u);
  for (const key of [
    'desktopProductionRouter.breadcrumb',
    'desktopProductionRouter.returnWorkbench',
    'desktopProductionRouter.loading.title',
    'desktopProductionRouter.forbidden.title',
    'desktopProductionRouter.unavailable.title',
    'desktopProductionRouter.error.title',
    'desktopProductionRouter.malformed.title',
    'desktopProductionRouter.notFound.title',
  ]) {
    assert.equal(messages.split(`'${key}'`).length, 3);
  }
  const referencedTokens = new Set(
    [...stylesheet.matchAll(/var\((--desktop-[a-z0-9-]+)/gu)].map(
      (entry) => entry[1],
    ),
  );
  for (const token of referencedTokens) {
    assert.match(globalStylesheet, new RegExp(`${token}\\s*:`, 'u'));
  }
});

function renderView({ state }) {
  return render(
    React.createElement(
      DesktopProductionRouterView,
      {
        state,
        registry,
        retry: async () => {},
        navigation: { clearHash() {} },
      },
      React.createElement(
        'article',
        { 'data-legacy': true },
        'Legacy workbench',
      ),
    ),
  );
}

function render(element) {
  return renderToStaticMarkup(
    React.createElement(I18nProvider, null, element),
  );
}

function hashLocation(initialHash) {
  return {
    port: {
      readHash: () => initialHash,
      subscribe: () => () => {},
    },
  };
}
