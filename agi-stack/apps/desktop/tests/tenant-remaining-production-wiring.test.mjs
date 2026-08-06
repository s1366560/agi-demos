import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const routeIds = Object.freeze([
  'tenant-tenant-patterns',
  'tenant-tenant-acp',
  'tenant-tenant-webhooks',
  'tenant-tenant-genes',
  'tenant-tenant-events',
  'tenant-tenant-decision-records',
  'tenant-tenant-org-settings',
  'tenant-tenant-settings',
]);
const localNativeIds = new Set([
  'tenant-tenant-patterns',
  'tenant-tenant-genes',
  'tenant-tenant-events',
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
  workspaceRoot: '',
});

test('remaining Tenant routes bind their typed runtime authorities in App', () => {
  for (const symbol of [
    'createTenantPatternsRouteBindingForRuntime',
    'createTenantAcpRouteBindingForRuntime',
    'createTenantWebhooksRouteBindingForRuntime',
    'createTenantGenesRouteBindingForRuntime',
    'createTenantEventsRouteBindingForRuntime',
    'createTenantDecisionRecordsRouteBindingForRuntime',
    'createTenantOrganizationSettingsRouteBindingForRuntime',
    'createTenantSettingsRouteBindingForRuntime',
    'readTenantDecisionRecordsRouteQuery',
  ]) {
    assert.match(appSource, new RegExp(symbol, 'u'), symbol);
  }
});

test('Workbench preserves observed Cloud and mixed Local provenance for remaining Tenant routes', async () => {
  const cloud = await loadSnapshot(cloudConfig, projection('cloud'));
  for (const routeId of routeIds) {
    const capability = cloud.capabilities[routeId];
    assert.equal(capability.availability, 'available', routeId);
    assert.equal(capability.provenance, 'observed', routeId);
    assert.equal(capability.authority_source, 'cloud_service', routeId);
  }

  const local = await loadSnapshot(
    { ...cloudConfig, mode: 'local', localApiToken: 'private-launch' },
    projection('local'),
  );
  for (const routeId of routeIds) {
    const capability = local.capabilities[routeId];
    if (localNativeIds.has(routeId)) {
      assert.equal(capability.availability, 'available', routeId);
      assert.equal(capability.provenance, 'observed', routeId);
      assert.equal(capability.authority_source, 'sidecar', routeId);
    } else {
      assert.equal(capability.availability, 'not_applicable', routeId);
      assert.equal(capability.provenance, 'declared', routeId);
      assert.equal(capability.authority_source, 'renderer', routeId);
    }
  }
});

async function loadSnapshot(config, capabilities) {
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
      {
        tenantRemainingCapabilityClient: {
          async load() {
            return capabilities;
          },
        },
      },
    ).loadSnapshot();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function projection(mode) {
  return Object.freeze(
    Object.fromEntries(
      routeIds.map((routeId) => {
        const observed = mode === 'cloud' || localNativeIds.has(routeId);
        return [
          routeId,
          Object.freeze({
            availability: observed ? 'available' : 'not_applicable',
            reason_code: observed ? null : `cloud_${routeId.replaceAll('-', '_')}_not_applicable`,
            service_version: observed ? '0.1.0' : null,
            contract_version: observed ? '4.0.0' : null,
            allowed_actions: observed ? Object.freeze(['view']) : Object.freeze([]),
            scope: Object.freeze({
              tenant_id: 'tenant-1',
              project_id: null,
              workspace_id:
                routeId === 'tenant-tenant-decision-records' ? 'workspace-1' : null,
              instance_id: null,
            }),
            authority_revision: observed ? 41 : null,
            authority_source: observed
              ? mode === 'local'
                ? 'sidecar'
                : 'cloud_service'
              : 'renderer',
            provenance: observed ? 'observed' : 'declared',
          }),
        ];
      }),
    ),
  );
}
