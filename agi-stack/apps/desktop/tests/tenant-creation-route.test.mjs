import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledDirectory =
  '/tmp/agistack-desktop-test-dist/src/features/tenant-creation';
mkdirSync(compiledDirectory, { recursive: true });
writeFileSync(`${compiledDirectory}/TenantCreationPage.css`, '');
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  DESKTOP_PRODUCTION_ROUTE_IDS,
  TENANT_CREATION_ROUTE_ID,
  createDesktopProductionRouteRegistry,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');
const {
  createTenantCreationRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/tenant-creation/tenantCreationRouteModule.js');
const {
  tenantCreationCapability,
} = require('/tmp/agistack-desktop-test-dist/src/features/tenant-creation/tenantCreationCapability.js');
const {
  evaluateDesktopRouteAccess,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js');

test('production registry adds authenticated tenant creation after the canonical routes', async () => {
  const registry = createRegistry();
  assert.equal(TENANT_CREATION_ROUTE_ID, 'tenant-creation');
  assert.deepEqual(
    registry.definitions.map((definition) => definition.id),
    DESKTOP_PRODUCTION_ROUTE_IDS,
  );
  const definition = registry.byId.get(TENANT_CREATION_ROUTE_ID);
  assert.equal(definition.path, '/tenants/new');
  assert.deepEqual(definition.scope, ['global']);
  assert.deepEqual(definition.requiredPermission, [['authenticated']]);
  assert.equal(definition.localPolicy, 'cloud_only');

  const module = await definition.loader();
  assert.equal(module.routeId, TENANT_CREATION_ROUTE_ID);
  assert.equal(module.disposition, 'implemented');
  assert.equal(module.availability, 'available');
});

test('tenant creation capability is Cloud fail-closed until observed and Local not applicable', () => {
  assert.deepEqual(tenantCreationCapability({ mode: 'cloud' }), {
    availability: 'unavailable',
    reason_code: 'renderer_capability_authority_unobserved',
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope: {
      tenant_id: null,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    },
    authority_revision: null,
    authority_source: 'renderer',
    provenance: 'declared',
  });
  assert.deepEqual(tenantCreationCapability({ mode: 'local' }), {
    availability: 'not_applicable',
    reason_code: 'local_tenant_creation_not_applicable',
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope: {
      tenant_id: null,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    },
    authority_revision: null,
    authority_source: 'renderer',
    provenance: 'declared',
  });
});

test('Local tenant creation stops at capability authority before loading', () => {
  const definition = createRegistry().byId.get(TENANT_CREATION_ROUTE_ID);
  const access = evaluateDesktopRouteAccess({
    match: {
      definition,
      context: {},
      canonicalPath: '/tenants/new',
    },
    mode: 'local',
    permissions: new Set(['authenticated']),
    capability: tenantCreationCapability({ mode: 'local' }),
  });
  assert.equal(access.status, 'unavailable');
  assert.equal(access.reasonCode, 'local_tenant_creation_not_applicable');
});

test('tenant creation route renders a native form without Web embedding', async () => {
  const definition = createRegistry().byId.get(TENANT_CREATION_ROUTE_ID);
  const module = await definition.loader();
  const markup = render(
    React.createElement(module.Surface, {
      module,
      context: {},
    }),
  );
  assert.match(markup, /Create organization/u);
  assert.match(markup, /name="name"/u);
  assert.match(markup, /name="description"/u);
  assert.match(markup, /name="plan"/u);
  assert.doesNotMatch(markup, /<iframe|<webview/u);
});

test('tenant creation wiring keeps mode checks out of the page and refreshes auth catalog', () => {
  const pageSource = readFileSync(
    new URL(
      '../src/features/tenant-creation/TenantCreationPage.tsx',
      import.meta.url,
    ),
    'utf8',
  );
  const appSource = readFileSync(
    new URL('../src/App.tsx', import.meta.url),
    'utf8',
  );
  assert.doesNotMatch(pageSource, /config\.mode|apiBaseUrl|window\.location/u);
  assert.match(appSource, /upsertCreatedTenant/u);
  assert.match(appSource, /listTenants\(signal\)/u);
  assert.match(appSource, /tenantCreationCapability/u);
});

function createRegistry() {
  const implementedLoaders = new Proxy(
    {
      [TENANT_CREATION_ROUTE_ID]: createTenantCreationRouteModuleLoader({
        createBinding: () => ({
          client: {
            create: async () => ({
              id: 'tenant-2',
              name: 'Acme',
              slug: 'acme',
              description: null,
              owner_id: 'user-1',
              plan: 'free',
              max_projects: 3,
              max_users: 10,
              max_storage: 1073741824,
              created_at: '2026-08-02T12:00:00Z',
              updated_at: null,
            }),
          },
          onCreated: async () => ({ catalogRefreshed: true }),
          onNavigateBack() {},
        }),
      }),
    },
    {
      has: () => true,
      get(target, property) {
        if (Reflect.has(target, property)) return Reflect.get(target, property);
        return async () => ({
          routeId: property,
          disposition: 'implemented',
          availability: 'available',
          reasonCode: null,
          capability: property,
          localPolicy:
            String(property).includes('pool') ||
            String(property).includes('clusters') ||
            String(property).includes('deploy') ||
            String(property).includes('dead-letter') ||
            property === TENANT_CREATION_ROUTE_ID
              ? 'cloud_only'
              : 'native_equivalent',
          Surface: () => React.createElement('div'),
        });
      },
      ownKeys(target) {
        return Reflect.ownKeys(target);
      },
      getOwnPropertyDescriptor() {
        return { configurable: true, enumerable: true };
      },
    },
  );
  return createDesktopProductionRouteRegistry({ implementedLoaders });
}

function render(element) {
  return renderToStaticMarkup(React.createElement(I18nProvider, null, element));
}
