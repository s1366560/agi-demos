import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const featureRoot = '/tmp/agistack-desktop-test-dist/src/features/tenant-admin';
const { DesktopApiError } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { createTenantGovernanceClient } = require(`${featureRoot}/tenantGovernanceClient.js`);
const { createTenantBillingClient } = require(`${featureRoot}/tenantBillingClient.js`);
const { createTenantAuditClient } = require(`${featureRoot}/tenantAuditClient.js`);
const { createTenantTrustClient } = require(`${featureRoot}/tenantTrustClient.js`);
const { createTenantGovernanceController } = require(
  `${featureRoot}/tenantGovernanceController.js`,
);
const { createTenantBillingController } = require(`${featureRoot}/tenantBillingController.js`);
const { createTenantAuditController } = require(`${featureRoot}/tenantAuditController.js`);
const { createTenantTrustController } = require(`${featureRoot}/tenantTrustController.js`);
const { createTenantGovernanceRouteModuleLoader } = require(
  `${featureRoot}/tenantGovernanceRouteModule.js`,
);
const { createTenantBillingRouteModuleLoader } = require(
  `${featureRoot}/tenantBillingRouteModule.js`,
);
const { createTenantAuditRouteModuleLoader } = require(`${featureRoot}/tenantAuditRouteModule.js`);
const { createTenantTrustRouteModuleLoader } = require(`${featureRoot}/tenantTrustRouteModule.js`);

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: 'must-not-cross-cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
  workspaceRoot: '/workspace',
});
const localConfig = Object.freeze({
  ...cloudConfig,
  apiBaseUrl: 'http://127.0.0.1:43117',
  apiKey: 'local-session',
  localApiToken: 'private-launch',
  mode: 'local',
});
const scope = Object.freeze({ authority: 'cloud', tenantId: 'tenant-1' });
const localScope = Object.freeze({ authority: 'local', tenantId: 'tenant-1' });
const trustScope = Object.freeze({ ...scope, workspaceId: 'workspace-1' });
const localTrustScope = Object.freeze({
  ...localScope,
  workspaceId: 'workspace-1',
});

test('four tenant admin routes publish lazy native cloud-only modules', async () => {
  const cases = [
    [createTenantGovernanceRouteModuleLoader, 'tenant-tenant-users'],
    [createTenantBillingRouteModuleLoader, 'tenant-tenant-billing'],
    [createTenantAuditRouteModuleLoader, 'tenant-tenant-audit-logs'],
    [createTenantTrustRouteModuleLoader, 'tenant-tenant-trust-policies'],
  ];
  for (const [factory, routeId] of cases) {
    let calls = 0;
    const loader = factory({
      createBinding() {
        calls += 1;
        throw new Error('binding is created only while rendering');
      },
    });
    assert.equal(calls, 0);
    const module = await loader();
    assert.deepEqual(
      {
        routeId: module.routeId,
        capability: module.capability,
        localPolicy: module.localPolicy,
        disposition: module.disposition,
        availability: module.availability,
        reasonCode: module.reasonCode,
        Surface: typeof module.Surface,
      },
      {
        routeId,
        capability: routeId,
        localPolicy: 'cloud_only',
        disposition: 'implemented',
        availability: 'available',
        reasonCode: null,
        Surface: 'function',
      },
    );
  }
});

test('governance client observes owner permissions and uses trusted-session authority for mutations', async () => {
  const requests = [];
  await withFetch(
    async (url, init = {}) => {
      requests.push({ url: String(url), init });
      const path = new URL(String(url)).pathname;
      if (path === '/api/v1/workspace-context') return json(contextPayload('owner'));
      if (path.endsWith('/members') && (init.method ?? 'GET') === 'GET') {
        return json({ members: [memberPayload()], total: 1 });
      }
      if (path.endsWith('/invitations') && (init.method ?? 'GET') === 'GET') {
        return json({
          items: [invitationPayload()],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }
      if (path.endsWith('/invitations')) return json(invitationPayload(), 201);
      if (path.endsWith('/members/user-1') && init.method === 'PATCH') {
        return json({ message: 'ok', user_id: 'user-1', role: 'admin' });
      }
      if (path.endsWith('/members/user-1') && init.method === 'DELETE') return noContent();
      throw new Error(`unexpected request ${init.method ?? 'GET'} ${path}`);
    },
    async () => {
      const client = createTenantGovernanceClient(cloudConfig);
      const observed = await client.load(scope);
      assert.equal(observed.availability, 'available');
      assert.equal(observed.membershipRole, 'owner');
      assert.deepEqual(observed.allowedActions, [
        'view',
        'list',
        'invite',
        'inspect-pending-invitation-count',
        'change-role',
        'remove-member',
      ]);
      assert.equal(observed.members[0].email, 'owner@example.test');
      assert.equal(observed.pendingInvitationTotal, 1);
      await client.invite(scope, {
        email: 'new@example.test',
        role: 'member',
        message: '',
      });
      await client.changeRole(scope, 'user-1', 'admin');
      await client.removeMember(scope, 'user-1');
    },
  );
  assert.equal(requests.length, 9);
  for (const request of requests) {
    const headers = new Headers(request.init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer trusted-session');
    assert.equal(headers.has('X-Agistack-Launch'), false);
    assert.equal(request.init.credentials, 'omit');
  }
});

test('billing client closes permissions and remains degraded until invoice file IPC exists', async () => {
  const requests = [];
  await withFetch(
    async (url, init = {}) => {
      requests.push({ url: String(url), init });
      const path = new URL(String(url)).pathname;
      if (path === '/api/v1/workspace-context') return json(contextPayload('owner'));
      if (path.endsWith('/billing')) return json(billingPayload());
      if (path.endsWith('/invoices')) return json({ invoices: [invoicePayload()] });
      if (path.endsWith('/upgrade')) {
        return json({ message: 'ok', tenant: billingPayload().tenant });
      }
      throw new Error(`unexpected request ${init.method ?? 'GET'} ${path}`);
    },
    async () => {
      const client = createTenantBillingClient(cloudConfig);
      const observed = await client.load(scope);
      assert.equal(observed.availability, 'degraded');
      assert.equal(observed.reasonCode, 'tenant_billing_invoice_download_file_ipc_unavailable');
      assert.deepEqual(observed.allowedActions, [
        'view',
        'inspect-usage',
        'list-invoices',
        'upgrade-plan',
      ]);
      assert.equal(observed.allowedActions.includes('download-invoice'), false);
      await client.upgradePlan(scope, 'pro');
    },
  );
  assert.deepEqual(
    requests.map(({ init }) => init.method ?? 'GET'),
    ['GET', 'GET', 'GET', 'GET', 'POST'],
  );
});

test('audit client observes filter, runtime-summary, and bounded native export authority', async () => {
  const requests = [];
  await withFetch(
    async (url, init = {}) => {
      requests.push({ url: String(url), init });
      const path = new URL(String(url)).pathname;
      if (path === '/api/v1/workspace-context') return json(contextPayload('member'));
      if (path.endsWith('/runtime-hooks/summary')) return json(auditSummaryPayload());
      if (path.endsWith('/filter')) {
        return json({
          items: [auditEntryPayload()],
          total: 1,
          limit: 20,
          offset: 0,
        });
      }
      if (path.endsWith('/audit-logs')) {
        const query = new URL(String(url)).searchParams;
        assert.equal(query.get('limit'), '1');
        assert.equal(query.get('offset'), '0');
        return json({
          items: [auditEntryPayload()],
          total: 7,
          limit: 1,
          offset: 0,
        });
      }
      throw new Error(`unexpected request ${init.method ?? 'GET'} ${path}`);
    },
    async () => {
      const client = createTenantAuditClient(cloudConfig);
      const observed = await client.load(scope, {
        action: 'workspace.updated',
        resourceType: 'workspace',
        actor: 'user-1',
        limit: 20,
        offset: 0,
      });
      assert.equal(observed.availability, 'available');
      assert.equal(observed.reasonCode, null);
      assert.deepEqual(observed.allowedActions, [
        'view',
        'filter',
        'inspect-runtime-hooks',
        'export',
      ]);
      assert.equal(observed.entries[0].action, 'workspace.updated');
      assert.equal(observed.runtimeSummary.total, 1);
      assert.equal(observed.authorityRevision, 7);
    },
  );
  const filtered = new URL(
    requests.find(({ url }) => new URL(url).pathname.endsWith('/filter')).url,
  );
  assert.equal(filtered.pathname.endsWith('/filter'), true);
  assert.equal(filtered.searchParams.get('resource_type'), 'workspace');
  assert.equal(filtered.searchParams.get('limit'), '20');
});

test('audit client exports the active filters through a bounded binary request', async () => {
  const requests = [];
  await withFetch(
    async (url, init = {}) => {
      requests.push({ url: String(url), init });
      const target = new URL(String(url));
      assert.equal(target.pathname, '/api/v1/tenants/tenant-1/audit-logs/export');
      assert.equal(target.searchParams.get('format'), 'csv');
      assert.equal(target.searchParams.get('action'), 'workspace.updated');
      assert.equal(target.searchParams.get('resource_type'), 'workspace');
      assert.equal(target.searchParams.get('actor'), 'user-1');
      return new Response('id,action\naudit-1,workspace.updated\n', {
        status: 200,
        headers: {
          'Content-Type': 'text/csv; charset=utf-8',
          'Content-Length': '37',
        },
      });
    },
    async () => {
      const result = await createTenantAuditClient(cloudConfig).exportLogs(
        scope,
        'csv',
        {
          action: 'workspace.updated',
          resourceType: 'workspace',
          actor: 'user-1',
        },
      );
      assert.equal(result.suggestedName, 'audit-logs.csv');
      assert.equal(result.mimeType, 'text/csv');
      assert.equal(await result.blob.text(), 'id,action\naudit-1,workspace.updated\n');
    },
  );
  assert.equal(requests.length, 1);
  assert.equal(new Headers(requests[0].init.headers).get('Accept'), 'text/csv');
  assert.equal(
    new Headers(requests[0].init.headers).get('Authorization'),
    'Bearer trusted-session',
  );
});

test('audit client cancels an unknown-length direct response at the native file limit', async () => {
  let cancelled = false;
  await withFetch(
    async () =>
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(new Uint8Array(8 * 1024 * 1024));
            controller.enqueue(new Uint8Array(8 * 1024 * 1024));
            controller.enqueue(Uint8Array.of(1));
          },
          cancel() {
            cancelled = true;
          },
        }),
        { headers: { 'Content-Type': 'text/csv' } },
      ),
    async () => {
      await assert.rejects(
        createTenantAuditClient(cloudConfig).exportLogs(scope, 'csv'),
        (error) => reasonCode(error) === 'tenant_audit_export_too_large',
      );
    },
  );
  assert.equal(cancelled, true);
});

test('audit client reuses an unfiltered page total as authority revision', async () => {
  const auditCalls = [];
  await withFetch(
    async (url) => {
      const parsed = new URL(String(url));
      if (parsed.pathname === '/api/v1/workspace-context') return json(contextPayload('member'));
      if (parsed.pathname.endsWith('/runtime-hooks/summary')) {
        return json(auditSummaryPayload());
      }
      if (parsed.pathname.endsWith('/audit-logs')) {
        auditCalls.push(parsed.search);
        return json({
          items: [auditEntryPayload()],
          total: 11,
          limit: 5,
          offset: 5,
        });
      }
      throw new Error(`unexpected request ${parsed.pathname}`);
    },
    async () => {
      const observed = await createTenantAuditClient(cloudConfig).load(scope, {
        limit: 5,
        offset: 5,
      });
      assert.equal(observed.total, 11);
      assert.equal(observed.authorityRevision, 11);
    },
  );
  assert.deepEqual(auditCalls, ['?limit=5&offset=5']);
});

test('governance accepts nullable backend member names without weakening the member contract', async () => {
  await withFetch(
    async (url, init = {}) => {
      const path = new URL(String(url)).pathname;
      if (path === '/api/v1/workspace-context') return json(contextPayload('member'));
      if (path.endsWith('/members') && (init.method ?? 'GET') === 'GET') {
        return json({
          members: [{ ...memberPayload(), name: null }],
          total: 1,
        });
      }
      throw new Error(`unexpected request ${init.method ?? 'GET'} ${path}`);
    },
    async () => {
      const observed = await createTenantGovernanceClient(cloudConfig).load(scope);
      assert.equal(observed.members[0].name, null);
    },
  );
});

test('trust client requires a real workspace scope and closes admin mutations', async () => {
  const requests = [];
  await withFetch(
    async (url, init = {}) => {
      requests.push({ url: String(url), init });
      const parsed = new URL(String(url));
      if (parsed.pathname === '/api/v1/workspace-context') return json(contextPayload('admin'));
      if (parsed.pathname.endsWith('/policies') && (init.method ?? 'GET') === 'GET') {
        assert.equal(parsed.searchParams.get('workspace_id'), 'workspace-1');
        return json({ items: [trustPolicyPayload()] });
      }
      if (parsed.pathname.endsWith('/policies')) return json(trustPolicyPayload(), 201);
      if (parsed.pathname.endsWith('/policies/policy-1')) return json(trustPolicyPayload());
      throw new Error(`unexpected request ${init.method ?? 'GET'} ${parsed.pathname}`);
    },
    async () => {
      const client = createTenantTrustClient(cloudConfig);
      const observed = await client.load(trustScope);
      assert.equal(observed.availability, 'available');
      assert.equal(observed.reasonCode, null);
      assert.deepEqual(observed.allowedActions, ['view', 'list', 'create', 'revoke']);
      await client.create(trustScope, {
        agentInstanceId: 'agent-1',
        actionType: 'terminal.execute',
        grantType: 'always',
      });
      await client.revoke(trustScope, 'policy-1');
      await assert.rejects(
        client.load({ ...trustScope, workspaceId: 'default' }),
        (error) => reasonCode(error) === 'tenant_trust_workspace_scope_invalid',
      );
    },
  );
  assert.equal(requests.length, 6);
});

test('all four Local clients fail closed with catalog reason codes before network access', async () => {
  let fetchCalls = 0;
  await withFetch(
    async () => {
      fetchCalls += 1;
      throw new Error('must not call Cloud from Local');
    },
    async () => {
      const cases = [
        [
          () => createTenantGovernanceClient(localConfig).load(localScope),
          'cloud_tenant_membership_not_applicable',
        ],
        [
          () => createTenantBillingClient(localConfig).load(localScope),
          'cloud_billing_authority_not_applicable',
        ],
        [
          () => createTenantAuditClient(localConfig).load(localScope),
          'cloud_tenant_audit_authority_not_applicable',
        ],
        [
          () => createTenantTrustClient(localConfig).load(localTrustScope),
          'cloud_tenant_trust_governance_not_applicable',
        ],
      ];
      for (const [invoke, expectedReason] of cases) {
        await assert.rejects(invoke(), (error) => {
          assert.equal(error instanceof DesktopApiError, true);
          assert.equal(error.status, 501);
          assert.equal(reasonCode(error), expectedReason);
          return true;
        });
      }
    },
  );
  assert.equal(fetchCalls, 0);
});

test('four controllers expose stale, forbidden, conflict, retry, and empty presentation states', async () => {
  const deferred = Promise.withResolvers();
  const governance = createTenantGovernanceController({
    client: {
      load: () => deferred.promise,
      invite: async () => {},
      changeRole: async () => {},
      removeMember: async () => {},
    },
    initialScope: scope,
  });
  const loading = governance.load(scope);
  assert.equal(governance.getSnapshot().state, 'loading');
  deferred.resolve(governanceSnapshot({ members: [] }));
  await loading;
  assert.equal(governance.getSnapshot().state, 'empty');

  const billing = createTenantBillingController({
    client: {
      load: async () => {
        throw new DesktopApiError('forbidden', 403, {});
      },
      upgradePlan: async () => {},
    },
    initialScope: scope,
  });
  await billing.load(scope);
  assert.equal(billing.getSnapshot().state, 'forbidden');
  assert.equal(billing.getSnapshot().retryVisible, false);

  const auditDeferred = Promise.withResolvers();
  const audit = createTenantAuditController({
    client: {
      load: () => auditDeferred.promise,
      exportLogs: async () => ({
        suggestedName: 'audit-logs.csv',
        mimeType: 'text/csv',
        blob: new Blob(['audit']),
      }),
    },
    initialScope: scope,
    saveExport: async (input) => {
      assert.equal(input.suggestedName, 'audit-logs.csv');
      assert.equal(input.mimeType, 'text/csv');
      assert.equal(await input.blob.text(), 'audit');
      return { status: 'saved', bytesWritten: 5 };
    },
  });
  const auditLoading = audit.load(scope);
  auditDeferred.resolve(auditSnapshot());
  await auditLoading;
  const reload = audit.load(scope);
  assert.equal(audit.getSnapshot().state, 'stale');
  await reload;
  assert.equal(audit.getSnapshot().state, 'ready');
  assert.deepEqual(await audit.exportLogs('csv'), { status: 'saved', bytesWritten: 5 });

  const trust = createTenantTrustController({
    client: {
      load: async () => {
        throw new DesktopApiError('conflict', 409, {});
      },
      create: async () => {},
      revoke: async () => {},
    },
    initialScope: trustScope,
  });
  await trust.load(trustScope);
  assert.equal(trust.getSnapshot().state, 'conflict');
  assert.equal(trust.getSnapshot().retryVisible, true);
});

function contextPayload(role) {
  return {
    context: {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      revision: 3,
      updated_at: '2026-08-05T00:00:00Z',
    },
    membership_role: role,
  };
}

function memberPayload(overrides = {}) {
  return {
    user_id: 'user-1',
    email: 'owner@example.test',
    name: 'Owner',
    role: 'owner',
    permissions: { admin: true },
    created_at: '2026-08-05T00:00:00Z',
    ...overrides,
  };
}

function invitationPayload(overrides = {}) {
  return {
    id: 'invite-1',
    tenant_id: 'tenant-1',
    email: 'pending@example.test',
    role: 'member',
    status: 'pending',
    invited_by: 'user-1',
    expires_at: '2026-08-12T00:00:00Z',
    created_at: '2026-08-05T00:00:00Z',
    ...overrides,
  };
}

function invoicePayload(overrides = {}) {
  return {
    id: 'invoice-1',
    amount: 1200,
    currency: 'USD',
    status: 'paid',
    period_start: '2026-07-01T00:00:00Z',
    period_end: '2026-08-01T00:00:00Z',
    created_at: '2026-08-01T00:00:00Z',
    paid_at: '2026-08-01T00:00:00Z',
    invoice_url: 'https://billing.memstack.test/invoice-1',
    ...overrides,
  };
}

function billingPayload() {
  return {
    tenant: {
      id: 'tenant-1',
      name: 'Tenant One',
      plan: 'free',
      storage_limit: 1024,
    },
    usage: { projects: 2, memories: 10, users: 3, storage: 128 },
    invoices: [invoicePayload()],
  };
}

function auditEntryPayload() {
  return {
    id: 'audit-1',
    timestamp: '2026-08-05T00:00:00Z',
    actor: 'user-1',
    actor_name: 'Owner',
    action: 'workspace.updated',
    resource_type: 'workspace',
    resource_id: 'workspace-1',
    tenant_id: 'tenant-1',
    details: {},
    ip_address: null,
    user_agent: null,
  };
}

function auditSummaryPayload() {
  return {
    total: 1,
    action_counts: { 'runtime_hook.completed': 1 },
    executor_counts: { shell: 1 },
    family_counts: { runtime: 1 },
    isolation_mode_counts: { sandbox: 1 },
    latest_timestamp: '2026-08-05T00:00:00Z',
  };
}

function trustPolicyPayload() {
  return {
    id: 'policy-1',
    tenant_id: 'tenant-1',
    workspace_id: 'workspace-1',
    agent_instance_id: 'agent-1',
    action_type: 'terminal.execute',
    granted_by: 'user-1',
    grant_type: 'always',
    scope: 'agent',
    revision: 1,
    revoked_by: null,
    revoked_at: null,
    created_at: '2026-08-05T00:00:00Z',
    deleted_at: null,
  };
}

function governanceSnapshot(overrides = {}) {
  const data = {
    membershipRole: 'owner',
    members: [memberPayload()],
    invitations: [],
    pendingInvitationTotal: 0,
    ...overrides,
  };
  return {
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: ['view', 'list'],
    data,
    ...data,
  };
}

function auditSnapshot() {
  const data = {
    membershipRole: 'member',
    entries: [auditEntryPayload()],
    total: 1,
    limit: 20,
    offset: 0,
    runtimeSummary: auditSummaryPayload(),
    query: { limit: 20, offset: 0 },
  };
  return {
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: ['view', 'filter', 'inspect-runtime-hooks', 'export'],
    data,
    ...data,
  };
}

async function withFetch(fetchImpl, work) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = fetchImpl;
  try {
    await work();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function noContent() {
  return new Response(null, { status: 204 });
}

function reasonCode(error) {
  return error?.payload?.reason_code ?? null;
}
