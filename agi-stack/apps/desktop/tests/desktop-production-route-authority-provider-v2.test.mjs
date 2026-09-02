import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  createDesktopProductionRouteAuthorityProviderV2,
  DesktopProductionRouteAuthorityProviderErrorV2,
} from '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteAuthorityProviderV2.js';

const tenantId = 'tenant-1';
const projectId = 'project-1';

test('production route authority provider fails closed before publication', () => {
  const provider = createDesktopProductionRouteAuthorityProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopProductionRouteAuthorityProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_production_route_authority_unpublished');
      assert.equal(error.message, 'desktop_production_route_authority_unpublished');
      return true;
    }
  );
});

test('each publication returns one frozen pinned authority binding', () => {
  const provider = createDesktopProductionRouteAuthorityProviderV2();
  const firstCapability = capabilityEntry({ authority_revision: 7 });
  const first = provider.publish(
    input({
      capabilitySnapshot: capabilitySnapshot('cloud', {
        'project-project-overview': firstCapability,
      }),
    })
  );

  assert.equal(Object.isFrozen(first), true);
  assert.equal(first.mode, 'cloud');
  assert.deepEqual([...first.permissions], ['authenticated']);
  assert.equal(
    first.resolveCapability('project-project-overview', { tenantId, projectId }),
    firstCapability
  );

  const secondCapability = capabilityEntry({ authority_revision: 8 });
  const second = provider.publish(
    input({
      config: runtimeConfig('local'),
      capabilitySnapshot: capabilitySnapshot('local_offline', {
        'project-project-overview': secondCapability,
      }),
    })
  );

  assert.equal(provider.resolve(), second);
  assert.notEqual(second, first);
  assert.equal(second.mode, 'local_offline');
  assert.equal(
    second.resolveCapability('project-project-overview', { tenantId, projectId }),
    secondCapability
  );
  assert.equal(first.mode, 'cloud');
  assert.equal(
    first.resolveCapability('project-project-overview', { tenantId, projectId }),
    firstCapability
  );
});

test('native capability runtime state falls back to the configured route mode', () => {
  const provider = createDesktopProductionRouteAuthorityProviderV2();

  const cloud = provider.publish(input({ capabilitySnapshot: capabilitySnapshot('native', {}) }));
  const local = provider.publish(
    input({
      config: runtimeConfig('local'),
      capabilitySnapshot: capabilitySnapshot('native', {}),
    })
  );

  assert.equal(cloud.mode, 'cloud');
  assert.equal(local.mode, 'local');
});

test('authentication kernel capabilities remain explicit and ignore snapshot aliases', () => {
  const provider = createDesktopProductionRouteAuthorityProviderV2();
  const forged = capabilityEntry({ availability: 'available', reason_code: null });
  const cloud = provider.publish(
    input({
      capabilitySnapshot: capabilitySnapshot('cloud', {
        'device-approval': forged,
        'tenant-creation': forged,
        'invitation-acceptance': forged,
      }),
    })
  );

  for (const capability of ['device-approval', 'tenant-creation', 'invitation-acceptance']) {
    const resolved = cloud.resolveCapability(capability, {});
    assert.notEqual(resolved, forged);
    assert.equal(resolved.availability, 'unavailable');
    assert.equal(resolved.reason_code, 'renderer_capability_authority_unobserved');
  }

  const local = provider.publish(
    input({
      config: runtimeConfig('local'),
      capabilitySnapshot: capabilitySnapshot('local_online', {}),
    })
  );
  assert.equal(local.resolveCapability('device-approval', {}).availability, 'not_applicable');
  assert.equal(local.resolveCapability('tenant-creation', {}).availability, 'not_applicable');
  assert.equal(local.resolveCapability('invitation-acceptance', {}).availability, 'not_applicable');
});

test('local-online cloud-only permissions resolve through the vault-bound broker', async () => {
  const requests = [];
  const provider = createDesktopProductionRouteAuthorityProviderV2();
  const authority = provider.publish(
    input({
      config: runtimeConfig('local'),
      capabilitySnapshot: capabilitySnapshot('local_online', {}),
      cloudRequestBroker: broker(requests),
    })
  );

  const snapshot = await authority.resolvePermissionSnapshot(
    { tenantId, projectId },
    new AbortController().signal,
    { definition: { localPolicy: 'cloud_only' } }
  );

  assert.equal(snapshot.subject_id, 'user-1');
  assert.deepEqual(snapshot.permissions, ['authenticated', 'tenant_member', 'project_member']);
  assert.deepEqual(requests, ['/api/v1/auth/me', '/api/v1/workspace-context']);
});

test('local-online cloud-only permissions fail closed without a broker', async () => {
  const provider = createDesktopProductionRouteAuthorityProviderV2();
  const authority = provider.publish(
    input({
      config: runtimeConfig('local'),
      capabilitySnapshot: capabilitySnapshot('local_online', {}),
      cloudRequestBroker: null,
    })
  );

  await assert.rejects(
    authority.resolvePermissionSnapshot({ tenantId, projectId }, new AbortController().signal, {
      definition: { localPolicy: 'cloud_only' },
    }),
    /cloud_request_broker_missing/u
  );
});

function input(overrides = {}) {
  return {
    auth: authState(),
    config: runtimeConfig('cloud'),
    capabilitySnapshot: capabilitySnapshot('cloud', {}),
    cloudRequestBroker: null,
    workspaceRosterOperationsV2: Object.freeze({
      listWorkspaceMembers: async () => [],
      listWorkspaceAgents: async () => [],
    }),
    ...overrides,
  };
}

function authState(overrides = {}) {
  return {
    status: 'signed_in',
    credentialKind: 'cloud_session',
    session: null,
    context: null,
    user: {
      user_id: 'user-1',
      email: 'user@example.com',
      name: 'User',
      roles: [],
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      profile: {},
    },
    tenants: [],
    projects: [],
    mustChangePassword: false,
    error: null,
    ...overrides,
  };
}

function runtimeConfig(mode) {
  return {
    apiBaseUrl: mode === 'cloud' ? 'https://api.example.test' : 'http://127.0.0.1:1',
    deviceAuthorizationBaseUrl: 'https://auth.example.test',
    apiKey: '',
    localApiToken: mode === 'local' ? 'redacted-local-credential' : '',
    tenantId,
    projectId,
    workspaceId: 'workspace-1',
    mode,
    workspaceRoot: '/workspace',
  };
}

function capabilitySnapshot(runtimeState, capabilities) {
  return Object.freeze({
    version: '5.0.0',
    runtime_state: runtimeState,
    capabilities: Object.freeze(capabilities),
  });
}

function capabilityEntry(overrides = {}) {
  return Object.freeze({
    availability: 'available',
    reason_code: null,
    service_version: '3.0.0',
    contract_version: '5.0.0',
    allowed_actions: Object.freeze(['view']),
    scope: Object.freeze({
      tenant_id: tenantId,
      project_id: projectId,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: 7,
    authority_source: 'cloud_service',
    supporting_authority_sources: Object.freeze([]),
    provenance: 'observed',
    ...overrides,
  });
}

function broker(requests) {
  return Object.freeze({
    async requestJson(request) {
      requests.push(request.path);
      if (request.path === '/api/v1/auth/me') {
        return {
          user_id: 'user-1',
          roles: [],
          global_roles: [],
          is_superuser: false,
        };
      }
      if (request.path === '/api/v1/workspace-context') {
        return {
          context: {
            tenant_id: tenantId,
            project_id: projectId,
            revision: 11,
            updated_at: '2026-08-31T00:00:00Z',
          },
          membership_role: 'member',
        };
      }
      throw new Error(`unexpected request: ${request.path}`);
    },
    async requestNoContent() {
      throw new Error('requestNoContent is not expected');
    },
    async requestResponse() {
      throw new Error('requestResponse is not expected');
    },
  });
}
