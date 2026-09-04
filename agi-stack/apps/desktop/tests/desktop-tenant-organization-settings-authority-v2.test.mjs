import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(
  `${ROOT}/src/plugins/desktopTenantOrganizationSettingsAuthorityModuleV2.js`,
);
const projectionV2 = require(
  `${ROOT}/src/plugins/desktopTenantOrganizationSettingsHttpProjectionV2.js`,
);

const config = (mode = 'cloud') => ({
  apiBaseUrl: mode === 'cloud' ? 'https://api.test' : 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: mode === 'cloud' ? 'trusted-session' : 'local-session',
  localApiToken: mode === 'local' ? 'private-launch' : '',
  tenantId: mode === 'cloud' ? 'tenant-1' : 'local',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode,
  workspaceRoot: '',
});
const scope = (authority = 'cloud') => ({
  authority,
  tenantId: authority === 'cloud' ? 'tenant-1' : 'local',
});
const tenant = () => ({
  id: 'tenant-1',
  name: 'Tenant',
  slug: 'tenant',
  description: null,
  ownerId: 'owner-1',
  plan: 'pro',
  maxProjects: 2,
  maxUsers: 3,
  maxStorage: 4,
  createdAt: 'now',
  updatedAt: null,
});
const registry = (overrides = {}) => ({
  id: 'registry-1',
  tenantId: 'tenant-1',
  name: 'Registry',
  type: 'docker',
  url: 'https://registry.test',
  username: 'robot',
  isDefault: true,
  status: 'ready',
  lastChecked: null,
  createdAt: 'now',
  updatedAt: null,
  ...overrides,
});
const smtp = (overrides = {}) => ({
  id: 'smtp-1',
  tenantId: 'tenant-1',
  smtpHost: 'smtp.test',
  smtpPort: 587,
  smtpUsername: 'mailer',
  smtpPasswordMasked: '********',
  fromEmail: 'agent@example.com',
  fromName: 'Agent',
  useTls: true,
  ...overrides,
});
const genePolicy = (overrides = {}) => ({
  id: 'policy-1',
  tenantId: 'tenant-1',
  policyKey: 'review',
  policyValue: Object.freeze({ nested: Object.freeze({ enabled: true }) }),
  description: null,
  createdAt: 'now',
  updatedAt: null,
  ...overrides,
});
const snapshot = (marker = 'load') => {
  const data = Object.freeze({
    membershipRole: 'owner',
    tenant: tenant(),
    stats: Object.freeze({ marker }),
    registries: Object.freeze([registry()]),
    smtp: smtp(),
    genePolicies: Object.freeze([genePolicy()]),
  });
  return Object.freeze({
    scope: scope(),
    scopeRevision: 7,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: Object.freeze([
      'view',
      'inspect-stats',
      'inspect-smtp',
      'manage-registries',
      'update-smtp',
      'delete-smtp',
      'test-smtp',
      'manage-gene-policies',
    ]),
    data,
    ...data,
  });
};
const authority = (overrides = {}) =>
  Object.freeze({
    async load() {
      return snapshot();
    },
    async saveRegistry() {
      return registry();
    },
    async deleteRegistry() {},
    async testRegistry() {
      return Object.freeze({ ok: true });
    },
    async saveSmtp() {
      return smtp();
    },
    async deleteSmtp() {},
    async testSmtp() {
      return Object.freeze({ sent: true });
    },
    async saveGenePolicy() {
      return genePolicy();
    },
    async deleteGenePolicy() {},
    ...overrides,
  });
const service = (value, capture = {}) =>
  Object.freeze({
    bindOperation(currentConfig) {
      capture.config = currentConfig;
      return value;
    },
  });
const actions = (value, lifecycle = [], releaseError, capture = {}) => ({
  async acquireServiceOperationLease(descriptor) {
    lifecycle.push(['acquire', descriptor]);
    return {
      status: 'accepted',
      useService(use) {
        capture.use = use;
        return use(value);
      },
      async release() {
        lifecycle.push(['release']);
        if (releaseError) throw releaseError;
      },
    };
  },
});

test('catalog registers the exact Tenant Organization Settings Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) =>
      item.module_ref ===
      moduleV2.DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(
    moduleV2.desktopTenantOrganizationSettingsAuthorityDefinitionV2.contractDigest,
    entry.contract_digest,
  );
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
    },
  ]);
});

test('all nine operations hold exact tenant leases and deep-freeze operation inputs', async () => {
  const lifecycle = [];
  const captured = {};
  const signal = new AbortController().signal;
  const client = authority({
    async load(currentScope, options) {
      captured.scope = currentScope;
      captured.signal = options?.signal;
      return snapshot();
    },
    async saveRegistry(_scope, input) {
      captured.registry = input;
      return registry();
    },
    async saveSmtp(_scope, input) {
      captured.smtp = input;
      return smtp();
    },
    async saveGenePolicy(_scope, input) {
      captured.genePolicy = input;
      return genePolicy();
    },
  });
  const serviceCapture = {};
  const operations = moduleV2.createDesktopTenantOrganizationSettingsOperationsV2(() =>
    actions(service(client, serviceCapture), lifecycle),
  );
  await operations.loadTenantOrganizationSettings({ config: config(), scope: scope(), signal });
  await operations.saveTenantOrganizationRegistry({
    config: config(),
    scope: scope(),
    input: {
      name: 'Registry',
      registryType: 'docker',
      url: 'https://registry.test',
      password: 'registry-password',
    },
  });
  await operations.deleteTenantOrganizationRegistry({
    config: config(),
    scope: scope(),
    registryId: 'registry-1',
  });
  await operations.testTenantOrganizationRegistry({
    config: config(),
    scope: scope(),
    registryId: 'registry-1',
  });
  await operations.saveTenantOrganizationSmtp({
    config: config(),
    scope: scope(),
    input: {
      smtpHost: 'smtp.test',
      smtpPort: 587,
      smtpUsername: 'mailer',
      smtpPassword: 'smtp-password',
      fromEmail: 'agent@example.com',
    },
  });
  await operations.deleteTenantOrganizationSmtp({ config: config(), scope: scope() });
  await operations.testTenantOrganizationSmtp({
    config: config(),
    scope: scope(),
    recipientEmail: 'recipient@example.com',
  });
  await operations.saveTenantOrganizationGenePolicy({
    config: config(),
    scope: scope(),
    input: {
      policyKey: 'review',
      policyValue: { nested: { enabled: true } },
    },
  });
  await operations.deleteTenantOrganizationGenePolicy({
    config: config(),
    scope: scope(),
    policyKey: 'review',
  });

  assert.deepEqual(
    lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value.scope),
    Array(9).fill({ kind: 'tenant', tenant_id: 'tenant-1' }),
  );
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 9);
  assert.equal(Object.isFrozen(serviceCapture.config), true);
  assert.equal(Object.isFrozen(captured.scope), true);
  assert.equal(captured.signal, signal);
  assert.equal(Object.isFrozen(captured.registry), true);
  assert.equal(Object.isFrozen(captured.smtp), true);
  assert.equal(Object.isFrozen(captured.genePolicy), true);
  assert.equal(Object.isFrozen(captured.genePolicy.policyValue), true);
  assert.equal(Object.isFrozen(captured.genePolicy.policyValue.nested), true);
  assert.equal(
    JSON.stringify(lifecycle).includes('registry-password') ||
      JSON.stringify(lifecycle).includes('smtp-password'),
    false,
  );
});

test('operation input, service, authority and response contracts fail closed', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantOrganizationSettingsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return actions(service(authority({ load: async () => ({}) }))).acquireServiceOperationLease(
        {},
      );
    },
  }));
  assert.throws(
    () =>
      operations.saveTenantOrganizationSmtp({
        config: config(),
        scope: scope(),
        input: {
          smtpHost: 'smtp.test',
          smtpPort: -1,
          smtpUsername: 'mailer',
          smtpPassword: 'secret',
          fromEmail: 'agent@example.com',
        },
      }),
    (error) => error.code === 'desktop_tenant_organization_settings_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => operations.loadTenantOrganizationSettings({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_organization_settings_operation_response_invalid',
  );
  const malformedService = moduleV2.createDesktopTenantOrganizationSettingsOperationsV2(() =>
    actions(Object.freeze({ bindOperation: () => authority(), extra: true })),
  );
  await assert.rejects(
    () => malformedService.loadTenantOrganizationSettings({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_organization_settings_service_invalid',
  );
  const malformedAuthority = moduleV2.createDesktopTenantOrganizationSettingsOperationsV2(() =>
    actions(Object.freeze({ bindOperation: () => ({ load() {} }) })),
  );
  await assert.rejects(
    () => malformedAuthority.loadTenantOrganizationSettings({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_organization_settings_service_invalid',
  );
  await assert.rejects(
    () =>
      moduleV2
        .createDesktopTenantOrganizationSettingsOperationsV2(() => null)
        .loadTenantOrganizationSettings({ config: config(), scope: scope() }),
    (error) =>
      error.name === 'DesktopTenantOrganizationSettingsAuthorityUnavailableErrorV2' &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  const rejected = moduleV2.createDesktopTenantOrganizationSettingsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'rejected',
        reasonCode: 'desktop_renderer_generation_service_unavailable',
        runtimeCode: 'missing',
      };
    },
  }));
  await assert.rejects(
    () => rejected.loadTenantOrganizationSettings({ config: config(), scope: scope() }),
    (error) =>
      error.reasonCode === 'desktop_renderer_generation_service_unavailable' &&
      error.runtimeCode === 'missing',
  );
});

test('mutation response validators reject cross-tenant and malformed results', async () => {
  const cases = [
    [
      'saveTenantOrganizationRegistry',
      { input: { name: 'Registry', registryType: 'docker', url: 'https://registry.test' } },
      { saveRegistry: async () => registry({ tenantId: 'tenant-2' }) },
    ],
    [
      'saveTenantOrganizationSmtp',
      {
        input: {
          smtpHost: 'smtp.test',
          smtpPort: 587,
          smtpUsername: 'mailer',
          smtpPassword: 'secret',
          fromEmail: 'agent@example.com',
        },
      },
      { saveSmtp: async () => smtp({ smtpPort: -1 }) },
    ],
    [
      'saveTenantOrganizationGenePolicy',
      { input: { policyKey: 'review', policyValue: {} } },
      { saveGenePolicy: async () => genePolicy({ policyValue: null }) },
    ],
    [
      'testTenantOrganizationRegistry',
      { registryId: 'registry-1' },
      { testRegistry: async () => [] },
    ],
  ];
  for (const [operation, extra, override] of cases) {
    const operations = moduleV2.createDesktopTenantOrganizationSettingsOperationsV2(() =>
      actions(service(authority(override))),
    );
    await assert.rejects(
      () => operations[operation]({ config: config(), scope: scope(), ...extra }),
      (error) => error.code === 'desktop_tenant_organization_settings_operation_response_invalid',
      operation,
    );
  }
});

test('HMR pins in-flight work, revokes escaped use and preserves error precedence', async () => {
  let finish;
  const capture = {};
  let current = actions(
    service(
      authority({
        load: () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      }),
    ),
    [],
    undefined,
    capture,
  );
  const operations = moduleV2.createDesktopTenantOrganizationSettingsOperationsV2(() => current);
  const pending = operations.loadTenantOrganizationSettings({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(authority({ load: async () => snapshot('new') })));
  finish(snapshot('old'));
  assert.equal((await pending).stats.marker, 'old');
  assert.equal(
    (await operations.loadTenantOrganizationSettings({ config: config(), scope: scope() })).stats
      .marker,
    'new',
  );
  await assert.rejects(
    () => capture.use(service(authority())),
    (error) => error.code === 'desktop_tenant_organization_settings_operation_released',
  );

  const primary = new Error('primary');
  const primaryFailing = moduleV2.createDesktopTenantOrganizationSettingsOperationsV2(() =>
    actions(service(authority({ load: async () => { throw primary; } })), [], new Error('release')),
  );
  await assert.rejects(
    () => primaryFailing.loadTenantOrganizationSettings({ config: config(), scope: scope() }),
    primary,
  );
  const release = new Error('release-only');
  const releaseFailing = moduleV2.createDesktopTenantOrganizationSettingsOperationsV2(() =>
    actions(service(authority()), [], release),
  );
  await assert.rejects(
    () => releaseFailing.loadTenantOrganizationSettings({ config: config(), scope: scope() }),
    release,
  );
});

test('Cloud projection preserves trusted transport, role checks and exact endpoints', async () => {
  const calls = [];
  const signal = new AbortController().signal;
  const restore = mockFetch(calls, 'owner');
  try {
    const client = projectionV2.createDesktopTenantOrganizationSettingsHttpProjectionV2(config());
    await client.load(scope(), { signal });
    await client.saveRegistry(
      scope(),
      {
        name: 'Registry',
        registryType: 'docker',
        url: 'https://registry.test',
        password: 'registry-password',
      },
      { signal },
    );
    await client.deleteRegistry(scope(), 'registry-1', { signal });
    await client.testRegistry(scope(), 'registry-1', { signal });
    await client.saveSmtp(
      scope(),
      {
        smtpHost: 'smtp.test',
        smtpPort: 587,
        smtpUsername: 'mailer',
        smtpPassword: 'smtp-password',
        fromEmail: 'agent@example.com',
      },
      { signal },
    );
    await client.deleteSmtp(scope(), { signal });
    await client.testSmtp(scope(), 'recipient@example.com', { signal });
    await client.saveGenePolicy(
      scope(),
      { policyKey: 'review', policyValue: { enabled: true } },
      { signal },
    );
    await client.deleteGenePolicy(scope(), 'review', { signal });
  } finally {
    restore();
  }
  const mutationCalls = calls.filter(({ path }) => path !== '/api/v1/workspace-context');
  assert.deepEqual(
    mutationCalls.map(({ method, path }) => [method, path]),
    [
      ['GET', '/api/v1/tenants/tenant-1'],
      ['GET', '/api/v1/tenants/tenant-1/stats'],
      ['GET', '/api/v1/tenants/tenant-1/registries'],
      ['GET', '/api/v1/tenants/tenant-1/smtp-config'],
      ['GET', '/api/v1/tenants/tenant-1/gene-policies'],
      ['POST', '/api/v1/tenants/tenant-1/registries'],
      ['DELETE', '/api/v1/tenants/tenant-1/registries/registry-1'],
      ['POST', '/api/v1/tenants/tenant-1/registries/registry-1/test'],
      ['PUT', '/api/v1/tenants/tenant-1/smtp-config'],
      ['DELETE', '/api/v1/tenants/tenant-1/smtp-config'],
      ['POST', '/api/v1/tenants/tenant-1/smtp-config/test'],
      ['PUT', '/api/v1/tenants/tenant-1/gene-policies/review'],
      ['DELETE', '/api/v1/tenants/tenant-1/gene-policies/review'],
    ],
  );
  for (const call of calls) {
    assert.equal(call.authorization, 'Bearer trusted-session');
    assert.equal(call.signal, signal);
  }

  const forbiddenCalls = [];
  const restoreForbidden = mockFetch(forbiddenCalls, 'member');
  try {
    const client = projectionV2.createDesktopTenantOrganizationSettingsHttpProjectionV2(config());
    await assert.rejects(
      () =>
        client.saveRegistry(scope(), {
          name: 'Registry',
          registryType: 'docker',
          url: 'https://registry.test',
        }),
      (error) => error.status === 403 && error.message === 'tenant_org_settings_admin_required',
    );
  } finally {
    restoreForbidden();
  }
  assert.deepEqual(
    forbiddenCalls.map(({ path }) => path),
    ['/api/v1/workspace-context'],
  );
});

test('Local projection rejects all operations before any network or mutation traffic', async () => {
  const calls = [];
  const restore = mockFetch(calls, 'owner');
  try {
    const client = projectionV2.createDesktopTenantOrganizationSettingsHttpProjectionV2(
      config('local'),
    );
    const localScope = scope('local');
    const operations = [
      () => client.load(localScope),
      () =>
        client.saveRegistry(localScope, {
          name: 'Registry',
          registryType: 'docker',
          url: 'https://registry.test',
        }),
      () => client.deleteRegistry(localScope, 'registry-1'),
      () => client.testRegistry(localScope, 'registry-1'),
      () =>
        client.saveSmtp(localScope, {
          smtpHost: 'smtp.test',
          smtpPort: 587,
          smtpUsername: 'mailer',
          smtpPassword: 'secret',
          fromEmail: 'agent@example.com',
        }),
      () => client.deleteSmtp(localScope),
      () => client.testSmtp(localScope, 'recipient@example.com'),
      () => client.saveGenePolicy(localScope, { policyKey: 'review', policyValue: {} }),
      () => client.deleteGenePolicy(localScope, 'review'),
    ];
    for (const operation of operations) {
      await assert.rejects(
        operation,
        (error) =>
          error.status === 501 &&
          error.message === 'cloud_organization_governance_not_applicable',
      );
    }
  } finally {
    restore();
  }
  assert.equal(calls.length, 0);
});

test('Cloud projection uses the vault broker without renderer credentials', async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, args });
          return vaultResponse(args.request.path, args.request.method);
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('vault_bound_cloud_must_not_fetch');
  };
  try {
    const client = projectionV2.createDesktopTenantOrganizationSettingsHttpProjectionV2({
      ...config(),
      apiKey: '',
    });
    await client.load(scope());
    await client.saveSmtp(scope(), {
      smtpHost: 'smtp.test',
      smtpPort: 587,
      smtpUsername: 'mailer',
      smtpPassword: 'smtp-password',
      fromEmail: 'agent@example.com',
    });
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
    globalThis.fetch = originalFetch;
  }
  assert.equal(calls.every(({ command }) => command === 'cloud_request'), true);
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
});

function mockFetch(calls, role) {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    const path = new URL(String(url)).pathname;
    const method = init.method ?? 'GET';
    calls.push({
      path,
      method,
      authorization: new Headers(init.headers).get('Authorization'),
      signal: init.signal,
    });
    return responseFor(path, method, role);
  };
  return () => {
    globalThis.fetch = original;
  };
}

function responseFor(path, method, role) {
  if (path === '/api/v1/workspace-context') {
    return json({
      context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 7 },
      membership_role: role,
    });
  }
  if (path === '/api/v1/tenants/tenant-1') return json(tenantPayload());
  if (path.endsWith('/stats')) return json({ projects: 1 });
  if (path.endsWith('/registries') && method === 'GET') return json([registryPayload()]);
  if (path.endsWith('/registries') && method === 'POST') return json(registryPayload());
  if (path.endsWith('/registries/registry-1') && method === 'DELETE') return json();
  if (path.endsWith('/registries/registry-1/test')) return json({ ok: true });
  if (path.endsWith('/smtp-config') && method === 'GET') return json(smtpPayload());
  if (path.endsWith('/smtp-config') && method === 'PUT') return json(smtpPayload());
  if (path.endsWith('/smtp-config') && method === 'DELETE') return json();
  if (path.endsWith('/smtp-config/test')) return json({ sent: true });
  if (path.endsWith('/gene-policies') && method === 'GET') return json([genePolicyPayload()]);
  if (path.endsWith('/gene-policies/review') && method === 'PUT') {
    return json(genePolicyPayload());
  }
  if (path.endsWith('/gene-policies/review') && method === 'DELETE') return json();
  throw new Error(`unexpected request ${method} ${path}`);
}

function vaultResponse(path, method) {
  const pathname = new URL(path, 'https://api.test').pathname;
  const response = responseFor(pathname, method, 'owner');
  return response.json().then((body) => ({ status: response.status, body }));
}

function tenantPayload() {
  return {
    id: 'tenant-1',
    name: 'Tenant',
    slug: 'tenant',
    description: null,
    owner_id: 'owner-1',
    plan: 'pro',
    max_projects: 2,
    max_users: 3,
    max_storage: 4,
    created_at: 'now',
    updated_at: null,
  };
}
function registryPayload() {
  return {
    id: 'registry-1',
    tenant_id: 'tenant-1',
    name: 'Registry',
    type: 'docker',
    url: 'https://registry.test',
    username: 'robot',
    is_default: true,
    status: 'ready',
    last_checked: null,
    created_at: 'now',
    updated_at: null,
  };
}
function smtpPayload() {
  return {
    id: 'smtp-1',
    tenant_id: 'tenant-1',
    smtp_host: 'smtp.test',
    smtp_port: 587,
    smtp_username: 'mailer',
    smtp_password_masked: '********',
    from_email: 'agent@example.com',
    from_name: 'Agent',
    use_tls: true,
  };
}
function genePolicyPayload() {
  return {
    id: 'policy-1',
    tenant_id: 'tenant-1',
    policy_key: 'review',
    policy_value: { enabled: true },
    description: null,
    created_at: 'now',
    updated_at: null,
  };
}
function json(payload, status = 200) {
  return new Response(payload === undefined ? '' : JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
