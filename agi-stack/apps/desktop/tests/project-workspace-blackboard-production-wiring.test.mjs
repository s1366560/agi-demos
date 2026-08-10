import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

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
          projectBlackboardClient: {
            async probe(scope) {
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
                collaborationClient: inertCollaborationClient,
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
        projectWorkspacesClient: {
          async list() {
            throw new Error('workspace authority unavailable');
          },
        },
        projectBlackboardClient: {
          async probe() {
            blackboardProbeCount += 1;
            throw new Error('must not probe without workspace scope');
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
  assert.match(registrySource, /createProjectWorkspacesHttpClient\(/);
  assert.match(registrySource, /createProjectBlackboardCloudClient\(/);
  assert.match(registrySource, /createProjectBlackboardLocalClient\(/);
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

const inertCollaborationClient = Object.freeze({
  async getSurface() {
    throw new Error('unused');
  },
  async refetchAuthority() {
    throw new Error('unused');
  },
  async mutateSurface() {
    throw new Error('unused');
  },
});
