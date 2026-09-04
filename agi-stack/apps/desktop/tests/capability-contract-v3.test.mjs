import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { projectOverviewOperationsV2Fixture } from './projectOverviewOperationsV2Fixture.mjs';
import { projectAgentDashboardOperationsV2Fixture } from './projectAgentDashboardOperationsV2Fixture.mjs';
import { projectAgentLogsOperationsV2Fixture } from './projectAgentLogsOperationsV2Fixture.mjs';
import { projectAgentPatternsOperationsV2Fixture } from './projectAgentPatternsOperationsV2Fixture.mjs';
import { projectCommunitiesOperationsV2Fixture } from './projectCommunitiesOperationsV2Fixture.mjs';
import { projectMemoriesOperationsV2Fixture } from './projectMemoriesOperationsV2Fixture.mjs';
import { projectTeamOperationsV2Fixture } from './projectTeamOperationsV2Fixture.mjs';
import { projectSchemaOperationsV2Fixture } from './projectSchemaOperationsV2Fixture.mjs';
import { projectMaintenanceOperationsV2Fixture } from './projectMaintenanceOperationsV2Fixture.mjs';
import { projectSettingsOperationsV2Fixture } from './projectSettingsOperationsV2Fixture.mjs';
import { projectEntitiesOperationsV2Fixture } from './projectEntitiesOperationsV2Fixture.mjs';
import { projectGraphOperationsV2Fixture } from './projectGraphOperationsV2Fixture.mjs';
import { projectBlackboardOperationsV2Fixture } from './projectBlackboardOperationsV2Fixture.mjs';
import { projectWorkspacesClientV2Fixture } from './projectWorkspacesClientV2Fixture.mjs';
import { runtimePoolOperationsV2Fixture } from './runtimePoolOperationsV2Fixture.mjs';
import { runtimeClustersOperationsV2Fixture } from './runtimeClustersOperationsV2Fixture.mjs';
import { runtimeInstancesOperationsV2Fixture } from './runtimeInstancesOperationsV2Fixture.mjs';
import { runtimeDeploymentsOperationsV2Fixture } from './runtimeDeploymentsOperationsV2Fixture.mjs';
import { tenantAnalyticsOperationsV2Fixture } from './tenantAnalyticsOperationsV2Fixture.mjs';
import { tenantAgentBindingsOperationsV2Fixture } from './tenantAgentBindingsOperationsV2Fixture.mjs';
import { tenantProjectsOperationsV2Fixture } from './tenantProjectsOperationsV2Fixture.mjs';
import { tenantTasksOperationsV2Fixture } from './tenantTasksOperationsV2Fixture.mjs';
import { tenantAgentDashboardOperationsV2Fixture } from './tenantAgentDashboardOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const {
  DESKTOP_CAPABILITY_NAMES,
  desktopCapability,
  parseDesktopCapabilitySnapshot,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const fixture = JSON.parse(
  readFileSync(new URL('./fixtures/desktop-capability-snapshot.v3.json', import.meta.url), 'utf8'),
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

function declaredEntry(capability) {
  return {
    ...capability,
    retryable: false,
    authority_source: 'renderer',
    supporting_authority_sources: [],
    provenance: 'declared',
  };
}

function declaredSnapshot(snapshot) {
  const { mode, ...legacySnapshot } = snapshot;
  return {
    ...legacySnapshot,
    version: '5.0.0',
    runtime_state: mode === 'local' ? 'local_offline' : mode,
    capabilities: Object.fromEntries(
      DESKTOP_CAPABILITY_NAMES.map((name) => [
        name,
        declaredEntry(
          snapshot.capabilities[name] ?? {
            availability: 'unavailable',
            reason_code: 'capability_not_declared',
            service_version: null,
            contract_version: null,
            allowed_actions: [],
            scope: nullScope,
            authority_revision: null,
          },
        ),
      ]),
    ),
  };
}

test('DesktopCapabilitySnapshot v3 validates authority fields and preserves the App view', () => {
  const snapshot = parseDesktopCapabilitySnapshot(fixture);
  assert.deepEqual(
    snapshot,
    declaredSnapshot({
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
        'tenant-creation': {
          availability: 'unavailable',
          reason_code: 'capability_not_declared',
          service_version: null,
          contract_version: null,
          allowed_actions: [],
          scope: nullScope,
          authority_revision: null,
        },
        'invitation-acceptance': {
          availability: 'unavailable',
          reason_code: 'capability_not_declared',
          service_version: null,
          contract_version: null,
          allowed_actions: [],
          scope: nullScope,
          authority_revision: null,
        },
        'agent-workspace-tenant-agent-workspace': {
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
        'tenant-tenant-workspaces': {
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
        'tenant-tenant-analytics': {
          availability: 'unavailable',
          reason_code: 'capability_not_declared',
          service_version: null,
          contract_version: null,
          allowed_actions: [],
          scope: nullScope,
          authority_revision: null,
        },
        'tenant-tenant-agent-configuration': {
          availability: 'unavailable',
          reason_code: 'capability_not_declared',
          service_version: null,
          contract_version: null,
          allowed_actions: [],
          scope: nullScope,
          authority_revision: null,
        },
        'tenant-tenant-agent-bindings': {
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
        'project-support': {
          availability: 'unavailable',
          reason_code: 'capability_not_declared',
          service_version: null,
          contract_version: null,
          allowed_actions: [],
          scope: nullScope,
          authority_revision: null,
        },
      },
    }),
  );
  assert.deepEqual(
    desktopCapability(snapshot, 'search'),
    declaredEntry({
      ...fixture.capabilities.search,
      status: 'degraded',
      available: false,
    }),
  );
  assert.deepEqual(
    desktopCapability(snapshot, 'sandbox_isolation'),
    declaredEntry({
      ...fixture.capabilities.sandbox_isolation,
      status: 'not_applicable',
      available: false,
    }),
  );
});

test('DesktopCapabilitySnapshot v2 is read-only input and normalizes missing capabilities closed', () => {
  const snapshot = parseDesktopCapabilitySnapshot(legacyFixture);
  assert.equal(snapshot?.version, '5.0.0');
  assert.deepEqual(
    snapshot?.capabilities.search,
    declaredEntry({
      availability: 'degraded',
      reason_code: 'local_search_keyword_only',
      service_version: '0.1.0',
      contract_version: '2.0.0',
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
    }),
  );

  const missingCapability = structuredClone(legacyFixture);
  delete missingCapability.capabilities.search;
  assert.deepEqual(
    parseDesktopCapabilitySnapshot(missingCapability)?.capabilities.search,
    declaredEntry({
      availability: 'unavailable',
      reason_code: 'capability_not_declared',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
    }),
  );
});

test('DesktopCapabilitySnapshot v3 rejects unsafe authority state and unsupported versions', () => {
  const duplicateAction = structuredClone(fixture);
  duplicateAction.capabilities.search.allowed_actions.push('advanced');
  assert.equal(parseDesktopCapabilitySnapshot(duplicateAction), null);

  const actionOnUnavailable = structuredClone(fixture);
  actionOnUnavailable.capabilities.workspace_collaboration.allowed_actions.push('update');
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
      {
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
        projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
        projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
        projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
        projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
        projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
        projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
        projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
        projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
        projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
        projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
        projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
        runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
        runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
        runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
        runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
        instanceTemplatesOperationsV2: {
          async probe({ config }) {
            return config.mode === 'local'
              ? {
                  availability: 'not_applicable',
                  reasonCode: 'local_instance_template_authority_unavailable',
                  allowedActions: [],
                  authorityRevision: null,
                }
              : {
                  availability: 'available',
                  reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
                  allowedActions: ['view', 'list', 'create', 'delete', 'publish', 'clone'],
                  authorityRevision: null,
                };
          },
        },
        deadLetterQueueOperationsV2: {
          async probe({ config }) {
            return config.mode === 'local'
              ? {
                  availability: 'not_applicable',
                  reasonCode: 'cloud_message_bus_dlq_not_applicable',
                  allowedActions: [],
                  authorityRevision: null,
                }
              : {
                  availability: 'available',
                  reasonCode: null,
                  allowedActions: ['view', 'list'],
                  authorityRevision: null,
                };
          },
        },
        backendStoresOperationsV2: {
          async probeBackendStores({ config }) {
            return config.mode === 'local'
              ? {
                  availability: 'not_applicable',
                  reasonCode: 'local_backend_stores_cloud_authority_unavailable',
                  allowedActions: [],
                  authorityRevision: null,
                }
              : {
                  availability: 'available',
                  reasonCode: null,
                  allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
                  authorityRevision: 23,
                };
          },
        },
        projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
        tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

        tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
        tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
      },
    );

    const snapshot = await client.loadSnapshot();
    assert.equal(snapshot.version, '5.0.0');
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
      retryable: false,
      authority_source: 'sidecar',
      supporting_authority_sources: [],
      provenance: 'observed',
    });
    assert.deepEqual(snapshot.capabilities['project-project-search'], snapshot.capabilities.search);
    assert.deepEqual(snapshot.capabilities.automation_run, {
      availability: 'unavailable',
      reason_code: 'capability_authority_revision_unavailable',
      service_version: '0.1.0',
      contract_version: '2.0.0',
      allowed_actions: [],
      scope: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: null,
      retryable: false,
      authority_source: 'sidecar',
      supporting_authority_sources: [],
      provenance: 'observed',
    });
    assert.deepEqual(snapshot.capabilities['project-project-cron-jobs'], {
      availability: 'unavailable',
      reason_code: 'capability_authority_revision_unavailable',
      service_version: '0.1.0',
      contract_version: '2.0.0',
      allowed_actions: [],
      scope: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: null,
      retryable: false,
      authority_source: 'sidecar',
      supporting_authority_sources: [],
      provenance: 'observed',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
