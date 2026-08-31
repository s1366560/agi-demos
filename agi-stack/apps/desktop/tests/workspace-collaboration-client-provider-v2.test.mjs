import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createWorkspaceCollaborationClientProviderV2,
  WorkspaceCollaborationClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'workspaceCollaborationClientProviderV2.js',
);

test('workspace collaboration client provider fails closed before publication', () => {
  const provider = createWorkspaceCollaborationClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof WorkspaceCollaborationClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'workspace_collaboration_client_unpublished');
      assert.equal(error.message, 'workspace_collaboration_client_unpublished');
      return true;
    },
  );
});

test('each publication returns one frozen generation-pinned client binding', async () => {
  const provider = createWorkspaceCollaborationClientProviderV2();
  const cloudConfig = runtimeConfig('cloud');
  const cloud = provider.publish({
    config: cloudConfig,
    capabilitySnapshot: unavailableSnapshot('cloud', 'cloud_capability_unavailable'),
  });
  cloudConfig.mode = 'local';

  const local = provider.publish({
    config: runtimeConfig('local'),
    capabilitySnapshot: unavailableSnapshot(
      'local_offline',
      'local_workspace_collaboration_unavailable',
    ),
  });

  assert.equal(Object.isFrozen(cloud), true);
  assert.equal(Object.isFrozen(local), true);
  assert.notEqual(cloud, local);
  assert.equal(provider.resolve(), local);
  assert.deepEqual(await cloud.client.getSurface('workspace-1', 'goals'), {
    workspace_id: 'workspace-1',
    surface: 'goals',
    authority: 'cloud',
    status: 'unavailable',
    revision: null,
    cursor: null,
    data: null,
    reason_code: 'cloud_capability_unavailable',
  });
  assert.deepEqual(await local.client.getSurface('workspace-1', 'goals'), {
    workspace_id: 'workspace-1',
    surface: 'goals',
    authority: 'local',
    status: 'unavailable',
    revision: null,
    cursor: null,
    data: null,
    reason_code: 'local_workspace_collaboration_unavailable',
  });
});

test('failed publication keeps the last-good client binding', () => {
  const provider = createWorkspaceCollaborationClientProviderV2();
  const lastGood = provider.publish({
    config: runtimeConfig('cloud'),
    capabilitySnapshot: unavailableSnapshot('cloud', 'last_good'),
  });
  const poisonedSnapshot = {
    version: '5.0.0',
    runtime_state: 'cloud',
    get capabilities() {
      throw new Error('candidate_capability_snapshot_invalid');
    },
  };

  assert.throws(
    () =>
      provider.publish({
        config: runtimeConfig('cloud'),
        capabilitySnapshot: poisonedSnapshot,
      }),
    /candidate_capability_snapshot_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(mode) {
  return {
    apiBaseUrl: mode === 'cloud' ? 'https://api.example.test' : 'http://127.0.0.1:1',
    deviceAuthorizationBaseUrl: 'https://auth.example.test',
    apiKey: '',
    localApiToken: mode === 'local' ? 'redacted-local-credential' : '',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    mode,
    workspaceRoot: '/workspace',
  };
}

function unavailableSnapshot(runtimeState, reasonCode) {
  return Object.freeze({
    version: '5.0.0',
    runtime_state: runtimeState,
    capabilities: Object.freeze({
      workspace_collaboration: Object.freeze({
        availability: 'unavailable',
        reason_code: reasonCode,
        service_version: null,
        contract_version: null,
        allowed_actions: Object.freeze([]),
        scope: Object.freeze({
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          workspace_id: 'workspace-1',
          instance_id: null,
        }),
        authority_revision: null,
        retryable: false,
        authority_source: 'cloud_service',
        supporting_authority_sources: Object.freeze([]),
        provenance: 'observed',
      }),
    }),
  });
}
