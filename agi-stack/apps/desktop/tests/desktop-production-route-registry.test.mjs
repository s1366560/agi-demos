import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledNavigationDirectory =
  '/tmp/agistack-desktop-test-dist/src/features/navigation';
mkdirSync(compiledNavigationDirectory, { recursive: true });
writeFileSync(
  `${compiledNavigationDirectory}/NativeUnavailableRoute.css`,
  '',
);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  PROJECT_OVERVIEW_ROUTE_ID,
  createDesktopProductionRouteRegistry,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js'
);
const {
  NativeUnavailableRoute,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/NativeUnavailableRoute.js'
);
const {
  evaluateDesktopRouteAccess,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js'
);

const sourceRoot = new URL('../src/features/navigation/', import.meta.url);
const registrySource = readFileSync(
  new URL('desktopProductionRouteRegistry.ts', sourceRoot),
  'utf8',
);
const surfaceSource = readFileSync(
  new URL('NativeUnavailableRoute.tsx', sourceRoot),
  'utf8',
);
const stylesheet = readFileSync(
  new URL('NativeUnavailableRoute.css', sourceRoot),
  'utf8',
);
const messagesSource = readFileSync(
  new URL('locales/nativeUnavailableRouteMessages.ts', sourceRoot),
  'utf8',
);
const i18nSource = readFileSync(
  new URL('../src/i18n.tsx', import.meta.url),
  'utf8',
);
const globalStylesheet = readFileSync(
  new URL('../src/styles.css', import.meta.url),
  'utf8',
);

function implementedProjectModule(overrides = {}) {
  function ProjectOverviewRoute() {
    return React.createElement('section', null, 'Project Overview route');
  }
  return Object.freeze({
    routeId: PROJECT_OVERVIEW_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: PROJECT_OVERVIEW_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: ProjectOverviewRoute,
    ...overrides,
  });
}

function createRegistry(loader = async () => implementedProjectModule()) {
  return createDesktopProductionRouteRegistry({
    implementedLoaders: {
      [PROJECT_OVERVIEW_ROUTE_ID]: loader,
    },
  });
}

test('production registry requires the one implemented Project Overview loader', () => {
  assert.equal(PROJECT_OVERVIEW_ROUTE_ID, 'project-project-overview');
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {},
      }),
    /desktop_production_route_loader_missing:project-project-overview/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: 'not-callable',
        },
      }),
    /desktop_production_route_loader_invalid:project-project-overview/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: async () => implementedProjectModule(),
          'external-web-handoff': async () => implementedProjectModule(),
        },
      }),
    /desktop_production_route_loader_unknown:external-web-handoff/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: async () => implementedProjectModule(),
          'tenant-tenant-overview': async () => implementedProjectModule(),
        },
      }),
    /desktop_production_route_loader_not_implemented:tenant-tenant-overview/u,
  );
});

test('all 51 production loaders remain lazy and Project Overview is the unique real module', async () => {
  let projectLoadCount = 0;
  const projectModule = implementedProjectModule();
  const registry = createRegistry(async () => {
    projectLoadCount += 1;
    return projectModule;
  });

  assert.equal(registry.definitions.length, 51);
  assert.equal(projectLoadCount, 0);

  const loaded = await Promise.all(
    registry.definitions.map(async (definition) => ({
      definition,
      module: await definition.loader(),
    })),
  );
  assert.equal(projectLoadCount, 1);

  const implemented = loaded.filter(
    ({ module }) => module.disposition === 'implemented',
  );
  const planned = loaded.filter(
    ({ module }) => module.disposition === 'planned',
  );
  assert.equal(implemented.length, 1);
  assert.equal(implemented[0].definition.id, PROJECT_OVERVIEW_ROUTE_ID);
  assert.equal(implemented[0].module, projectModule);
  assert.equal(planned.length, 50);

  for (const { definition, module } of planned) {
    assert.equal(module.routeId, definition.id);
    assert.equal(module.capability, definition.capability);
    assert.equal(module.localPolicy, definition.localPolicy);
    assert.equal(module.availability, 'unavailable');
    assert.equal(module.Surface, NativeUnavailableRoute);
    assert.equal(module.reasonCode, plannedReason(definition.localPolicy));
    assert.notEqual(module.reasonCode, null);
  }
});

test('implemented loader results fail closed when the route module contract drifts', async () => {
  const cases = [
    {
      module: null,
      reason: 'desktop_route_module_invalid:project-project-overview',
    },
    {
      module: implementedProjectModule({ routeId: 'tenant-tenant-overview' }),
      reason: 'desktop_route_module_identity_mismatch:project-project-overview',
    },
    {
      module: implementedProjectModule({ disposition: 'planned' }),
      reason: 'desktop_route_module_invalid:project-project-overview',
    },
    {
      module: implementedProjectModule({ availability: 'unavailable' }),
      reason: 'desktop_route_module_invalid:project-project-overview',
    },
    {
      module: implementedProjectModule({ capability: 'project-project-settings' }),
      reason: 'desktop_route_module_contract_mismatch:project-project-overview',
    },
    {
      module: implementedProjectModule({ localPolicy: 'cloud_only' }),
      reason: 'desktop_route_module_contract_mismatch:project-project-overview',
    },
    {
      module: implementedProjectModule({ Surface: 'ProjectOverviewPage' }),
      reason: 'desktop_route_module_invalid:project-project-overview',
    },
  ];

  for (const entry of cases) {
    const registry = createRegistry(async () => entry.module);
    await assert.rejects(
      registry.byId.get(PROJECT_OVERVIEW_ROUTE_ID).loader(),
      new RegExp(entry.reason),
    );
  }
});

test('Local cloud-only and blocked routes stay owned by the Host gate', () => {
  const registry = createRegistry();
  const cloudOnly = registry.definitions.find(
    (definition) => definition.localPolicy === 'cloud_only',
  );
  const blocked = registry.definitions.find(
    (definition) => definition.localPolicy === 'blocked_by_web_contract',
  );
  assert.ok(cloudOnly);
  assert.ok(blocked);

  const localAccess = (definition) =>
    evaluateDesktopRouteAccess({
      match: {
        definition,
        context: {
          tenantId: 'tenant-1',
          projectId: definition.scope.includes('project')
            ? 'project-1'
            : undefined,
        },
        canonicalPath: definition.path,
      },
      mode: 'local',
      permissions: new Set(definition.requiredPermission),
      capability: null,
    });

  assert.deepEqual(localAccess(cloudOnly), {
    status: 'unavailable',
    reasonCode: 'desktop_route_local_cloud_only',
    capability: null,
  });
  assert.deepEqual(localAccess(blocked), {
    status: 'unavailable',
    reasonCode: 'desktop_route_local_blocked_by_web_contract',
    capability: null,
  });
});

test('generic unavailable surface renders structured route authority without a Web escape', async () => {
  const registry = createRegistry();
  const definition = registry.byId.get('tenant-tenant-overview');
  assert.ok(definition);
  const module = await definition.loader();
  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { module }),
    ),
  );

  assert.match(markup, /Native route planned/);
  assert.match(markup, /tenant-tenant-overview/);
  assert.match(markup, /desktop_native_route_planned/);
  assert.match(markup, /native_equivalent/);
  assert.match(markup, /Unavailable/);
  assert.doesNotMatch(markup, /Complete|WebView|Open in browser|href=|<iframe|<webview/i);
  assert.doesNotMatch(surfaceSource, /shell\.openExternal|window\.open|<iframe|<webview/i);
  assert.doesNotMatch(registrySource, /https?:\/\/|window\.open|shell\.openExternal/);
});

test('unavailable route UI uses bilingual domain i18n and declared Desktop tokens', () => {
  assert.match(surfaceSource, /useI18n\(\)/);
  assert.match(
    i18nSource,
    /nativeUnavailableRouteEnUS,[\s\S]*nativeUnavailableRouteZhCN/,
  );
  assert.match(i18nSource, /\.\.\.nativeUnavailableRouteEnUS/);
  assert.match(i18nSource, /\.\.\.nativeUnavailableRouteZhCN/);
  for (const key of [
    'nativeUnavailableRoute.title',
    'nativeUnavailableRoute.description',
    'nativeUnavailableRoute.routeId',
    'nativeUnavailableRoute.capability',
    'nativeUnavailableRoute.localPolicy',
    'nativeUnavailableRoute.reasonCode',
    'nativeUnavailableRoute.availability',
  ]) {
    assert.equal(messagesSource.split(`'${key}'`).length, 3);
  }

  assert.match(stylesheet, /var\(--desktop-surface-3\)/);
  assert.match(stylesheet, /@media \(max-width:/);
  assert.match(stylesheet, /:focus-visible/);
  const referencedTokens = new Set(
    [...stylesheet.matchAll(/var\((--desktop-[a-z0-9-]+)/g)].map(
      (match) => match[1],
    ),
  );
  for (const token of referencedTokens) {
    assert.match(globalStylesheet, new RegExp(`${token}\\s*:`));
  }
});

function plannedReason(localPolicy) {
  if (localPolicy === 'cloud_only') {
    return 'desktop_native_route_cloud_only_planned';
  }
  if (localPolicy === 'blocked_by_web_contract') {
    return 'desktop_native_route_web_contract_blocked';
  }
  return 'desktop_native_route_planned';
}
