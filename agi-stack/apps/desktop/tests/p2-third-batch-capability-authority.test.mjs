import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src/features/settings-routes';
const {
  P2_THIRD_BATCH_CAPABILITY_IDS,
  createP2ThirdBatchCapabilityClient,
} = require(`${root}/p2ThirdBatchCapabilityClient.js`);
const { NativeRouteClientError } = require(`${root}/nativeRouteHttpClient.js`);
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');

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

test('P2 third-batch capability client publishes only observed Cloud actions', async () => {
  const client = createP2ThirdBatchCapabilityClient(cloudConfig, {
    evolution: probe({
      scope: { authority: 'cloud', tenantId: 'tenant-1' },
      allowedActions: ['view', 'configure', 'run'],
    }),
    channels: probe({
      scope: {
        authority: 'cloud',
        tenantId: 'tenant-1',
        projectId: 'project-1',
      },
      allowedActions: ['view', 'list-channel-configs', 'create-channel-config'],
    }),
    templates: probe({
      scope: { authority: 'cloud', tenantId: 'tenant-1' },
      allowedActions: ['view', 'list', 'view-detail', 'install'],
    }),
    profile: probe({
      scope: { authority: 'cloud' },
      allowedActions: ['view', 'update', 'change-language', 'change-password'],
    }),
  });

  const result = await client.load();
  assert.deepEqual(P2_THIRD_BATCH_CAPABILITY_IDS, [
    'tenant-tenant-evolution',
    'project-project-channels',
    'tenant-tenant-templates',
    'user-profile',
  ]);
  for (const id of P2_THIRD_BATCH_CAPABILITY_IDS) {
    assert.equal(result[id].provenance, 'observed', id);
    assert.equal(result[id].capability.availability, 'available', id);
    assert.equal(result[id].capability.contract_version, '4.0.0', id);
  }
  assert.deepEqual(result['tenant-tenant-evolution'].capability.allowed_actions, [
    'view',
    'configure',
    'run',
  ]);
  assert.deepEqual(result['project-project-channels'].capability.scope, {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: null,
    instance_id: null,
  });
});

test('P2 third-batch Local policy distinguishes N/A, observed unavailable, and read-only profile', async () => {
  let channelCalls = 0;
  const localConfig = {
    ...cloudConfig,
    mode: 'local',
    apiBaseUrl: 'http://127.0.0.1:43117',
    localApiToken: 'private-launch',
  };
  const client = createP2ThirdBatchCapabilityClient(localConfig, {
    evolution: rejecting('local_skill_evolution_authority_unavailable'),
    channels: {
      async observe() {
        channelCalls += 1;
        throw new NativeRouteClientError(
          'local_channel_runtime_not_applicable',
          501,
        );
      },
    },
    templates: rejecting('local_subagent_registry_unavailable'),
    profile: probe({
      scope: { authority: 'local' },
      availability: 'degraded',
      reasonCode: 'local_profile_mutation_authority_unavailable',
      allowedActions: ['view'],
    }),
  });

  const result = await client.load();
  assert.deepEqual(pick(result['project-project-channels']), {
    provenance: 'observed',
    availability: 'not_applicable',
    reasonCode: 'local_channel_runtime_not_applicable',
    actions: [],
  });
  assert.deepEqual(pick(result['tenant-tenant-evolution']), {
    provenance: 'observed',
    availability: 'unavailable',
    reasonCode: 'local_skill_evolution_authority_unavailable',
    actions: [],
  });
  assert.deepEqual(pick(result['tenant-tenant-templates']), {
    provenance: 'observed',
    availability: 'unavailable',
    reasonCode: 'local_subagent_registry_unavailable',
    actions: [],
  });
  assert.deepEqual(pick(result['user-profile']), {
    provenance: 'observed',
    availability: 'degraded',
    reasonCode: 'local_profile_mutation_authority_unavailable',
    actions: ['view'],
  });
  assert.equal(channelCalls, 1);
});

test('P2 third-batch malformed observation fails only that capability closed', async () => {
  const client = createP2ThirdBatchCapabilityClient(cloudConfig, {
    evolution: probe({
      scope: { authority: 'local', tenantId: 'tenant-1' },
      allowedActions: ['view'],
    }),
    channels: probe({
      scope: {
        authority: 'cloud',
        tenantId: 'tenant-1',
        projectId: 'project-1',
      },
      allowedActions: ['view'],
    }),
    templates: probe({
      scope: { authority: 'cloud', tenantId: 'tenant-1' },
      allowedActions: ['view'],
    }),
    profile: probe({
      scope: { authority: 'cloud' },
      allowedActions: ['view'],
    }),
  });

  const result = await client.load();
  assert.deepEqual(pick(result['tenant-tenant-evolution']), {
    provenance: 'observed',
    availability: 'unavailable',
    reasonCode: 'skill_evolution_authority_contract_invalid',
    actions: [],
  });
  assert.equal(result['project-project-channels'].capability.availability, 'available');
  assert.equal(result['tenant-tenant-templates'].capability.availability, 'available');
  assert.equal(result['user-profile'].capability.availability, 'available');
});

test('workbench Snapshot v4 keeps unversioned P2 observations unavailable', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ reason_code: 'unrelated_authority_unavailable' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    });
  try {
    const client = createDesktopWorkbenchCapabilityClient(
      unavailableAutomation,
      cloudConfig,
      {
        p2ThirdBatchCapabilityClient: {
          async load() {
            return projectionSet();
          },
        },
      },
    );
    const snapshot = await client.loadSnapshot();
    for (const id of P2_THIRD_BATCH_CAPABILITY_IDS) {
      assert.equal(snapshot.capabilities[id].provenance, 'observed', id);
      assert.equal(snapshot.capabilities[id].authority_source, 'cloud_service', id);
      assert.equal(snapshot.capabilities[id].availability, 'unavailable', id);
      assert.equal(
        snapshot.capabilities[id].reason_code,
        'capability_authority_revision_unavailable',
        id,
      );
      assert.deepEqual(snapshot.capabilities[id].allowed_actions, [], id);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

function probe({
  scope,
  availability = 'available',
  reasonCode = null,
  allowedActions,
}) {
  return {
    async observe() {
      return {
        scope,
        authority: scope.authority,
        availability,
        reasonCode,
        allowedActions,
        itemCount: 1,
      };
    },
  };
}

function rejecting(reasonCode) {
  return {
    async observe() {
      throw new NativeRouteClientError(reasonCode, 501, { reason_code: reasonCode });
    },
  };
}

function pick(projection) {
  return {
    provenance: projection.provenance,
    availability: projection.capability.availability,
    reasonCode: projection.capability.reason_code,
    actions: [...projection.capability.allowed_actions],
  };
}

function projectionSet() {
  return Object.fromEntries(
    P2_THIRD_BATCH_CAPABILITY_IDS.map((id) => [
      id,
      {
        provenance: 'observed',
        capability: {
          availability: 'available',
          reason_code: null,
          service_version: '0.1.0',
          contract_version: '4.0.0',
          allowed_actions: ['view'],
          scope: {
            tenant_id: id === 'user-profile' ? null : 'tenant-1',
            project_id: id === 'project-project-channels' ? 'project-1' : null,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        },
      },
    ]),
  );
}

const unavailableAutomation = Object.freeze({
  async getAutomationCapabilities() {
    throw new Error('unrelated authority unavailable');
  },
});
