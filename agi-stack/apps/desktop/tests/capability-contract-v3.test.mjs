import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  desktopCapability,
  parseDesktopCapabilitySnapshot,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const {
  createDesktopWorkbenchCapabilityClient,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const fixture = JSON.parse(
  readFileSync(
    new URL('./fixtures/desktop-capability-snapshot.v3.json', import.meta.url),
    'utf8',
  ),
);

const legacyFixture = JSON.parse(
  readFileSync(
    new URL(
      '../contracts/desktop-web-parity/fixtures/capability-snapshot.v2.json',
      import.meta.url,
    ),
    'utf8',
  ),
).input.snapshot;

const nullScope = {
  tenant_id: null,
  project_id: null,
  workspace_id: null,
  instance_id: null,
};

test('DesktopCapabilitySnapshot v3 validates authority fields and preserves the App view', () => {
  const snapshot = parseDesktopCapabilitySnapshot(fixture);
  assert.deepEqual(snapshot, {
    ...fixture,
    capabilities: {
      ...fixture.capabilities,
      'device-approval': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-overview': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-projects': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-tasks': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-pool': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-runtimes': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-instances': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-clusters': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-deploy': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-instance-templates': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'tenant-tenant-dead-letter-queue': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'project-project-overview': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'project-project-search': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
      'project-project-cron-jobs': {
        availability: 'unavailable',
        reason_code: 'capability_not_declared',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: nullScope,
        authority_revision: null,
      },
    },
  });
  assert.deepEqual(desktopCapability(snapshot, 'search'), {
    ...fixture.capabilities.search,
    status: 'degraded',
    available: true,
  });
  assert.deepEqual(desktopCapability(snapshot, 'sandbox_isolation'), {
    ...fixture.capabilities.sandbox_isolation,
    status: 'not_applicable',
    available: false,
  });
});

test('DesktopCapabilitySnapshot v2 is read-only input and normalizes missing capabilities closed', () => {
  const snapshot = parseDesktopCapabilitySnapshot(legacyFixture);
  assert.equal(snapshot?.version, '3.0.0');
  assert.deepEqual(snapshot?.capabilities.search, {
    availability: 'degraded',
    reason_code: 'local_search_keyword_only',
    service_version: '0.1.0',
    contract_version: '2.0.0',
    allowed_actions: [],
    scope: nullScope,
    authority_revision: null,
  });

  const missingCapability = structuredClone(legacyFixture);
  delete missingCapability.capabilities.search;
  assert.deepEqual(
    parseDesktopCapabilitySnapshot(missingCapability)?.capabilities.search,
    {
      availability: 'unavailable',
      reason_code: 'capability_not_declared',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
    },
  );
});

test('DesktopCapabilitySnapshot v3 rejects unsafe authority state and unsupported versions', () => {
  const duplicateAction = structuredClone(fixture);
  duplicateAction.capabilities.search.allowed_actions.push('advanced');
  assert.equal(parseDesktopCapabilitySnapshot(duplicateAction), null);

  const actionOnUnavailable = structuredClone(fixture);
  actionOnUnavailable.capabilities.workspace_collaboration.allowed_actions.push(
    'update',
  );
  assert.equal(parseDesktopCapabilitySnapshot(actionOnUnavailable), null);

  const invalidScope = structuredClone(fixture);
  invalidScope.capabilities.search.scope.project_id = ' project-1 ';
  assert.equal(parseDesktopCapabilitySnapshot(invalidScope), null);

  const invalidRevision = structuredClone(fixture);
  invalidRevision.capabilities.search.authority_revision = -1;
  assert.equal(parseDesktopCapabilitySnapshot(invalidRevision), null);

  assert.equal(
    parseDesktopCapabilitySnapshot({
      version: '1.0.0',
      mode: 'local',
      capabilities: {},
    }),
    null,
  );
});

test('workbench capability client emits scoped v3 authority metadata', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        service_version: '0.1.0',
        contract_version: '2.0.0',
        mode: 'keyword_degraded',
        reason_code: 'local_embeddings_unavailable',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        projection_revision: 21,
        backfill_cursor: null,
        supported_search_types: ['advanced', 'temporal', 'faceted'],
        unavailable_search_types: ['graph_traversal', 'community'],
      }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      },
    );

  try {
    const client = createDesktopWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => ({
          service_version: '0.1.0',
          contract_version: '2.0.0',
          schema_version: 1,
          read: true,
          revision_guarded: true,
          idempotency_guarded: true,
          durable_execution: true,
          supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
          create: { allowed: true },
          edit: { allowed: true },
          toggle: { allowed: true },
          run_now: { allowed: true },
          delete: { allowed: true },
        }),
      },
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'http://127.0.0.1:4123',
        localApiToken: 'launch-capability',
        mode: 'local',
        tenantId: 'tenant-1',
        projectId: 'project-1',
        workspaceId: 'workspace-1',
      },
    );

    const snapshot = await client.loadSnapshot();
    assert.equal(snapshot.version, '3.0.0');
    assert.deepEqual(snapshot.capabilities.search, {
      availability: 'degraded',
      reason_code: 'local_embeddings_unavailable',
      service_version: '0.1.0',
      contract_version: '2.0.0',
      allowed_actions: ['advanced', 'temporal', 'faceted'],
      scope: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: 21,
    });
    assert.deepEqual(
      snapshot.capabilities['project-project-search'],
      snapshot.capabilities.search,
    );
    assert.deepEqual(snapshot.capabilities.automation_run, {
      availability: 'available',
      reason_code: null,
      service_version: '0.1.0',
      contract_version: '2.0.0',
      allowed_actions: ['run_now'],
      scope: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: null,
    });
    assert.deepEqual(snapshot.capabilities['project-project-cron-jobs'], {
      availability: 'available',
      reason_code: null,
      service_version: '0.1.0',
      contract_version: '2.0.0',
      allowed_actions: [
        'view',
        'list',
        'view-history',
        'inspect-capabilities',
        'create',
        'update',
        'toggle',
        'run-now',
        'delete',
      ],
      scope: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: null,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
