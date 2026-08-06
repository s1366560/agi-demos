import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledDirectory =
  '/tmp/agistack-desktop-test-dist/src/features/device-approval';
mkdirSync(compiledDirectory, { recursive: true });
writeFileSync(`${compiledDirectory}/DeviceApprovalPage.css`, '');
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  DESKTOP_PRODUCTION_ROUTE_IDS,
  DEVICE_APPROVAL_ROUTE_ID,
  createDesktopProductionRouteRegistry,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');
const {
  createDeviceApprovalRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/device-approval/deviceApprovalRouteModule.js');
const {
  evaluateDesktopRouteAccess,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js');
const {
  deviceApprovalCapability,
} = require('/tmp/agistack-desktop-test-dist/src/features/device-approval/deviceApprovalCapability.js');

test('production registry keeps native device approval beside global native routes', async () => {
  const registry = createRegistry();
  assert.equal(DEVICE_APPROVAL_ROUTE_ID, 'device-approval');
  assert.deepEqual(
    registry.definitions.map((definition) => definition.id),
    DESKTOP_PRODUCTION_ROUTE_IDS,
  );
  const definition = registry.byId.get(DEVICE_APPROVAL_ROUTE_ID);
  assert.equal(definition.path, '/device');
  assert.deepEqual(definition.scope, ['global']);
  assert.deepEqual(definition.requiredPermission, [['authenticated']]);
  assert.equal(definition.localPolicy, 'cloud_only');

  const module = await definition.loader();
  assert.equal(module.routeId, DEVICE_APPROVAL_ROUTE_ID);
  assert.equal(module.disposition, 'implemented');
  assert.equal(module.availability, 'available');
});

test('device approval capability is Cloud fail-closed until observed and Local not applicable', () => {
  assert.deepEqual(deviceApprovalCapability({ mode: 'cloud' }), {
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
  assert.deepEqual(deviceApprovalCapability({ mode: 'local' }), {
    availability: 'not_applicable',
    reason_code: 'local_cloud_device_approval_not_applicable',
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

test('Local device approval is stopped before module loading', () => {
  const definition = createRegistry().byId.get(DEVICE_APPROVAL_ROUTE_ID);
  const access = evaluateDesktopRouteAccess({
    match: {
      definition,
      context: {},
      canonicalPath: '/device',
    },
    mode: 'local',
    permissions: new Set(['authenticated']),
    capability: deviceApprovalCapability({ mode: 'local' }),
  });
  assert.equal(access.status, 'unavailable');
  assert.equal(
    access.reasonCode,
    'local_cloud_device_approval_not_applicable',
  );
});

test('device approval route renders native code entry from the injected hash port', async () => {
  const definition = createRegistry().byId.get(DEVICE_APPROVAL_ROUTE_ID);
  const module = await definition.loader();
  const markup = render(
    React.createElement(module.Surface, {
      module,
      context: {},
    }),
  );
  assert.match(markup, /Approve another device/u);
  assert.match(markup, /value="ABCD2345"/u);
  assert.match(markup, /current@example\.test/u);
  assert.doesNotMatch(markup, /<iframe|<webview/u);
});

test('device approval implementation remains isolated from the monolithic API client', () => {
  const clientSource = readFileSync(
    new URL(
      '../src/features/device-approval/deviceApprovalClient.ts',
      import.meta.url,
    ),
    'utf8',
  );
  const pageSource = readFileSync(
    new URL(
      '../src/features/device-approval/DeviceApprovalPage.tsx',
      import.meta.url,
    ),
    'utf8',
  );
  assert.doesNotMatch(clientSource, /new DesktopApiClient|class DesktopApiClient/u);
  assert.doesNotMatch(pageSource, /window\.location|config\.mode|apiBaseUrl/u);
});

function createRegistry() {
  const implementedLoaders = new Proxy(
    {
      [DEVICE_APPROVAL_ROUTE_ID]: createDeviceApprovalRouteModuleLoader({
        createBinding: () => ({
          client: { approve: async () => ({ status: 'approved' }) },
          accountLabel: 'current@example.test',
          initialCode: 'ABCD2345',
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
          localPolicy: String(property).includes('pool') ||
            String(property).includes('clusters') ||
            String(property).includes('deploy') ||
            String(property).includes('dead-letter')
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
