import { projectMcpServersOperationsV2Fixture } from './projectMcpServersOperationsV2Fixture.mjs';
import { tenantProvidersOperationsV2Fixture } from './tenantProvidersOperationsV2Fixture.mjs';
import { tenantSkillDefinitionsOperationsV2Fixture } from './tenantSkillOperationsV2Fixture.mjs';
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
  DESKTOP_CAPABILITY_NAMES,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  createDesktopProductionRouteRegistry,
  registerDesktopProductionRouteLoaders,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');
const {
  NativeRouteClientError,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings-routes/nativeRouteHttpClient.js');

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const registrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);
const settingsSource = readFileSync(
  new URL('../src/features/settings/SettingsWindow.tsx', import.meta.url),
  'utf8',
);
const profileAuxiliarySource = readFileSync(
  new URL('../src/features/settings-routes/profileAuxiliaryRoute.ts', import.meta.url),
  'utf8',
);
const evolutionClientSource = readFileSync(
  new URL('../src/features/settings-routes/evolutionRouteClient.ts', import.meta.url),
  'utf8',
);
const p2RuntimeSource = readFileSync(
  new URL('../src/features/settings-routes/p2ThirdBatchRouteRuntime.ts', import.meta.url),
  'utf8',
);
const workbenchSource = readFileSync(
  new URL('../src/features/runtime/workbenchCapabilityClient.ts', import.meta.url),
  'utf8',
);

const ROUTE_IDS = Object.freeze([
  'tenant-tenant-evolution',
  'project-project-channels',
  'tenant-tenant-templates',
]);
const CAPABILITY_IDS = Object.freeze([...ROUTE_IDS, 'user-profile']);

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

test('P2 third-batch and Profile loaders are owned by the V2 route registry', () => {
  for (const routeId of ROUTE_IDS) {
    assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(routeId), true, routeId);
  }
  assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes('user-profile'), false);

  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders(
      Object.fromEntries(ROUTE_IDS.map((routeId) => [routeId, implementedLoader(routeId)])),
    ),
  });
  for (const routeId of ROUTE_IDS) {
    assert.deepEqual(registry.byId.get(routeId)?.structuralReadiness, {
      status: 'ready',
    });
  }

  for (const symbol of [
    'createEvolutionRouteModuleLoader',
    'createChannelsRouteModuleLoader',
    'createTemplatesRouteModuleLoader',
    'createEvolutionRouteBindingForRuntime',
    'createChannelsRouteBindingForRuntime',
    'createTemplatesRouteBindingForRuntime',
    'createProfileRouteModuleLoader',
    'createProfileRouteBindingForRuntime',
  ]) {
    assert.match(registrySource, new RegExp(symbol, 'u'), symbol);
    assert.doesNotMatch(appSource, new RegExp(symbol, 'u'), symbol);
  }
  assert.match(settingsSource, /rendererRouteRegistry/u);
  assert.match(settingsSource, /byId\.get\(PROFILE_ROUTE_ID\)\?\.loader/u);
  assert.match(profileAuxiliarySource, /createProfileGenerationHashLocationPort/u);
  assert.doesNotMatch(appSource, /matchProfileAuxiliaryRoute|profileAuxiliaryRouteActiveRef/u);
  assert.doesNotMatch(evolutionClientSource, /createEvolutionRouteClient|requestNativeRouteJson/u);
  assert.match(p2RuntimeSource, /createDesktopTenantEvolutionClientV2/u);
  assert.match(p2RuntimeSource, /createDesktopProjectChannelsClientV2/u);
  assert.match(registrySource, /tenantEvolutionOperationsV2/u);
  assert.match(registrySource, /projectChannelsOperationsV2/u);
  assert.match(workbenchSource, /tenantEvolutionOperationsV2/u);
  assert.match(workbenchSource, /projectChannelsOperationsV2/u);
  assert.doesNotMatch(workbenchSource, /evolutionRouteClient\?/u);
  assert.doesNotMatch(workbenchSource, /channelsRouteClient\?/u);
  assert.match(appSource, /createDesktopTenantEvolutionOperationsV2/u);
  assert.match(appSource, /createDesktopProjectChannelsOperationsV2/u);
  assert.doesNotMatch(
    appSource,
    /(?:evolution|channels|templates|profile)[\s\S]{0,500}(?:WebView|<webview|<iframe|openExternal|window\.open)/iu,
  );
});

test('Cloud Snapshot v4 closes unversioned third-batch observations', async () => {
  const snapshot = await loadSnapshot(cloudConfig, {
    evolutionRouteClient: observedProbe({
      authority: 'cloud',
      tenantId: 'tenant-1',
      allowedActions: ['view', 'configure', 'run', 'apply-job', 'reject-job'],
    }),
    channelsRouteClient: observedProbe({
      authority: 'cloud',
      tenantId: 'tenant-1',
      projectId: 'project-1',
      allowedActions: ['view', 'list-channel-configs'],
    }),
    templatesRouteClient: observedProbe({
      authority: 'cloud',
      tenantId: 'tenant-1',
      allowedActions: ['view', 'list', 'install'],
    }),
    profileRouteClient: observedProbe({
      authority: 'cloud',
      allowedActions: ['view', 'update', 'change-language', 'change-password'],
    }),
  });

  for (const capabilityId of CAPABILITY_IDS) {
    const capability = snapshot.capabilities[capabilityId];
    assert.equal(capability.provenance, 'observed', capabilityId);
    assert.equal(capability.authority_source, 'cloud_service', capabilityId);
    assert.equal(capability.availability, 'unavailable', capabilityId);
    assert.equal(capability.reason_code, 'capability_authority_revision_unavailable', capabilityId);
    assert.equal(capability.contract_version, '4.0.0', capabilityId);
  }
});

test('Local Snapshot observes stable sidecar dispositions without promoting declared state', async () => {
  const localConfig = {
    ...cloudConfig,
    apiBaseUrl: 'http://127.0.0.1:43117',
    apiKey: 'local-session',
    localApiToken: 'private-launch',
    mode: 'local',
  };
  const snapshot = await loadSnapshot(localConfig, {
    evolutionRouteClient: rejectedProbe('local_skill_evolution_authority_unavailable'),
    channelsRouteClient: rejectedProbe('local_channel_runtime_not_applicable'),
    templatesRouteClient: rejectedProbe('local_subagent_registry_unavailable'),
    profileRouteClient: observedProbe({
      authority: 'local',
      availability: 'degraded',
      reasonCode: 'local_profile_mutation_authority_unavailable',
      allowedActions: ['view'],
    }),
  });

  assert.deepEqual(pick(snapshot, 'tenant-tenant-evolution'), {
    availability: 'unavailable',
    reason_code: 'local_skill_evolution_authority_unavailable',
    allowed_actions: [],
  });
  assert.deepEqual(pick(snapshot, 'project-project-channels'), {
    availability: 'not_applicable',
    reason_code: 'local_channel_runtime_not_applicable',
    allowed_actions: [],
  });
  assert.deepEqual(pick(snapshot, 'tenant-tenant-templates'), {
    availability: 'unavailable',
    reason_code: 'local_subagent_registry_unavailable',
    allowed_actions: [],
  });
  assert.deepEqual(pick(snapshot, 'user-profile'), {
    availability: 'unavailable',
    reason_code: 'capability_authority_revision_unavailable',
    allowed_actions: [],
  });
  for (const capabilityId of CAPABILITY_IDS) {
    assert.equal(snapshot.capabilities[capabilityId].provenance, 'observed');
    assert.equal(snapshot.capabilities[capabilityId].authority_source, 'sidecar');
  }
});

test('Capability catalog contains four P2 third-batch IDs exactly once', () => {
  for (const capabilityId of CAPABILITY_IDS) {
    assert.equal(DESKTOP_CAPABILITY_NAMES.includes(capabilityId), true, capabilityId);
  }
});

async function loadSnapshot(config, clients) {
  const {
    evolutionRouteClient,
    channelsRouteClient,
    templatesRouteClient,
    profileRouteClient,
    ...remainingClients
  } = clients;
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
          throw new Error('unavailable');
        },
      },
      config,
      {
        ...remainingClients,
        tenantEvolutionOperationsV2: {
          observeTenantEvolution: ({ scope, signal }) =>
            evolutionRouteClient.observe(scope, signal),
        },
        projectChannelsOperationsV2: {
          loadProjectChannels: ({ scope, signal }) =>
            channelsRouteClient.observe(scope, signal),
        },
        tenantTemplatesOperationsV2: {
          loadTenantTemplates: ({ scope, signal }) =>
            templatesRouteClient.observe(scope, {}, signal),
        },
        userProfileOperationsV2: {
          observeUserProfile: ({ scope, signal }) =>
            profileRouteClient.observe(scope, signal),
        },
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        tenantProvidersOperationsV2: tenantProvidersOperationsV2Fixture(),
        projectMcpServersOperationsV2: projectMcpServersOperationsV2Fixture(),
        tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2Fixture(),
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

function observedProbe({
  authority,
  tenantId,
  projectId,
  availability = 'available',
  reasonCode = null,
  allowedActions,
}) {
  return {
    async observe(scope) {
      assert.equal(scope.authority, authority);
      if (tenantId !== undefined) assert.equal(scope.tenantId, tenantId);
      if (projectId !== undefined) assert.equal(scope.projectId, projectId);
      return {
        scope,
        authority,
        availability,
        reasonCode,
        allowedActions,
        itemCount: 0,
        user: profileUser(),
      };
    },
  };
}

function rejectedProbe(reasonCode) {
  return {
    async observe() {
      throw new NativeRouteClientError(reasonCode, 501, { reason_code: reasonCode });
    },
  };
}

function profileUser() {
  return {
    user_id: 'user-1',
    email: 'user@example.test',
    name: 'User',
    roles: ['member'],
    global_roles: [],
    is_active: true,
    is_superuser: false,
    created_at: '2026-08-05T00:00:00Z',
    profile: {},
    preferred_language: 'en-US',
  };
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

function pick(snapshot, capabilityId) {
  const capability = snapshot.capabilities[capabilityId];
  return {
    availability: capability.availability,
    reason_code: capability.reason_code,
    allowed_actions: [...capability.allowed_actions],
  };
}
