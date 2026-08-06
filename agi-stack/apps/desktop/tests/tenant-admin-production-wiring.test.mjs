import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

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

test('tenant governance routes have real production loader and App bindings', () => {
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

  assert.match(appSource, /createTenantGovernanceRouteModuleLoader/u);
  assert.match(appSource, /createTenantBillingRouteModuleLoader/u);
  assert.match(appSource, /createTenantAuditRouteModuleLoader/u);
  assert.match(appSource, /createTenantTrustRouteModuleLoader/u);
  assert.match(appSource, /createTenantGovernanceRouteBindingForRuntime/u);
  assert.match(appSource, /createTenantBillingRouteBindingForRuntime/u);
  assert.match(appSource, /createTenantAuditRouteBindingForRuntime/u);
  assert.match(appSource, /createTenantTrustRouteBindingForRuntime/u);
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
        tenantGovernanceClient: probe('available', null, ['view', 'list', 'invite']),
        tenantBillingClient: probe(
          'degraded',
          'tenant_billing_invoice_download_file_ipc_unavailable',
          ['view', 'inspect-usage', 'list-invoices', 'upgrade-plan'],
        ),
        tenantAuditClient: probe(
          'degraded',
          'tenant_audit_export_file_ipc_unavailable',
          ['view', 'filter', 'inspect-runtime-hooks'],
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
        availability: 'degraded',
        reason_code: 'tenant_audit_export_file_ipc_unavailable',
        allowed_actions: ['view', 'filter', 'inspect-runtime-hooks'],
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
