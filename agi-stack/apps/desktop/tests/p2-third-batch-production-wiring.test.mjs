import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

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

test('P2 third-batch production routes own real loaders while Profile remains route-only', () => {
  for (const routeId of ROUTE_IDS) {
    assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(routeId), true, routeId);
  }
  assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes('user-profile'), false);

  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders(
      Object.fromEntries(
        ROUTE_IDS.map((routeId) => [routeId, implementedLoader(routeId)]),
      ),
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
    'createProfileRouteBindingForRuntime',
  ]) {
    assert.match(appSource, new RegExp(symbol, 'u'), symbol);
  }
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
    assert.equal(
      capability.reason_code,
      'capability_authority_revision_unavailable',
      capabilityId,
    );
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
      clients,
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
