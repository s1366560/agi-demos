import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
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
import { projectEntitiesOperationsV2Fixture } from './projectEntitiesOperationsV2Fixture.mjs';
import { projectGraphOperationsV2Fixture } from './projectGraphOperationsV2Fixture.mjs';
import { projectBlackboardOperationsV2Fixture } from './projectBlackboardOperationsV2Fixture.mjs';
import { runtimePoolOperationsV2Fixture } from './runtimePoolOperationsV2Fixture.mjs';
import { runtimeClustersOperationsV2Fixture } from './runtimeClustersOperationsV2Fixture.mjs';
import { tenantAnalyticsOperationsV2Fixture } from './tenantAnalyticsOperationsV2Fixture.mjs';
import { tenantAgentBindingsOperationsV2Fixture } from './tenantAgentBindingsOperationsV2Fixture.mjs';
import { tenantProjectsOperationsV2Fixture } from './tenantProjectsOperationsV2Fixture.mjs';
import { tenantTasksOperationsV2Fixture } from './tenantTasksOperationsV2Fixture.mjs';
import { tenantAgentDashboardOperationsV2Fixture } from './tenantAgentDashboardOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const compiledNavigationDirectory = '/tmp/agistack-desktop-test-dist/src/features/navigation';
mkdirSync(compiledNavigationDirectory, { recursive: true });
writeFileSync(`${compiledNavigationDirectory}/NativeUnavailableRoute.css`, '');
require.extensions['.css'] = () => {};

const {
  DESKTOP_CAPABILITY_NAMES,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  PROJECT_BLACKBOARD_ROUTE_ID,
  PROJECT_WORKSPACES_ROUTE_ID,
  createDesktopProductionRouteRegistry,
  registerDesktopProductionRouteLoaders,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');
const {
  buildDesktopRoutePath,
  matchDesktopRoute,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js');
const {
  evaluateDesktopRouteAccess,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js');
const {
  buildProjectBlackboardCanonicalPath,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-blackboard/projectBlackboardRouteModule.js');

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const registrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);
const workbenchSource = readFileSync(
  new URL('../src/features/runtime/workbenchCapabilityClient.ts', import.meta.url),
  'utf8',
);
const providerSource = readFileSync(
  new URL(
    '../src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts',
    import.meta.url,
  ),
  'utf8',
);
const legacyProjectWorkspacesClientPath = new URL(
  '../src/features/project-workspaces/projectWorkspacesHttpClient.ts',
  import.meta.url,
);

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

test('production catalog structurally implements both project routes with project-member permission', async () => {
  assert.ok(DESKTOP_CAPABILITY_NAMES.includes('project-project-workspaces'));
  assert.ok(DESKTOP_CAPABILITY_NAMES.includes('project-blackboard-dynamic-project-blackboard'));
  assert.ok(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(PROJECT_WORKSPACES_ROUTE_ID));
  assert.ok(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(PROJECT_BLACKBOARD_ROUTE_ID));

  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [PROJECT_WORKSPACES_ROUTE_ID]: implementedLoader(PROJECT_WORKSPACES_ROUTE_ID),
      [PROJECT_BLACKBOARD_ROUTE_ID]: implementedLoader(PROJECT_BLACKBOARD_ROUTE_ID),
    }),
  });
  for (const routeId of [PROJECT_WORKSPACES_ROUTE_ID, PROJECT_BLACKBOARD_ROUTE_ID]) {
    const definition = registry.byId.get(routeId);
    assert.ok(definition);
    assert.deepEqual(definition.requiredPermission, [['authenticated', 'project_member']]);
    assert.deepEqual(definition.structuralReadiness, { status: 'ready' });
    assert.equal(
      evaluateDesktopRouteAccess({
        match: {
          definition,
          context: {
            tenantId: 'tenant-1',
            projectId: 'project-1',
            workspaceId: 'workspace-1',
          },
          canonicalPath: definition.path,
        },
        mode: 'cloud',
        permissions: new Set(['authenticated']),
        capability: observedCapability('cloud_service', {
          authority_revision: 1,
        }),
      }).status,
      'forbidden',
    );
    assert.equal(
      evaluateDesktopRouteAccess({
        match: {
          definition,
          context: {
            tenantId: 'tenant-1',
            projectId: 'project-1',
            workspaceId: 'workspace-1',
          },
          canonicalPath: definition.path,
        },
        mode: 'cloud',
        permissions: new Set(['authenticated', 'project_member']),
        capability: observedCapability('cloud_service', {
          authority_revision: 1,
        }),
      }).status,
      'allowed',
    );
  }
});

test('Workspaces to Blackboard navigation builds and restores the canonical scoped hash', () => {
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {},
  });
  const workspaces = registry.byId.get(PROJECT_WORKSPACES_ROUTE_ID);
  assert.ok(workspaces);
  assert.equal(
    buildDesktopRoutePath(workspaces, {
      tenantId: 'tenant / 1',
      projectId: 'project / 1',
    }),
    '/tenant/tenant%20%2F%201/project/project%20%2F%201/workspaces',
  );

  const path = buildProjectBlackboardCanonicalPath({
    tenantId: 'tenant / 1',
    projectId: 'project / 1',
    workspaceId: 'workspace / 1',
  });
  assert.equal(
    path,
    '/tenant/tenant%20%2F%201/project/project%20%2F%201/blackboard' +
      '?workspaceId=workspace%20%2F%201',
  );
  const matched = matchDesktopRoute(registry, `#${path}`);
  assert.ok(matched);
  assert.equal(matched.definition.id, PROJECT_BLACKBOARD_ROUTE_ID);
  assert.deepEqual(matched.context, {
    tenantId: 'tenant / 1',
    projectId: 'project / 1',
    workspaceId: 'workspace / 1',
  });
  assert.equal(matched.canonicalPath, path);
});

test('Snapshot v4 closes unversioned Workspaces and Blackboard observations', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ reason_code: 'unrelated_authority_unavailable' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    });
  try {
    for (const [mode, authoritySource] of [
      ['cloud', 'cloud_service'],
      ['local', 'sidecar'],
    ]) {
      const config = Object.freeze({
        ...cloudConfig,
        mode,
        localApiToken: mode === 'local' ? 'private-launch' : '',
      });
      const workspaceScope = Object.freeze({
        authority: mode,
        tenantId: config.tenantId,
        projectId: config.projectId,
      });
      const blackboardScope = Object.freeze({
        ...workspaceScope,
        workspaceId: config.workspaceId,
      });
      const client = createDesktopWorkbenchCapabilityClient(
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
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
    projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
          projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
          projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
          projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
          projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture({
            async probeProjectBlackboard({ scope }) {
              assert.deepEqual(scope, blackboardScope);
              return {
                scope,
                authority: mode,
                availability: mode === 'cloud' ? 'available' : 'degraded',
                reasonCode: mode === 'cloud' ? null : 'local_workspace_plan_read_only',
                initialSurface: mode === 'cloud' ? 'goals' : 'status',
                allowedActions:
                  mode === 'cloud'
                    ? ['view', 'read-surfaces', 'mutate-surfaces']
                    : ['view', 'review-plan'],
                authorityRevision: null,
              };
            },
          }),
          runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
          runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          projectWorkspacesClient: {
            async list(scope) {
              assert.deepEqual(scope, workspaceScope);
              return {
                scope,
                authority: mode,
                availability: mode === 'cloud' ? 'available' : 'degraded',
                reasonCode: mode === 'cloud' ? null : 'local_workspace_lifecycle_partial',
                serviceVersion: mode === 'cloud' ? 'cloud' : 'sidecar',
                contractVersion: '1.0.0',
                authorityRevision: null,
                allowedActions:
                  mode === 'cloud'
                    ? ['view', 'list', 'create', 'open-blackboard']
                    : ['view', 'list', 'open-blackboard'],
                workspaces: [],
              };
            },
          },
        },
      );
      const snapshot = await client.loadSnapshot();
      assert.deepEqual(
        snapshot.capabilities[PROJECT_WORKSPACES_ROUTE_ID],
        observedCapability(authoritySource, {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          allowed_actions: [],
          scope: capabilityScope(config, false),
        }),
      );
      assert.deepEqual(
        snapshot.capabilities[PROJECT_BLACKBOARD_ROUTE_ID],
        observedCapability(authoritySource, {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          allowed_actions: [],
          scope: capabilityScope(config, true),
        }),
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('authority failures and missing Blackboard workspace stay scoped and unavailable', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response('{}', { status: 503 });
  try {
    let blackboardProbeCount = 0;
    const config = Object.freeze({ ...cloudConfig, workspaceId: '' });
    const client = createDesktopWorkbenchCapabilityClient(
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
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
    projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
        projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
        projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
        projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
        projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture({
          async probeProjectBlackboard() {
            blackboardProbeCount += 1;
            throw new Error('must not probe without workspace scope');
          },
        }),
        runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
        runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
        tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

        tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
        tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
        projectWorkspacesClient: {
          async list() {
            throw new Error('workspace authority unavailable');
          },
        },
      },
    );
    const snapshot = await client.loadSnapshot();
    assert.deepEqual(
      snapshot.capabilities[PROJECT_WORKSPACES_ROUTE_ID],
      observedCapability('cloud_service', {
        availability: 'unavailable',
        reason_code: 'project_workspaces_authority_unavailable',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: capabilityScope(config, false),
      }),
    );
    assert.deepEqual(
      snapshot.capabilities[PROJECT_BLACKBOARD_ROUTE_ID],
      observedCapability('cloud_service', {
        availability: 'unavailable',
        reason_code: 'project_blackboard_scope_unavailable',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: capabilityScope(config, true),
      }),
    );
    assert.equal(blackboardProbeCount, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('App binds both typed route modules without browser handoff or DesktopApiClient expansion', () => {
  assert.match(
    registrySource,
    /\[PROJECT_WORKSPACES_ROUTE_ID\]:\s*createProjectWorkspacesRouteModuleLoader\(/,
  );
  assert.match(
    registrySource,
    /\[PROJECT_BLACKBOARD_ROUTE_ID\]:\s*createProjectBlackboardRouteModuleLoader\(/,
  );
  assert.match(registrySource, /createProjectWorkspacesV2Client\(/);
  assert.match(registrySource, /desktopWorkspaceCatalogOperationsV2/u);
  assert.match(registrySource, /desktopWorkspaceLifecycleOperationsV2/u);
  assert.doesNotMatch(registrySource, /createProjectWorkspacesHttpClient\(/u);
  assert.match(providerSource, /createProjectWorkspacesV2Client\(config,\s*\{/u);
  assert.match(workbenchSource, /projectWorkspacesClient:\s*Pick<ProjectWorkspacesClient/u);
  assert.doesNotMatch(workbenchSource, /projectWorkspacesClient\?\s*:/u);
  assert.doesNotMatch(workbenchSource, /createProjectWorkspacesHttpClient/u);
  assert.equal(existsSync(legacyProjectWorkspacesClientPath), false);
  assert.match(registrySource, /createProjectBlackboardV2Client\(/);
  assert.match(registrySource, /projectBlackboardOperationsV2/u);
  assert.doesNotMatch(registrySource, /createProjectBlackboard(?:Cloud|Local)Client\(/u);
  assert.match(registrySource, /buildProjectBlackboardCanonicalPath\(/);
  assert.doesNotMatch(
    registrySource,
    /PROJECT_(?:WORKSPACES|BLACKBOARD)_ROUTE_ID[^]{0,1200}(?:window\.open|openExternal|webview|iframe)/,
  );
});

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

function observedCapability(authoritySource, overrides = {}) {
  return {
    availability: 'available',
    reason_code: null,
    service_version: '0.1.0',
    contract_version: '4.0.0',
    allowed_actions: ['view'],
    scope: {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: 'workspace-1',
      instance_id: null,
    },
    authority_revision: null,
    retryable: false,
    authority_source: authoritySource,
    supporting_authority_sources: [],
    provenance: 'observed',
    ...overrides,
  };
}

function capabilityScope(config, workspace) {
  return {
    tenant_id: config.tenantId || null,
    project_id: config.projectId || null,
    workspace_id: workspace ? config.workspaceId || null : null,
    instance_id: null,
  };
}
