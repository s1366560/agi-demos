import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const featureRoot = '/tmp/agistack-desktop-test-dist/src/features/tenant-admin';
const {
  TENANT_ADMIN_CAPABILITY_IDS,
  createTenantAdminCapabilityClient,
} = require(`${featureRoot}/tenantAdminCapabilityClient.js`);

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

test('tenant admin capability client publishes only observed Cloud actions', async () => {
  const calls = [];
  const client = createTenantAdminCapabilityClient(cloudConfig, {
    governance: authorityClient(
      calls,
      'governance',
      observed(['view', 'list', 'invite']),
    ),
    billing: authorityClient(
      calls,
      'billing',
      observed(['view', 'inspect-usage', 'list-invoices'], 'degraded', 'file_ipc_missing'),
    ),
    audit: authorityClient(
      calls,
      'audit',
      observed(
        ['view', 'filter', 'inspect-runtime-hooks'],
        'degraded',
        'file_ipc_missing',
        false,
        17,
      ),
    ),
    trust: authorityClient(
      calls,
      'trust',
      observed(['view', 'list', 'create', 'revoke'], 'available', null, true),
    ),
  });

  const capabilities = await client.load();
  assert.deepEqual(Object.keys(capabilities), TENANT_ADMIN_CAPABILITY_IDS);
  assert.deepEqual(calls.sort(), ['audit', 'billing', 'governance', 'trust']);
  assert.deepEqual(capabilities['tenant-tenant-users'], expectedCapability(['view', 'list', 'invite']));
  assert.deepEqual(
    capabilities['tenant-tenant-billing'],
    expectedCapability(
      ['view', 'inspect-usage', 'list-invoices'],
      'degraded',
      'file_ipc_missing',
    ),
  );
  assert.deepEqual(
    capabilities['tenant-tenant-trust-policies'],
    expectedCapability(['view', 'list', 'create', 'revoke'], 'available', null, true),
  );
  assert.deepEqual(
    capabilities['tenant-tenant-audit-logs'],
    expectedCapability(
      ['view', 'filter', 'inspect-runtime-hooks'],
      'degraded',
      'file_ipc_missing',
      false,
      17,
    ),
  );
});

test('tenant admin capability client keeps Local Cloud-only authorities not applicable', async () => {
  let calls = 0;
  const unavailableClient = {
    async load() {
      calls += 1;
      throw new Error('Local must not call Cloud authority');
    },
  };
  const client = createTenantAdminCapabilityClient(
    Object.freeze({
      ...cloudConfig,
      apiBaseUrl: 'http://127.0.0.1:43117',
      apiKey: 'local-session',
      localApiToken: 'private-launch',
      mode: 'local',
    }),
    {
      governance: unavailableClient,
      billing: unavailableClient,
      audit: unavailableClient,
      trust: unavailableClient,
    },
  );

  const capabilities = await client.load();
  assert.equal(calls, 0);
  assert.deepEqual(
    Object.fromEntries(
      Object.entries(capabilities).map(([id, capability]) => [
        id,
        {
          availability: capability.availability,
          reason_code: capability.reason_code,
          allowed_actions: capability.allowed_actions,
        },
      ]),
    ),
    {
      'tenant-tenant-users': {
        availability: 'not_applicable',
        reason_code: 'cloud_tenant_membership_not_applicable',
        allowed_actions: [],
      },
      'tenant-tenant-billing': {
        availability: 'not_applicable',
        reason_code: 'cloud_billing_authority_not_applicable',
        allowed_actions: [],
      },
      'tenant-tenant-audit-logs': {
        availability: 'not_applicable',
        reason_code: 'cloud_tenant_audit_authority_not_applicable',
        allowed_actions: [],
      },
      'tenant-tenant-trust-policies': {
        availability: 'not_applicable',
        reason_code: 'cloud_tenant_trust_governance_not_applicable',
        allowed_actions: [],
      },
    },
  );
});

test('tenant admin capability client fails one malformed observation closed without hiding peers', async () => {
  const client = createTenantAdminCapabilityClient(cloudConfig, {
    governance: authorityClient([], 'governance', observed(['view', 'unknown-action'])),
    billing: authorityClient([], 'billing', observed(['view'])),
    audit: authorityClient([], 'audit', observed(['view'], 'available', null, false, -1)),
    trust: authorityClient([], 'trust', observed(['view'], 'available', null, true)),
  });

  const capabilities = await client.load();
  assert.equal(capabilities['tenant-tenant-users'].availability, 'unavailable');
  assert.equal(
    capabilities['tenant-tenant-users'].reason_code,
    'tenant_governance_authority_contract_invalid',
  );
  assert.equal(capabilities['tenant-tenant-billing'].availability, 'available');
  assert.equal(capabilities['tenant-tenant-audit-logs'].availability, 'unavailable');
  assert.equal(
    capabilities['tenant-tenant-audit-logs'].reason_code,
    'tenant_audit_authority_contract_invalid',
  );
});

function authorityClient(calls, name, snapshot) {
  return {
    async load(scope, options) {
      calls.push(name);
      assert.equal(options.signal, undefined);
      assert.equal(scope.authority, 'cloud');
      assert.equal(scope.tenantId, 'tenant-1');
      if (name === 'trust') assert.equal(scope.workspaceId, 'workspace-1');
      return snapshot;
    },
  };
}

function observed(
  allowedActions,
  availability = 'available',
  reasonCode = null,
  trust = false,
  authorityRevision = undefined,
) {
  return Object.freeze({
    authority: 'cloud',
    availability,
    reasonCode,
    contractVersion: '4.0.0',
    ...(authorityRevision === undefined ? {} : { authorityRevision }),
    allowedActions: Object.freeze(allowedActions),
    scope: Object.freeze({
      authority: 'cloud',
      tenantId: 'tenant-1',
      ...(trust ? { workspaceId: 'workspace-1' } : {}),
    }),
    data: Object.freeze({}),
  });
}

function expectedCapability(
  allowedActions,
  availability = 'available',
  reasonCode = null,
  trust = false,
  authorityRevision = null,
) {
  return {
    availability,
    reason_code: reasonCode,
    service_version: '0.1.0',
    contract_version: '4.0.0',
    allowed_actions: allowedActions,
    scope: {
      tenant_id: 'tenant-1',
      project_id: null,
      workspace_id: trust ? 'workspace-1' : null,
      instance_id: null,
    },
    authority_revision: authorityRevision,
    authority_source: 'cloud_service',
    provenance: 'observed',
  };
}
