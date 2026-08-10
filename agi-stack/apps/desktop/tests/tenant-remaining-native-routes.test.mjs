import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);
const featureRoot = '/tmp/agistack-desktop-test-dist/src/features/tenant-admin';
const { createTenantPatternsClient } = require(`${featureRoot}/tenantPatternsClient.js`);
const { createTenantAcpClient } = require(`${featureRoot}/tenantAcpClient.js`);
const { createTenantWebhooksClient } = require(`${featureRoot}/tenantWebhooksClient.js`);
const { createTenantGenesClient } = require(`${featureRoot}/tenantGenesClient.js`);
const { createTenantEventsClient } = require(`${featureRoot}/tenantEventsClient.js`);
const { requestTenantManagementJson } = require(`${featureRoot}/tenantManagementHttp.js`);
const { createTenantDecisionRecordsClient } = require(
  `${featureRoot}/tenantDecisionRecordsClient.js`,
);
const { createTenantOrganizationSettingsClient } = require(
  `${featureRoot}/tenantOrganizationSettingsClient.js`,
);
const { createTenantSettingsClient } = require(`${featureRoot}/tenantSettingsClient.js`);
const { createTenantPatternsRouteModuleLoader } = require(
  `${featureRoot}/tenantPatternsRouteModule.js`,
);
const { createTenantAcpRouteModuleLoader } = require(`${featureRoot}/tenantAcpRouteModule.js`);
const { createTenantWebhooksRouteModuleLoader } = require(
  `${featureRoot}/tenantWebhooksRouteModule.js`,
);
const { createTenantGenesRouteModuleLoader } = require(`${featureRoot}/tenantGenesRouteModule.js`);
const { createTenantEventsRouteModuleLoader } = require(
  `${featureRoot}/tenantEventsRouteModule.js`,
);
const { createTenantDecisionRecordsRouteModuleLoader } = require(
  `${featureRoot}/tenantDecisionRecordsRouteModule.js`,
);
const { createTenantOrganizationSettingsRouteModuleLoader } = require(
  `${featureRoot}/tenantOrganizationSettingsRouteModule.js`,
);
const { createTenantSettingsRouteModuleLoader } = require(
  `${featureRoot}/tenantSettingsRouteModule.js`,
);
const {
  createTenantPatternsRouteBindingForRuntime,
  createTenantAcpRouteBindingForRuntime,
  createTenantWebhooksRouteBindingForRuntime,
  createTenantGenesRouteBindingForRuntime,
  createTenantEventsRouteBindingForRuntime,
  createTenantDecisionRecordsRouteBindingForRuntime,
  createTenantOrganizationSettingsRouteBindingForRuntime,
  createTenantSettingsRouteBindingForRuntime,
} = require(`${featureRoot}/tenantRemainingRouteRuntime.js`);
const {
  createTenantRemainingCapabilityClient,
  TENANT_REMAINING_CAPABILITY_IDS,
} = require(`${featureRoot}/tenantRemainingCapabilityClient.js`);
const {
  buildTenantDecisionRecordsRoutePath,
  readTenantDecisionRecordsRouteQuery,
} = require(`${featureRoot}/tenantDecisionRecordsRouteQuery.js`);

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
const localConfig = Object.freeze({
  ...cloudConfig,
  apiBaseUrl: 'http://127.0.0.1:43117',
  apiKey: 'local-session',
  localApiToken: 'private-launch-capability',
  tenantId: 'local',
  mode: 'local',
});
const cloudScope = Object.freeze({ authority: 'cloud', tenantId: 'tenant-1' });
const localScope = Object.freeze({ authority: 'local', tenantId: 'local' });
const cloudWorkspaceScope = Object.freeze({
  ...cloudScope,
  workspaceId: 'workspace-1',
});
const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('Decision Records workspace query is explicit, canonical and reloadable', () => {
  const path = buildTenantDecisionRecordsRoutePath('tenant-1', 'workspace-1');
  assert.equal(path, '/tenant/tenant-1/decision-records?workspace=workspace-1');
  assert.deepEqual(readTenantDecisionRecordsRouteQuery(`#${path}`), {
    status: 'ready',
    workspaceId: 'workspace-1',
  });
  assert.deepEqual(readTenantDecisionRecordsRouteQuery('#/tenant/tenant-1/decision-records'), {
    status: 'unavailable',
    reasonCode: 'tenant_decisions_workspace_query_required',
  });
  for (const location of [
    '#/tenant/tenant-1/decision-records?workspace=',
    '#/tenant/tenant-1/decision-records?workspace=one&workspace=two',
    '#/tenant/tenant-1/decision-records?workspace=..',
  ]) {
    assert.deepEqual(readTenantDecisionRecordsRouteQuery(location), {
      status: 'unavailable',
      reasonCode: 'tenant_decisions_workspace_query_invalid',
    });
  }
});

test('remaining tenant routes expose lazy native modules with Local policy', async () => {
  const cases = [
    [
      createTenantPatternsRouteModuleLoader,
      'tenant-tenant-patterns',
      'native_equivalent',
    ],
    [createTenantAcpRouteModuleLoader, 'tenant-tenant-acp', 'cloud_only'],
    [createTenantWebhooksRouteModuleLoader, 'tenant-tenant-webhooks', 'cloud_only'],
    [createTenantGenesRouteModuleLoader, 'tenant-tenant-genes', 'native_equivalent'],
    [createTenantEventsRouteModuleLoader, 'tenant-tenant-events', 'native_equivalent'],
    [
      createTenantDecisionRecordsRouteModuleLoader,
      'tenant-tenant-decision-records',
      'cloud_only',
    ],
    [
      createTenantOrganizationSettingsRouteModuleLoader,
      'tenant-tenant-org-settings',
      'cloud_only',
    ],
    [createTenantSettingsRouteModuleLoader, 'tenant-tenant-settings', 'cloud_only'],
  ];

  for (const [factory, routeId, localPolicy] of cases) {
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
        localPolicy,
        disposition: 'implemented',
        availability: 'available',
        reasonCode: null,
        Surface: 'function',
      },
    );
  }
});

test('Cloud clients use trusted session and exact tenant/workspace scope', async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    calls.push(`${init.method ?? 'GET'} ${parsed.pathname}${parsed.search}`);
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer trusted-session');
    if (parsed.pathname === '/api/v1/workspace-context') {
      return json({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 41 },
        membership_role: 'owner',
      });
    }
    if (parsed.pathname === '/api/v1/agent/workflows/patterns') {
      assert.equal(parsed.searchParams.get('tenant_id'), 'tenant-1');
      return json({
        patterns: [patternPayload()],
        total: 1,
        page: 1,
        page_size: 50,
      });
    }
    if (parsed.pathname === '/api/v1/acp/tenants/tenant-1/status') {
      return json(acpStatusPayload());
    }
    if (parsed.pathname === '/api/v1/acp/tenants/tenant-1/runner-pools') return json([]);
    if (parsed.pathname === '/api/v1/tenant-webhooks/tenant-1') {
      return json([webhookPayload()]);
    }
    if (parsed.pathname === '/api/v1/events/types') return json(['workspace.updated']);
    if (parsed.pathname === '/api/v1/genes/') {
      assert.equal(parsed.searchParams.get('tenant_id'), 'tenant-1');
      return json({ genes: [genePayload()], total: 1, page: 1, page_size: 20 });
    }
    if (parsed.pathname === '/api/v1/events') {
      assert.equal(parsed.searchParams.get('tenant_id'), 'tenant-1');
      if (parsed.searchParams.get('event_type') === 'workspace.updated') {
        return json({ items: [eventPayload()], total: 1, page: 1, page_size: 20 });
      }
      assert.equal(parsed.searchParams.get('page'), '1');
      assert.equal(parsed.searchParams.get('page_size'), '1');
      return json({ items: [eventPayload()], total: 7, page: 1, page_size: 1 });
    }
    if (parsed.pathname === '/api/v1/tenants/tenant-1/trust/decision-records') {
      assert.equal(parsed.searchParams.get('workspace_id'), 'workspace-1');
      return json({ items: [decisionPayload()] });
    }
    if (parsed.pathname === '/api/v1/tenants/tenant-1') return json(tenantPayload());
    if (parsed.pathname === '/api/v1/tenants/tenant-1/stats') return json({ projects: 3 });
    if (parsed.pathname === '/api/v1/tenants/tenant-1/registries') return json([]);
    if (parsed.pathname === '/api/v1/tenants/tenant-1/smtp-config') return json(null);
    if (parsed.pathname === '/api/v1/tenants/tenant-1/gene-policies') return json([]);
    throw new Error(
      `unexpected request ${init.method ?? 'GET'} ${parsed.pathname}${parsed.search}`,
    );
  };

  const snapshots = await Promise.all([
    createTenantPatternsClient(cloudConfig).load(cloudScope),
    createTenantAcpClient(cloudConfig).load(cloudScope),
    createTenantWebhooksClient(cloudConfig).load(cloudScope),
    createTenantGenesClient(cloudConfig).load(cloudScope),
    createTenantEventsClient(cloudConfig).load(cloudScope, {
      filters: { eventType: 'workspace.updated' },
    }),
    createTenantDecisionRecordsClient(cloudConfig).load(cloudWorkspaceScope),
    createTenantOrganizationSettingsClient(cloudConfig).load(cloudScope),
    createTenantSettingsClient(cloudConfig).load(cloudScope),
  ]);

  assert.deepEqual(
    snapshots.map((snapshot) => snapshot.authority),
    ['cloud', 'cloud', 'cloud', 'cloud', 'cloud', 'cloud', 'cloud', 'cloud'],
  );
  assert.equal(
    snapshots.every((snapshot) => snapshot.contractVersion === '4.0.0'),
    true,
  );
  assert.equal(
    snapshots.every((snapshot) => snapshot.scopeRevision === 41),
    true,
  );
  assert.deepEqual(snapshots[0].allowedActions, ['view', 'list', 'delete']);
  assert.deepEqual(snapshots[1].allowedActions, [
    'view',
    'view-status',
    'list-runner-pools',
    'list-agents',
    'list-sessions',
    'create-agent',
    'update-agent',
    'delete-agent',
    'test-agent',
  ]);
  assert.deepEqual(snapshots[2].allowedActions, [
    'view',
    'list',
    'list-event-types',
    'create',
    'update',
    'delete',
    'copy-secret',
  ]);
  assert.deepEqual(snapshots[4].allowedActions, [
    'view',
    'list',
    'filter',
    'paginate',
  ]);
  assert.equal(snapshots[4].total, 1);
  assert.equal(snapshots[4].scopeRevision, 41);
  assert.deepEqual(snapshots[5].allowedActions, [
    'view',
    'list',
    'filter',
    'inspect',
    'resolve-approval',
  ]);
  assert.equal(calls.some((call) => call.includes('tenant_id=tenant-1')), true);
  assert.equal(calls.some((call) => call.includes('workspace_id=workspace-1')), true);
});

test('tenant management transport presents launch capability before Local sidecar route auth', async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const headers = new Headers(init.headers);
    calls.push({ url: String(url), headers });
    if (String(url).startsWith(localConfig.apiBaseUrl)) {
      if (headers.get('X-Agistack-Launch') !== 'private-launch-capability') {
        return json({ detail: 'Launch capability required' }, 401);
      }
      return json({ detail: 'Not Found' }, 404);
    }
    assert.equal(headers.get('X-Agistack-Launch'), null);
    return json({ ok: true });
  };

  await assert.rejects(
    requestTenantManagementJson(localConfig, '/api/v1/events?tenant_id=local'),
    (error) => error.status === 404,
  );
  assert.deepEqual(
    await requestTenantManagementJson(cloudConfig, '/api/v1/events?tenant_id=tenant-1'),
    { ok: true },
  );
  assert.equal(calls[0].headers.get('Authorization'), 'Bearer local-session');
  assert.equal(calls[1].headers.get('Authorization'), 'Bearer trusted-session');
});

test('Events uses context revision independently from the page total', async () => {
  const eventCalls = [];
  globalThis.fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    assert.equal(new Headers(init.headers).get('X-Agistack-Launch'), null);
    if (parsed.pathname === '/api/v1/workspace-context') {
      return json({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 41 },
        membership_role: 'member',
      });
    }
    if (parsed.pathname === '/api/v1/events/types') return json(['workspace.updated']);
    if (parsed.pathname === '/api/v1/events') {
      eventCalls.push(parsed.search);
      assert.equal(parsed.searchParams.get('page'), '2');
      assert.equal(parsed.searchParams.get('page_size'), '5');
      return json({ items: [eventPayload()], total: 13, page: 2, page_size: 5 });
    }
    throw new Error(`unexpected request ${parsed.pathname}`);
  };

  const observed = await createTenantEventsClient(cloudConfig).load(cloudScope, {
    filters: { page: 2, pageSize: 5 },
  });
  assert.equal(observed.total, 13);
  assert.equal(observed.scopeRevision, 41);
  assert.equal(Object.hasOwn(observed, 'authorityRevision'), false);
  assert.equal(eventCalls.length, 1);
});

test('Events fails closed when scope authority changes during resource observation', async () => {
  let contextCalls = 0;
  globalThis.fetch = async (url) => {
    const parsed = new URL(String(url));
    if (parsed.pathname === '/api/v1/workspace-context') {
      contextCalls += 1;
      return json({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: contextCalls === 1 ? 41 : 42,
        },
        membership_role: 'member',
      });
    }
    if (parsed.pathname === '/api/v1/events/types') return json(['workspace.updated']);
    if (parsed.pathname === '/api/v1/events') {
      return json({ items: [eventPayload()], total: 13, page: 1, page_size: 20 });
    }
    throw new Error(`unexpected request ${parsed.pathname}`);
  };

  await assert.rejects(createTenantEventsClient(cloudConfig).load(cloudScope), (error) => {
    assert.equal(error.status, 409);
    assert.equal(error.message, 'tenant_management_authority_stale');
    return true;
  });
  assert.equal(contextCalls, 2);
});

test('tenant scope observation rejects missing, negative, and cross-project revisions', async () => {
  const cases = [
    [
      { tenant_id: 'tenant-1', project_id: 'project-1' },
      502,
      'tenant_management_workspace_context_contract_invalid',
    ],
    [
      { tenant_id: 'tenant-1', project_id: 'project-1', revision: -1 },
      502,
      'tenant_management_workspace_context_contract_invalid',
    ],
    [
      { tenant_id: 'tenant-1', project_id: 'project-2', revision: 41 },
      409,
      'tenant_management_workspace_context_scope_conflict',
    ],
  ];
  for (const [context, status, reason] of cases) {
    let calls = 0;
    globalThis.fetch = async (url) => {
      calls += 1;
      assert.equal(new URL(String(url)).pathname, '/api/v1/workspace-context');
      return json({ context, membership_role: 'member' });
    };
    await assert.rejects(createTenantEventsClient(cloudConfig).load(cloudScope), (error) => {
      assert.equal(error.status, status);
      assert.equal(error.message, reason);
      return true;
    });
    assert.equal(calls, 1);
  }
});

test('Local native clients probe sidecar and return stable unavailable reasons', async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    calls.push(parsed.pathname);
    const headers = new Headers(init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer local-session');
    if (headers.get('X-Agistack-Launch') !== 'private-launch-capability') {
      return json({ detail: 'Launch capability required' }, 401);
    }
    if (parsed.pathname === '/api/v1/workspace-context') {
      return json({
        context: { tenant_id: 'local', project_id: 'project-1', revision: 41 },
        membership_role: 'member',
      });
    }
    return json({ detail: 'Not Found' }, 404);
  };

  const cases = [
    [
      createTenantPatternsClient(localConfig).load(localScope),
      'local_workflow_patterns_authority_unavailable',
    ],
    [
      createTenantGenesClient(localConfig).load(localScope),
      'local_gene_market_authority_unavailable',
    ],
    [
      createTenantEventsClient(localConfig).load(localScope),
      'local_event_ledger_authority_unavailable',
    ],
  ];
  for (const [operation, reasonCode] of cases) {
    await assert.rejects(
      operation,
      (error) => error.status === 501 && error.message === reasonCode,
    );
  }
  assert.deepEqual(calls.sort(), [
    '/api/v1/agent/workflows/patterns',
    '/api/v1/events',
    '/api/v1/events/types',
    '/api/v1/genes/',
    '/api/v1/workspace-context',
    '/api/v1/workspace-context',
    '/api/v1/workspace-context',
  ]);
});

test('Cloud-only Local clients return catalog N/A without crossing to Cloud', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('Cloud-only Local route must not fetch');
  };
  const cases = [
    [
      createTenantAcpClient(localConfig).load(localScope),
      'local_external_acp_not_applicable',
    ],
    [
      createTenantWebhooksClient(localConfig).load(localScope),
      'cloud_tenant_webhook_authority_required',
    ],
    [
      createTenantDecisionRecordsClient(localConfig).load({
        ...localScope,
        workspaceId: 'workspace-1',
      }),
      'cloud_tenant_decision_ledger_not_applicable',
    ],
    [
      createTenantOrganizationSettingsClient(localConfig).load(localScope),
      'cloud_organization_governance_not_applicable',
    ],
    [
      createTenantSettingsClient(localConfig).load(localScope),
      'cloud_tenant_settings_not_applicable',
    ],
  ];
  for (const [operation, reasonCode] of cases) {
    await assert.rejects(
      operation,
      (error) => error.status === 501 && error.message === reasonCode,
    );
  }
  assert.equal(calls, 0);
});

test('remaining Tenant clients fail closed on session and tenant mismatch', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('invalid scope must fail before fetch');
  };
  await assert.rejects(
    createTenantSettingsClient({ ...cloudConfig, apiKey: '' }).load(cloudScope),
    (error) =>
      error.status === 401 &&
      error.message === 'tenant_management_trusted_session_required',
  );
  await assert.rejects(
    createTenantEventsClient(cloudConfig).load({ ...cloudScope, tenantId: 'tenant-2' }),
    (error) =>
      error.status === 409 &&
      error.message === 'tenant_management_tenant_scope_mismatch',
  );
  assert.equal(calls, 0);
});

test('every published mutation action is reachable from its native page', () => {
  const cases = [
    ['TenantPatternsPage.tsx', ['controller.deletePattern']],
    [
      'TenantAcpPage.tsx',
      [
        'controller.createAgent',
        'controller.updateAgent',
        'controller.deleteAgent',
        'controller.testAgent',
      ],
    ],
    [
      'TenantWebhooksPage.tsx',
      ['controller.createWebhook', 'controller.updateWebhook', 'controller.deleteWebhook'],
    ],
    [
      'TenantGenesPage.tsx',
      [
        'controller.createGene',
        'controller.updateGene',
        'controller.deleteGene',
        'controller.publishGene',
        'controller.unpublishGene',
        'controller.installGene',
        'controller.rateGene',
        'controller.createReview',
        'controller.deleteReview',
      ],
    ],
    ['TenantDecisionRecordsPage.tsx', ['controller.resolveApproval']],
    [
      'TenantOrganizationSettingsPage.tsx',
      [
        'controller.saveRegistry',
        'controller.deleteRegistry',
        'controller.testRegistry',
        'controller.saveSmtp',
        'controller.deleteSmtp',
        'controller.testSmtp',
        'controller.saveGenePolicy',
        'controller.deleteGenePolicy',
      ],
    ],
    ['TenantSettingsPage.tsx', ['controller.updateTenant', 'controller.deleteTenant']],
  ];
  for (const [filename, needles] of cases) {
    const source = readFileSync(
      new URL(`../src/features/tenant-admin/${filename}`, import.meta.url),
      'utf8',
    );
    for (const needle of needles) assert.match(source, new RegExp(escapeRegExp(needle)));
  }
});

test('remaining Tenant runtime bindings preserve mode and exact workspace scope', () => {
  const context = Object.freeze({
    tenantId: 'tenant-1',
    workspaceId: 'route-workspace-must-not-win',
  });
  const factories = [
    createTenantPatternsRouteBindingForRuntime,
    createTenantAcpRouteBindingForRuntime,
    createTenantWebhooksRouteBindingForRuntime,
    createTenantGenesRouteBindingForRuntime,
    createTenantEventsRouteBindingForRuntime,
    createTenantOrganizationSettingsRouteBindingForRuntime,
    createTenantSettingsRouteBindingForRuntime,
  ];
  for (const factory of factories) {
    assert.deepEqual(factory(cloudConfig, context).scope, cloudScope);
    assert.deepEqual(factory(localConfig, { ...context, tenantId: 'local' }).scope, localScope);
  }
  assert.deepEqual(
    createTenantDecisionRecordsRouteBindingForRuntime(cloudConfig, context).scope,
    cloudWorkspaceScope,
  );
});

test('Cloud capability authority accepts only observed v4 exact-scope contracts', async () => {
  const calls = [];
  const capabilities = await createTenantRemainingCapabilityClient(
    cloudConfig,
    capabilityDependencies('cloud', calls),
  ).load();

  assert.deepEqual(TENANT_REMAINING_CAPABILITY_IDS, Object.keys(ACTIONS_BY_CAPABILITY));
  assert.deepEqual(calls.sort(), [...TENANT_REMAINING_CAPABILITY_IDS].sort());
  for (const id of TENANT_REMAINING_CAPABILITY_IDS) {
    assert.equal(capabilities[id].availability, 'available');
    assert.equal(capabilities[id].authority_source, 'cloud_service');
    assert.equal(capabilities[id].provenance, 'observed');
    assert.equal(capabilities[id].contract_version, '4.0.0');
    assert.equal(capabilities[id].authority_revision, 41);
    assert.deepEqual(capabilities[id].allowed_actions, ACTIONS_BY_CAPABILITY[id]);
    assert.equal(capabilities[id].scope.tenant_id, 'tenant-1');
  }
  assert.equal(
    capabilities['tenant-tenant-decision-records'].scope.workspace_id,
    'workspace-1',
  );
});

test('Local authority observes three sidecar routes and declares five N/A', async () => {
  const calls = [];
  const capabilities = await createTenantRemainingCapabilityClient(
    localConfig,
    capabilityDependencies('sidecar', calls),
  ).load();
  assert.deepEqual(calls.sort(), [
    'tenant-tenant-events',
    'tenant-tenant-genes',
    'tenant-tenant-patterns',
  ]);
  for (const id of [
    'tenant-tenant-patterns',
    'tenant-tenant-genes',
    'tenant-tenant-events',
  ]) {
    assert.equal(capabilities[id].availability, 'available');
    assert.equal(capabilities[id].authority_source, 'sidecar');
    assert.equal(capabilities[id].provenance, 'observed');
  }
  const declaredReasons = {
    'tenant-tenant-acp': 'local_external_acp_not_applicable',
    'tenant-tenant-webhooks': 'cloud_tenant_webhook_authority_required',
    'tenant-tenant-decision-records': 'cloud_tenant_decision_ledger_not_applicable',
    'tenant-tenant-org-settings': 'cloud_organization_governance_not_applicable',
    'tenant-tenant-settings': 'cloud_tenant_settings_not_applicable',
  };
  for (const [id, reason] of Object.entries(declaredReasons)) {
    assert.equal(capabilities[id].availability, 'not_applicable');
    assert.equal(capabilities[id].reason_code, reason);
    assert.equal(capabilities[id].authority_source, 'renderer');
    assert.equal(capabilities[id].provenance, 'declared');
    assert.deepEqual(capabilities[id].allowed_actions, []);
  }
});

test('remaining authority rejects mismatched authority and workspace scope', async () => {
  const calls = [];
  const dependencies = capabilityDependencies('cloud', calls);
  dependencies.patterns = {
    async load(scope) {
      return observedSnapshot(
        'sidecar',
        scope,
        ACTIONS_BY_CAPABILITY['tenant-tenant-patterns'],
      );
    },
  };
  const capabilities = await createTenantRemainingCapabilityClient(
    cloudConfig,
    dependencies,
  ).load();
  assert.equal(capabilities['tenant-tenant-patterns'].availability, 'unavailable');
  assert.equal(
    capabilities['tenant-tenant-patterns'].reason_code,
    'tenant_patterns_authority_contract_invalid',
  );
  assert.equal(capabilities['tenant-tenant-patterns'].provenance, 'observed');

  const missingRevisionDependencies = capabilityDependencies('cloud', []);
  missingRevisionDependencies.patterns = {
    async load(scope) {
      const { scopeRevision: _scopeRevision, ...snapshot } = observedSnapshot(
        'cloud',
        scope,
        ACTIONS_BY_CAPABILITY['tenant-tenant-patterns'],
      );
      return snapshot;
    },
  };
  const missingRevision = await createTenantRemainingCapabilityClient(
    cloudConfig,
    missingRevisionDependencies,
  ).load();
  assert.equal(missingRevision['tenant-tenant-patterns'].availability, 'unavailable');
  assert.equal(
    missingRevision['tenant-tenant-patterns'].reason_code,
    'tenant_patterns_authority_contract_invalid',
  );

  let decisionCalls = 0;
  const missingWorkspaceDependencies = capabilityDependencies('cloud', []);
  missingWorkspaceDependencies.decisionRecords = {
    async load() {
      decisionCalls += 1;
      throw new Error('missing workspace must fail before observation');
    },
  };
  const missingWorkspace = await createTenantRemainingCapabilityClient(
    { ...cloudConfig, workspaceId: '' },
    missingWorkspaceDependencies,
  ).load();
  assert.equal(decisionCalls, 0);
  assert.deepEqual(
    {
      availability: missingWorkspace['tenant-tenant-decision-records'].availability,
      reason: missingWorkspace['tenant-tenant-decision-records'].reason_code,
      source: missingWorkspace['tenant-tenant-decision-records'].authority_source,
      provenance: missingWorkspace['tenant-tenant-decision-records'].provenance,
    },
    {
      availability: 'unavailable',
      reason: 'tenant_decisions_workspace_scope_unavailable',
      source: 'renderer',
      provenance: 'declared',
    },
  );
});

const ACTIONS_BY_CAPABILITY = Object.freeze({
  'tenant-tenant-patterns': Object.freeze(['view', 'list', 'delete']),
  'tenant-tenant-acp': Object.freeze([
    'view',
    'view-status',
    'list-runner-pools',
    'list-agents',
    'list-sessions',
    'create-agent',
    'update-agent',
    'delete-agent',
    'test-agent',
  ]),
  'tenant-tenant-webhooks': Object.freeze([
    'view',
    'list',
    'list-event-types',
    'create',
    'update',
    'delete',
    'copy-secret',
  ]),
  'tenant-tenant-genes': Object.freeze([
    'view',
    'list',
    'inspect-genome',
    'inspect-evolution',
    'list-reviews',
    'rate',
    'create-review',
    'delete-own-review',
    'create',
    'update',
    'delete',
    'publish',
    'unpublish',
    'install',
  ]),
  'tenant-tenant-events': Object.freeze(['view', 'list', 'filter', 'paginate']),
  'tenant-tenant-decision-records': Object.freeze([
    'view',
    'list',
    'filter',
    'inspect',
    'resolve-approval',
  ]),
  'tenant-tenant-org-settings': Object.freeze([
    'view',
    'inspect-stats',
    'inspect-smtp',
    'manage-registries',
    'update-smtp',
    'delete-smtp',
    'test-smtp',
    'manage-gene-policies',
  ]),
  'tenant-tenant-settings': Object.freeze(['view', 'inspect-usage', 'update', 'delete']),
});

function capabilityDependencies(authority, calls) {
  const load = (id) => async (scope) => {
    calls.push(id);
    const expectedMode = authority === 'sidecar' ? 'local' : 'cloud';
    assert.equal(scope.authority, expectedMode);
    if (id === 'tenant-tenant-decision-records') {
      assert.equal(scope.workspaceId, 'workspace-1');
    }
    return observedSnapshot(authority, scope, ACTIONS_BY_CAPABILITY[id]);
  };
  return {
    patterns: { load: load('tenant-tenant-patterns') },
    acp: { load: load('tenant-tenant-acp') },
    webhooks: { load: load('tenant-tenant-webhooks') },
    genes: { load: load('tenant-tenant-genes') },
    events: { load: load('tenant-tenant-events') },
    decisionRecords: { load: load('tenant-tenant-decision-records') },
    organizationSettings: { load: load('tenant-tenant-org-settings') },
    settings: { load: load('tenant-tenant-settings') },
  };
}

function observedSnapshot(authority, scope, allowedActions) {
  return Object.freeze({
    authority,
    scope,
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    scopeRevision: 41,
    allowedActions,
    data: Object.freeze({}),
  });
}

function json(payload, status = 200) {
  return new Response(payload === undefined ? '' : JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function patternPayload() {
  return {
    id: 'pattern-1',
    name: 'Review pattern',
    description: 'Review changes',
    usage_count: 4,
    success_rate: 80,
    updated_at: '2026-08-05T00:00:00Z',
    steps: [{ tool_name: 'read', tool_parameters: {} }],
  };
}

function acpStatusPayload() {
  return {
    enabled: true,
    websocketEnabled: true,
    httpBaseUrl: 'https://cloud.memstack.test/api/v1/acp',
    externalAgentsConfigPath: null,
    agentCount: 1,
    availableCount: 1,
    missingEnvCount: 0,
    activeSessionCount: 0,
    agents: [
      {
        id: 'agent-1',
        agentKey: 'reviewer',
        name: 'Reviewer',
        transport: 'stdio',
        command: 'reviewer',
        args: [],
        url: null,
        env: {},
        headers: {},
        runnerPoolKey: null,
        requiredLabels: {},
        cwdPolicy: {},
        enabled: true,
        source: 'tenant',
        available: true,
        missingEnv: [],
        activeSessions: 0,
        totalSessions: 0,
        promptCount: 0,
        updateCount: 0,
      },
    ],
    sessions: [],
    recentEvents: [],
  };
}

function webhookPayload() {
  return {
    id: 'webhook-1',
    tenant_id: 'tenant-1',
    name: 'Events',
    url: 'https://hooks.example.test/memstack',
    secret: null,
    events: ['workspace.updated'],
    is_active: true,
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
  };
}

function genePayload() {
  return {
    id: 'gene-1',
    name: 'Review',
    slug: 'review',
    tenant_id: 'tenant-1',
    description: 'Review code',
    category: 'development',
    version: '1.0.0',
    visibility: 'tenant',
    install_count: 1,
    avg_rating: 5,
    is_published: true,
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
  };
}

function eventPayload() {
  return {
    id: 'event-1',
    tenant_id: 'tenant-1',
    event_type: 'workspace.updated',
    message: 'Workspace updated',
    source: 'workspace',
    metadata: {},
    created_at: '2026-08-05T00:00:00Z',
  };
}

function decisionPayload() {
  return {
    id: 'decision-1',
    tenant_id: 'tenant-1',
    workspace_id: 'workspace-1',
    agent_instance_id: 'agent-instance-1',
    decision_type: 'permission',
    context_summary: 'Needs permission',
    proposal: {},
    outcome: 'pending',
    reviewer_id: null,
    review_type: null,
    review_comment: null,
    resolved_at: null,
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
    deleted_at: null,
  };
}

function tenantPayload() {
  return {
    id: 'tenant-1',
    name: 'Tenant One',
    slug: 'tenant-one',
    description: 'Tenant description',
    owner_id: 'user-1',
    plan: 'pro',
    max_projects: 10,
    max_users: 50,
    max_storage: 1024,
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
  };
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
