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
import { tenantAgentDefinitionsOperationsV2Fixture } from './tenantAgentDefinitionsOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  createDesktopProductionRouteRegistry,
  registerDesktopProductionRouteLoaders,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const registrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);
const routeIds = Object.freeze([
  'project-project-schema',
  'project-project-maintenance',
  'project-project-settings',
]);
const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
});

test('Project Administration production routes own native loaders and App bindings', async () => {
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders(
      Object.fromEntries(routeIds.map((routeId) => [routeId, implementedLoader(routeId)])),
    ),
  });
  for (const routeId of routeIds) {
    assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(routeId), true, routeId);
    assert.deepEqual(registry.byId.get(routeId)?.structuralReadiness, { status: 'ready' });
    assert.equal((await registry.byId.get(routeId).loader()).localPolicy, 'native_equivalent');
  }
  for (const symbol of [
    'createProjectSchemaRouteModuleLoader',
    'createProjectMaintenanceRouteModuleLoader',
    'createProjectSettingsRouteModuleLoader',
    'createProjectSchemaController',
    'createProjectMaintenanceController',
    'createProjectSettingsController',
  ]) {
    assert.match(registrySource, new RegExp(symbol, 'u'), symbol);
    assert.doesNotMatch(appSource, new RegExp(symbol, 'u'), symbol);
  }
  assert.match(
    registrySource,
    /createDesktopProjectSchemaClientV2\(\s*projectSchemaOperationsV2,\s*currentConfig,?\s*\)/u,
  );
  assert.match(appSource, /projectSchemaOperationsV2:\s*desktopProjectSchemaOperationsV2/gu);
  assert.match(
    registrySource,
    /createDesktopProjectMaintenanceClientV2\(\s*projectMaintenanceOperationsV2,\s*currentConfig,?\s*\)/u,
  );
  assert.match(
    appSource,
    /projectMaintenanceOperationsV2:\s*desktopProjectMaintenanceOperationsV2/gu,
  );
  assert.doesNotMatch(registrySource, /createProjectSchemaClient/u);
  assert.doesNotMatch(registrySource, /createProjectMaintenanceClient/u);
});

test('Project Administration Snapshot observes Cloud and declares Local authority', async () => {
  const cloud = await loadSnapshot(cloudConfig, clients('cloud'));
  for (const routeId of routeIds) {
    const capability = cloud.capabilities[routeId];
    assert.equal(capability.provenance, 'observed', routeId);
    assert.equal(capability.authority_source, 'cloud_service', routeId);
  }
  assert.deepEqual(cloud.capabilities['project-project-schema'], {
    availability: 'degraded',
    reason_code: 'desktop_project_schema_actions_and_export_unwired',
    service_version: '0.1.0',
    contract_version: '4.0.0',
    allowed_actions: ['view', 'list-entity-types'],
    provenance: 'observed',
    authority_source: 'cloud_service',
    authority_revision: 67,
    retryable: false,
    supporting_authority_sources: [],
    scope: {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
    },
  });
  assert.deepEqual(cloud.capabilities['project-project-maintenance'], {
    availability: 'degraded',
    reason_code: 'desktop_project_maintenance_surface_and_endpoints_incomplete',
    service_version: '0.1.0',
    contract_version: '4.0.0',
    allowed_actions: ['view'],
    provenance: 'observed',
    authority_source: 'cloud_service',
    authority_revision: 68,
    retryable: false,
    supporting_authority_sources: [],
    scope: {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
    },
  });
  assert.deepEqual(cloud.capabilities['project-project-settings'], {
    availability: 'degraded',
    reason_code: 'desktop_project_settings_actions_unwired',
    service_version: '0.1.0',
    contract_version: '4.0.0',
    allowed_actions: ['view'],
    provenance: 'observed',
    authority_source: 'cloud_service',
    authority_revision: 68,
    retryable: false,
    supporting_authority_sources: [],
    scope: {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
    },
  });

  let calls = 0;
  const localClients = Object.fromEntries(
    routeIds.map((routeId) => [
      routeId,
      {
        async load() {
          calls += 1;
          throw new Error(routeId);
        },
      },
    ]),
  );
  const local = await loadSnapshot(
    { ...cloudConfig, mode: 'local', localApiToken: 'private-launch' },
    localClients,
  );
  assert.equal(calls, 0);
  for (const routeId of routeIds) {
    const capability = local.capabilities[routeId];
    assert.equal(capability.provenance, 'declared', routeId);
    assert.equal(capability.authority_source, 'renderer', routeId);
    assert.equal(capability.availability, 'unavailable', routeId);
  }
});

async function loadSnapshot(config, projectAdministrationClients) {
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
        projectAdministrationClients,
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2Fixture(),
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
    ).loadSnapshot();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function clients(authority) {
  return Object.fromEntries(
    routeIds.map((routeId) => [
      routeId,
      {
        async load(scope) {
          assert.deepEqual(scope, {
            authority,
            tenantId: 'tenant-1',
            projectId: 'project-1',
          });
          return {
            scope,
            scopeRevision: 31,
            authority,
            availability: 'available',
            reasonCode: null,
            contractVersion: '4.0.0',
            allowedActions: ['view'],
          };
        },
      },
    ]),
  );
}

function implementedLoader(routeId) {
  return async () => ({
    routeId,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: routeId,
    localPolicy: 'native_equivalent',
    Surface: () => null,
  });
}
