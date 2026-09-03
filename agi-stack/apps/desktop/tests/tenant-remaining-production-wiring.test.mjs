import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

import { projectOverviewOperationsV2Fixture } from './projectOverviewOperationsV2Fixture.mjs';
import { projectAgentDashboardOperationsV2Fixture } from './projectAgentDashboardOperationsV2Fixture.mjs';
import { projectAgentLogsOperationsV2Fixture } from './projectAgentLogsOperationsV2Fixture.mjs';
import { projectAgentPatternsOperationsV2Fixture } from './projectAgentPatternsOperationsV2Fixture.mjs';
import { projectGraphOperationsV2Fixture } from './projectGraphOperationsV2Fixture.mjs';
import { projectBlackboardOperationsV2Fixture } from './projectBlackboardOperationsV2Fixture.mjs';
import { projectWorkspacesClientV2Fixture } from './projectWorkspacesClientV2Fixture.mjs';
import { runtimePoolOperationsV2Fixture } from './runtimePoolOperationsV2Fixture.mjs';
import { tenantAnalyticsOperationsV2Fixture } from './tenantAnalyticsOperationsV2Fixture.mjs';
import { tenantAgentBindingsOperationsV2Fixture } from './tenantAgentBindingsOperationsV2Fixture.mjs';
import { tenantProjectsOperationsV2Fixture } from './tenantProjectsOperationsV2Fixture.mjs';
import { tenantTasksOperationsV2Fixture } from './tenantTasksOperationsV2Fixture.mjs';
import { tenantAgentDashboardOperationsV2Fixture } from './tenantAgentDashboardOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');

const registrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);
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

test('remaining Tenant routes bind their typed runtime authorities in the production registry', () => {
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
    assert.match(registrySource, new RegExp(symbol, 'u'), symbol);
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
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
        projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
        projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
        projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
        projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
        runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
        projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
        tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

        tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
        tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
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
