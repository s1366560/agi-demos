import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

import { projectOverviewOperationsV2Fixture } from './projectOverviewOperationsV2Fixture.mjs';
import { projectAgentDashboardOperationsV2Fixture } from './projectAgentDashboardOperationsV2Fixture.mjs';
import { projectAgentLogsOperationsV2Fixture } from './projectAgentLogsOperationsV2Fixture.mjs';
import { projectAgentPatternsOperationsV2Fixture } from './projectAgentPatternsOperationsV2Fixture.mjs';
import { projectCommunitiesOperationsV2Fixture } from './projectCommunitiesOperationsV2Fixture.mjs';
import { projectMemoriesOperationsV2Fixture } from './projectMemoriesOperationsV2Fixture.mjs';
import { projectTeamOperationsV2Fixture } from './projectTeamOperationsV2Fixture.mjs';
import { projectEntitiesOperationsV2Fixture } from './projectEntitiesOperationsV2Fixture.mjs';
import { projectGraphOperationsV2Fixture } from './projectGraphOperationsV2Fixture.mjs';
import { projectBlackboardOperationsV2Fixture } from './projectBlackboardOperationsV2Fixture.mjs';
import { projectWorkspacesClientV2Fixture } from './projectWorkspacesClientV2Fixture.mjs';
import { runtimePoolOperationsV2Fixture } from './runtimePoolOperationsV2Fixture.mjs';
import { runtimeClustersOperationsV2Fixture } from './runtimeClustersOperationsV2Fixture.mjs';
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
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  TENANT_AUDIT_LOGS_ROUTE_ID,
  TENANT_BILLING_ROUTE_ID,
  TENANT_TRUST_POLICIES_ROUTE_ID,
  TENANT_USERS_ROUTE_ID,
  createDesktopProductionRouteRegistry,
  registerDesktopProductionRouteLoaders,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const registrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);

const ROUTE_IDS = Object.freeze([
  'tenant-tenant-users',
  'tenant-tenant-billing',
  'tenant-tenant-audit-logs',
  'tenant-tenant-trust-policies',
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
  workspaceRoot: '/workspace',
});

test('tenant governance routes have real production route registry bindings', () => {
  assert.deepEqual(
    [
      TENANT_USERS_ROUTE_ID,
      TENANT_BILLING_ROUTE_ID,
      TENANT_AUDIT_LOGS_ROUTE_ID,
      TENANT_TRUST_POLICIES_ROUTE_ID,
    ],
    ROUTE_IDS,
  );
  for (const routeId of ROUTE_IDS) {
    assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(routeId), true, routeId);
  }

  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders(
      Object.fromEntries(
        ROUTE_IDS.map((routeId) => [routeId, implementedLoader(routeId)]),
      ),
    ),
  });
  for (const routeId of ROUTE_IDS) {
    assert.deepEqual(registry.byId.get(routeId)?.structuralReadiness, {
      status: 'ready',
    });
  }

  assert.match(registrySource, /createTenantGovernanceRouteModuleLoader/u);
  assert.match(registrySource, /createTenantBillingRouteModuleLoader/u);
  assert.match(registrySource, /createTenantAuditRouteModuleLoader/u);
  assert.match(registrySource, /createTenantTrustRouteModuleLoader/u);
  assert.match(registrySource, /createTenantGovernanceRouteBindingForRuntime/u);
  assert.match(registrySource, /createTenantBillingRouteBindingForRuntime/u);
  assert.match(registrySource, /createTenantAuditRouteBindingForRuntime/u);
  assert.match(registrySource, /createTenantTrustRouteBindingForRuntime/u);
  assert.doesNotMatch(
    appSource,
    /tenant-admin[\s\S]{0,500}(?:WebView|<webview|<iframe|openExternal|window\.open)/iu,
  );
});

test('Cloud Snapshot v4 fail-closes unversioned tenant admin authorities', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ reason_code: 'unrelated_authority_unavailable' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    });
  try {
    const client = createDesktopWorkbenchCapabilityClient(
      unavailableAutomation,
      cloudConfig,
      {
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
        projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
        projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
        projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
        projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
        projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
        runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
        runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
        projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
        tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

        tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
        tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
        tenantGovernanceClient: probe('available', null, ['view', 'list', 'invite']),
        tenantBillingClient: probe(
          'degraded',
          'tenant_billing_invoice_download_file_ipc_unavailable',
          ['view', 'inspect-usage', 'list-invoices', 'upgrade-plan'],
        ),
        tenantAuditClient: probe(
          'available',
          null,
          ['view', 'filter', 'inspect-runtime-hooks', 'export'],
          17,
        ),
        tenantTrustClient: probe('available', null, ['view', 'list', 'create', 'revoke']),
      },
    );

    const snapshot = await client.loadSnapshot();
    for (const routeId of ROUTE_IDS) {
      const capability = snapshot.capabilities[routeId];
      assert.equal(capability.provenance, 'observed', routeId);
      assert.equal(capability.authority_source, 'cloud_service', routeId);
      assert.equal(capability.scope.tenant_id, 'tenant-1', routeId);
      assert.equal(capability.scope.project_id, null, routeId);
    }
    for (const routeId of [
      'tenant-tenant-users',
      'tenant-tenant-billing',
      'tenant-tenant-trust-policies',
    ]) {
      assert.deepEqual(
        pickCapability(snapshot.capabilities[routeId]),
        {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          allowed_actions: [],
        },
        routeId,
      );
    }
    assert.deepEqual(
      pickCapability(snapshot.capabilities['tenant-tenant-audit-logs']),
      {
        availability: 'available',
        reason_code: null,
        allowed_actions: ['view', 'filter', 'inspect-runtime-hooks', 'export'],
      },
    );
    assert.equal(
      snapshot.capabilities['tenant-tenant-audit-logs'].authority_revision,
      17,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Local Snapshot keeps all four Cloud-only routes declared not-applicable', async () => {
  let loadCalls = 0;
  const neverProbe = {
    async load() {
      loadCalls += 1;
      throw new Error('Cloud-only client must not run in Local');
    },
  };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ reason_code: 'unrelated_authority_unavailable' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    });
  try {
    const client = createDesktopWorkbenchCapabilityClient(
      unavailableAutomation,
      { ...cloudConfig, mode: 'local', localApiToken: 'private-launch' },
      {
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
        projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
        projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
        projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
        projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
        projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
        runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
        runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
        projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
        tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

        tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
        tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
        tenantGovernanceClient: neverProbe,
        tenantBillingClient: neverProbe,
        tenantAuditClient: neverProbe,
        tenantTrustClient: neverProbe,
      },
    );
    const snapshot = await client.loadSnapshot();
    const reasons = {
      'tenant-tenant-users': 'cloud_tenant_membership_not_applicable',
      'tenant-tenant-billing': 'cloud_billing_authority_not_applicable',
      'tenant-tenant-audit-logs': 'cloud_tenant_audit_authority_not_applicable',
      'tenant-tenant-trust-policies': 'cloud_tenant_trust_governance_not_applicable',
    };
    for (const routeId of ROUTE_IDS) {
      const capability = snapshot.capabilities[routeId];
      assert.equal(capability.availability, 'not_applicable', routeId);
      assert.equal(capability.reason_code, reasons[routeId], routeId);
      assert.equal(capability.provenance, 'declared', routeId);
      assert.equal(capability.authority_source, 'renderer', routeId);
      assert.deepEqual(capability.allowed_actions, [], routeId);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(loadCalls, 0);
});

function implementedLoader(routeId) {
  return async () => ({
    routeId,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: routeId,
    localPolicy: 'cloud_only',
    Surface: () => null,
  });
}

function probe(availability, reasonCode, allowedActions, authorityRevision = undefined) {
  return {
    async load(scope) {
      return {
        scope,
        authority: 'cloud',
        availability,
        reasonCode,
        contractVersion: '4.0.0',
        allowedActions,
        ...(authorityRevision === undefined ? {} : { authorityRevision }),
      };
    },
  };
}

function pickCapability(capability) {
  return {
    availability: capability.availability,
    reason_code: capability.reason_code,
    allowed_actions: [...capability.allowed_actions],
  };
}

const unavailableAutomation = Object.freeze({
  async getAutomationCapabilities() {
    throw new Error('unrelated authority unavailable');
  },
});
