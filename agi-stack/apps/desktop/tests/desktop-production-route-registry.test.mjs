import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledNavigationDirectory =
  '/tmp/agistack-desktop-test-dist/src/features/navigation';
mkdirSync(compiledNavigationDirectory, { recursive: true });
writeFileSync(`${compiledNavigationDirectory}/NativeUnavailableRoute.css`, '');
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  PROJECT_CRON_JOBS_ROUTE_ID,
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
  TENANT_OVERVIEW_ROUTE_ID,
  TENANT_PROJECTS_ROUTE_ID,
  TENANT_TASKS_ROUTE_ID,
  TENANT_WORKSPACES_ROUTE_ID,
  createDesktopProductionRouteRegistry,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');
const {
  NativeUnavailableRoute,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/NativeUnavailableRoute.js');
const {
  evaluateDesktopRouteAccess,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js');

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

function implementedSearchModule(overrides = {}) {
  function ProjectSearchRoute() {
    return React.createElement('section', null, 'Project Search route');
  }
  return Object.freeze({
    routeId: PROJECT_SEARCH_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: PROJECT_SEARCH_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: ProjectSearchRoute,
    ...overrides,
  });
}

function implementedCronJobsModule(overrides = {}) {
  function ProjectCronJobsRoute() {
    return React.createElement('section', null, 'Project Cron Jobs route');
  }
  return Object.freeze({
    routeId: PROJECT_CRON_JOBS_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: PROJECT_CRON_JOBS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: ProjectCronJobsRoute,
    ...overrides,
  });
}

function implementedTenantModule(overrides = {}) {
  function TenantOverviewRoute() {
    return React.createElement('section', null, 'Tenant Overview route');
  }
  return Object.freeze({
    routeId: TENANT_OVERVIEW_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_OVERVIEW_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantOverviewRoute,
    ...overrides,
  });
}

function implementedTenantProjectsModule(overrides = {}) {
  function TenantProjectsRoute() {
    return React.createElement('section', null, 'Tenant Projects route');
  }
  return Object.freeze({
    routeId: TENANT_PROJECTS_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_PROJECTS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantProjectsRoute,
    ...overrides,
  });
}

function implementedTenantWorkspacesModule(overrides = {}) {
  function TenantWorkspacesRoute() {
    return React.createElement('section', null, 'Tenant Workspaces route');
  }
  return Object.freeze({
    routeId: TENANT_WORKSPACES_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_WORKSPACES_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantWorkspacesRoute,
    ...overrides,
  });
}

function implementedTenantTasksModule(overrides = {}) {
  function TenantTasksRoute() {
    return React.createElement('section', null, 'Tenant Tasks route');
  }
  return Object.freeze({
    routeId: TENANT_TASKS_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_TASKS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantTasksRoute,
    ...overrides,
  });
}

function createRegistry(
  projectLoader = async () => implementedProjectModule(),
  searchLoader = async () => implementedSearchModule(),
  cronJobsLoader = async () => implementedCronJobsModule(),
  tenantLoader = async () => implementedTenantModule(),
  tenantProjectsLoader = async () => implementedTenantProjectsModule(),
  tenantWorkspacesLoader = async () => implementedTenantWorkspacesModule(),
  tenantTasksLoader = async () => implementedTenantTasksModule(),
) {
  return createDesktopProductionRouteRegistry({
    implementedLoaders: {
      [PROJECT_OVERVIEW_ROUTE_ID]: projectLoader,
      [PROJECT_SEARCH_ROUTE_ID]: searchLoader,
      [PROJECT_CRON_JOBS_ROUTE_ID]: cronJobsLoader,
      [TENANT_OVERVIEW_ROUTE_ID]: tenantLoader,
      [TENANT_PROJECTS_ROUTE_ID]: tenantProjectsLoader,
      [TENANT_WORKSPACES_ROUTE_ID]: tenantWorkspacesLoader,
      [TENANT_TASKS_ROUTE_ID]: tenantTasksLoader,
    },
  });
}

test('production registry requires every implemented project route loader', () => {
  assert.equal(PROJECT_OVERVIEW_ROUTE_ID, 'project-project-overview');
  assert.equal(PROJECT_SEARCH_ROUTE_ID, 'project-project-search');
  assert.equal(PROJECT_CRON_JOBS_ROUTE_ID, 'project-project-cron-jobs');
  assert.equal(TENANT_OVERVIEW_ROUTE_ID, 'tenant-tenant-overview');
  assert.equal(TENANT_PROJECTS_ROUTE_ID, 'tenant-tenant-projects');
  assert.equal(TENANT_WORKSPACES_ROUTE_ID, 'tenant-tenant-workspaces');
  assert.equal(TENANT_TASKS_ROUTE_ID, 'tenant-tenant-tasks');
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
          [PROJECT_SEARCH_ROUTE_ID]: async () => implementedSearchModule(),
          [PROJECT_CRON_JOBS_ROUTE_ID]: async () => implementedCronJobsModule(),
        },
      }),
    /desktop_production_route_loader_invalid:project-project-overview/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: async () => implementedProjectModule(),
          [PROJECT_SEARCH_ROUTE_ID]: async () => implementedSearchModule(),
          [PROJECT_CRON_JOBS_ROUTE_ID]: async () => implementedCronJobsModule(),
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
          [PROJECT_SEARCH_ROUTE_ID]: async () => implementedSearchModule(),
          [PROJECT_CRON_JOBS_ROUTE_ID]: async () => implementedCronJobsModule(),
          [TENANT_OVERVIEW_ROUTE_ID]: 'not-callable',
        },
      }),
    /desktop_production_route_loader_invalid:tenant-tenant-overview/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: async () => implementedProjectModule(),
          [PROJECT_SEARCH_ROUTE_ID]: 'not-callable',
          [PROJECT_CRON_JOBS_ROUTE_ID]: async () => implementedCronJobsModule(),
        },
      }),
    /desktop_production_route_loader_invalid:project-project-search/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: async () => implementedProjectModule(),
          [PROJECT_SEARCH_ROUTE_ID]: async () => implementedSearchModule(),
          [PROJECT_CRON_JOBS_ROUTE_ID]: 'not-callable',
        },
      }),
    /desktop_production_route_loader_invalid:project-project-cron-jobs/u,
  );
});

test('all 51 production loaders remain lazy and seven routes are real modules', async () => {
  let projectLoadCount = 0;
  let searchLoadCount = 0;
  let cronJobsLoadCount = 0;
  let tenantLoadCount = 0;
  let tenantProjectsLoadCount = 0;
  let tenantWorkspacesLoadCount = 0;
  let tenantTasksLoadCount = 0;
  const projectModule = implementedProjectModule();
  const searchModule = implementedSearchModule();
  const cronJobsModule = implementedCronJobsModule();
  const tenantModule = implementedTenantModule();
  const tenantProjectsModule = implementedTenantProjectsModule();
  const tenantWorkspacesModule = implementedTenantWorkspacesModule();
  const tenantTasksModule = implementedTenantTasksModule();
  const registry = createRegistry(
    async () => {
      projectLoadCount += 1;
      return projectModule;
    },
    async () => {
      searchLoadCount += 1;
      return searchModule;
    },
    async () => {
      cronJobsLoadCount += 1;
      return cronJobsModule;
    },
    async () => {
      tenantLoadCount += 1;
      return tenantModule;
    },
    async () => {
      tenantProjectsLoadCount += 1;
      return tenantProjectsModule;
    },
    async () => {
      tenantWorkspacesLoadCount += 1;
      return tenantWorkspacesModule;
    },
    async () => {
      tenantTasksLoadCount += 1;
      return tenantTasksModule;
    },
  );

  assert.equal(registry.definitions.length, 51);
  assert.equal(projectLoadCount, 0);
  assert.equal(searchLoadCount, 0);
  assert.equal(cronJobsLoadCount, 0);
  assert.equal(tenantLoadCount, 0);
  assert.equal(tenantProjectsLoadCount, 0);
  assert.equal(tenantWorkspacesLoadCount, 0);
  assert.equal(tenantTasksLoadCount, 0);

  const loaded = await Promise.all(
    registry.definitions.map(async (definition) => ({
      definition,
      module: await definition.loader(),
    })),
  );
  assert.equal(projectLoadCount, 1);
  assert.equal(searchLoadCount, 1);
  assert.equal(cronJobsLoadCount, 1);
  assert.equal(tenantLoadCount, 1);
  assert.equal(tenantProjectsLoadCount, 1);
  assert.equal(tenantWorkspacesLoadCount, 1);
  assert.equal(tenantTasksLoadCount, 1);

  const implemented = loaded.filter(
    ({ module }) => module.disposition === 'implemented',
  );
  const planned = loaded.filter(
    ({ module }) => module.disposition === 'planned',
  );
  assert.equal(implemented.length, 7);
  assert.deepEqual(
    implemented.map(({ definition }) => definition.id).sort(),
    [
      PROJECT_OVERVIEW_ROUTE_ID,
      PROJECT_SEARCH_ROUTE_ID,
      PROJECT_CRON_JOBS_ROUTE_ID,
      TENANT_OVERVIEW_ROUTE_ID,
      TENANT_PROJECTS_ROUTE_ID,
      TENANT_WORKSPACES_ROUTE_ID,
      TENANT_TASKS_ROUTE_ID,
    ].sort(),
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === PROJECT_OVERVIEW_ROUTE_ID,
    ).module,
    projectModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === PROJECT_SEARCH_ROUTE_ID,
    ).module,
    searchModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === PROJECT_CRON_JOBS_ROUTE_ID,
    ).module,
    cronJobsModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_OVERVIEW_ROUTE_ID,
    ).module,
    tenantModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_PROJECTS_ROUTE_ID,
    ).module,
    tenantProjectsModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_WORKSPACES_ROUTE_ID,
    ).module,
    tenantWorkspacesModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_TASKS_ROUTE_ID,
    ).module,
    tenantTasksModule,
  );
  assert.equal(planned.length, 44);

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
      module: implementedProjectModule({
        capability: 'project-project-settings',
      }),
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
      permissions: new Set(definition.requiredPermission.flat()),
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
  const definition = registry.byId.get('tenant-tenant-analytics');
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
  assert.match(markup, /tenant-tenant-analytics/);
  assert.match(markup, /desktop_native_route_planned/);
  assert.match(markup, /native_equivalent/);
  assert.match(markup, /Unavailable/);
  assert.doesNotMatch(
    markup,
    /Complete|WebView|Open in browser|href=|<iframe|<webview/i,
  );
  assert.doesNotMatch(
    surfaceSource,
    /shell\.openExternal|window\.open|<iframe|<webview/i,
  );
  assert.doesNotMatch(
    registrySource,
    /https?:\/\/|window\.open|shell\.openExternal/,
  );
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
