import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const { createDesktopProjectBlackboardAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectBlackboardTransportV2.js',
);
const { requireCapabilityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectBlackboardOperationContractV2.js',
);

function runtimeConfig() {
  return Object.freeze({
    apiBaseUrl: 'http://127.0.0.1:47771',
    deviceAuthorizationBaseUrl: 'https://auth.example.test',
    apiKey: 'test-session',
    localApiToken: 'test-launch',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    mode: 'local',
    workspaceRoot: '/workspace',
  });
}

test('Local collaboration transport binds verified scope before the V2 service contract', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const { WORKSPACE_HTTP_MUTATION_ACTIONS } = require(
    COMPILED_ROOT + '/src/features/workspace/workspaceCollaborationHttpMutations.js',
  );
  const config = runtimeConfig();
  let responseWorkspace = config.workspaceId;
  let authorityWorkspace = config.workspaceId;
  let revision = 1;
  globalThis.window = undefined;
  globalThis.fetch = async (url) => {
    const identity = {
      contract_version: '2.0.0',
      tenant_id: config.tenantId,
      project_id: config.projectId,
      workspace_id: responseWorkspace,
    };
    const payload = String(url).endsWith('/authority')
      ? { ...identity, workspace_id: authorityWorkspace, revision, cursor: 'workspace:workspace-1:revision:1' }
      : {
          ...identity,
          service_version: '0.2.0',
          authority: 'local',
          status: 'available',
          reason_code: null,
          canonical_read: true,
          read_surfaces: Object.keys(WORKSPACE_HTTP_MUTATION_ACTIONS),
          mutations: {
            allowed: true,
            revision_guarded: true,
            idempotency_guarded: true,
            actions: WORKSPACE_HTTP_MUTATION_ACTIONS,
          },
          allowed_actions: WORKSPACE_HTTP_MUTATION_ACTIONS,
        };
    return new Response(JSON.stringify(payload), {
      headers: { 'content-type': 'application/json' },
    });
  };
  try {
    const authority = createDesktopProjectBlackboardAuthorityV2(config);
    const requestedScope = {
      tenantId: config.tenantId,
      projectId: config.projectId,
      workspaceId: config.workspaceId,
    };
    const capability = requireCapabilityV2(
      await authority.probeWorkspaceCollaborationCapability(requestedScope),
      config,
    );
    assert.equal(capability.availability, 'available');
    assert.equal(capability.authority_revision, 1);
    assert.equal(capability.scope.workspace_id, config.workspaceId);
    responseWorkspace = 'other-workspace';
    const rejected = requireCapabilityV2(
      await authority.probeWorkspaceCollaborationCapability(requestedScope),
      config,
    );
    assert.equal(rejected.availability, 'unavailable');
    assert.equal(rejected.reason_code, 'workspace_collaboration_capability_scope_mismatch');
    assert.equal(rejected.scope.workspace_id, null);
    responseWorkspace = config.workspaceId;
    authorityWorkspace = 'other-workspace';
    const mismatchedAuthority = await authority.probeWorkspaceCollaborationCapability(requestedScope);
    assert.equal(mismatchedAuthority.availability, 'unavailable');
    assert.equal(mismatchedAuthority.reason_code, 'workspace_collaboration_authority_contract_invalid');
    authorityWorkspace = config.workspaceId;
    revision = -1;
    const invalidRevision = await authority.probeWorkspaceCollaborationCapability(requestedScope);
    assert.equal(invalidRevision.availability, 'unavailable');
    assert.equal(invalidRevision.authority_revision, null);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
  }
});
