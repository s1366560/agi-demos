import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);

const compiledModule =
  '/tmp/agistack-desktop-test-dist/src/api/cloudSessionProjectionClient.js';

afterEach(() => {
  delete globalThis.window;
});

test('renderer decodes a credential-free Cloud identity and workspace projection', () => {
  const { decodeCloudSessionProjection } = require(compiledModule);
  const projection = decodeCloudSessionProjection(projectionPayload());

  assert.deepEqual(projection, {
    status: 'authenticated',
    apiBaseUrl: 'https://cloud.memstack.test',
    expiresAt: '2099-08-10T00:00:00Z',
    user: {
      userId: 'user-1',
      email: 'user@example.test',
      name: 'User One',
      roles: ['member'],
      globalRoles: [],
      active: true,
      superuser: false,
      createdAt: '2026-08-10T00:00:00Z',
      preferredLanguage: 'zh-CN',
    },
    workspaceContext: {
      tenantId: 'tenant-1',
      projectId: 'project-1',
      revision: 7,
      updatedAt: '2026-08-10T00:01:00Z',
      membershipRole: 'member',
    },
    tenants: [{ id: 'tenant-1', name: 'Tenant One', slug: 'tenant-one' }],
    projects: [
      {
        id: 'project-1',
        tenant_id: 'tenant-1',
        name: 'Project One',
        is_public: false,
      },
    ],
  });
  assert.equal(JSON.stringify(projection).includes('oauth-subject-not-for-renderer'), false);
});

test('renderer rejects projection drift and any top-level credential field', () => {
  const { decodeCloudSessionProjection } = require(compiledModule);

  assert.equal(
    decodeCloudSessionProjection({
      ...projectionPayload(),
      credential: 'must-never-cross-the-preload-boundary',
    }),
    null,
  );
  assert.equal(
    decodeCloudSessionProjection({
      ...projectionPayload(),
      workspace_context: {
        ...projectionPayload().workspace_context,
        context: {
          ...projectionPayload().workspace_context.context,
          revision: -1,
        },
      },
    }),
    null,
  );
  assert.equal(
    decodeCloudSessionProjection({
      ...projectionPayload(),
      user: { ...projectionPayload().user, access_token: 'forbidden' },
    }),
    null,
  );
  assert.equal(
    decodeCloudSessionProjection({
      ...projectionPayload(),
      projects: [{ id: 'project-1', tenant_id: 'other-tenant', name: 'Project One' }],
    }),
    null,
  );
});

test('renderer accepts a tenant-only Cloud projection without inventing project authority', () => {
  const { decodeCloudSessionProjection } = require(compiledModule);
  const payload = projectionPayload();
  const projection = decodeCloudSessionProjection({
    ...payload,
    workspace_context: {
      ...payload.workspace_context,
      context: {
        ...payload.workspace_context.context,
        project_id: null,
      },
    },
    projects: [],
  });

  assert.equal(projection.workspaceContext.projectId, null);
  assert.deepEqual(projection.projects, []);
});

test('renderer client invokes only the cancellable projection command', async () => {
  const { desktopCloudSessionProjectionClient } = require(compiledModule);
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async (command, args) => {
          commands.push({ command, args });
          return projectionPayload();
        },
      },
    },
  };

  const client = desktopCloudSessionProjectionClient();
  assert.ok(client);
  assert.deepEqual(await client.load(), decodeExpectedProjection());
  assert.equal(commands.length, 1);
  assert.equal(commands[0].command, 'cloud_session_projection');
  assert.match(commands[0].args.requestId, /^[0-9a-f-]{36}$/u);
  assert.equal(JSON.stringify(commands).includes('credential'), false);
});

test('renderer projection cancellation is owner-bound through the existing cancel command', async () => {
  const { desktopCloudSessionProjectionClient } = require(compiledModule);
  const commands = [];
  let resolveProjection;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async (command, args) => {
          commands.push({ command, args });
          if (command === 'cloud_request_cancel') return { cancelled: true };
          return new Promise((resolve) => {
            resolveProjection = resolve;
          });
        },
      },
    },
  };

  const controller = new AbortController();
  const request = desktopCloudSessionProjectionClient().load(controller.signal);
  controller.abort();

  await assert.rejects(request, { name: 'AbortError' });
  assert.equal(commands.length, 2);
  assert.equal(commands[0].command, 'cloud_session_projection');
  assert.deepEqual(commands[1], {
    command: 'cloud_request_cancel',
    args: { requestId: commands[0].args.requestId },
  });
  resolveProjection?.(projectionPayload());
});

test('renderer client fails closed on a malformed main-process projection', async () => {
  const { desktopCloudSessionProjectionClient } = require(compiledModule);
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async () => ({ ...projectionPayload(), status: 'expired' }),
      },
    },
  };

  await assert.rejects(desktopCloudSessionProjectionClient().load(), {
    message: 'cloud_session_projection_contract_invalid',
  });
});

function projectionPayload() {
  return {
    status: 'authenticated',
    api_base_url: 'https://cloud.memstack.test',
    expires_at: '2099-08-10T00:00:00Z',
    user: {
      user_id: 'user-1',
      email: 'user@example.test',
      name: 'User One',
      roles: ['member'],
      global_roles: [],
      is_active: true,
      is_superuser: false,
      created_at: '2026-08-10T00:00:00Z',
      profile: {
        avatar_url: 'https://images.example.test/avatar.png',
        oauth_identities: {
          github: { subject: 'oauth-subject-not-for-renderer' },
        },
      },
      preferred_language: 'zh-CN',
    },
    workspace_context: {
      context: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        revision: 7,
        updated_at: '2026-08-10T00:01:00Z',
      },
      membership_role: 'member',
    },
    tenants: [{ id: 'tenant-1', name: 'Tenant One', slug: 'tenant-one' }],
    projects: [
      {
        id: 'project-1',
        tenant_id: 'tenant-1',
        name: 'Project One',
        is_public: false,
      },
    ],
  };
}

function decodeExpectedProjection() {
  return {
    status: 'authenticated',
    apiBaseUrl: 'https://cloud.memstack.test',
    expiresAt: '2099-08-10T00:00:00Z',
    user: {
      userId: 'user-1',
      email: 'user@example.test',
      name: 'User One',
      roles: ['member'],
      globalRoles: [],
      active: true,
      superuser: false,
      createdAt: '2026-08-10T00:00:00Z',
      preferredLanguage: 'zh-CN',
    },
    workspaceContext: {
      tenantId: 'tenant-1',
      projectId: 'project-1',
      revision: 7,
      updatedAt: '2026-08-10T00:01:00Z',
      membershipRole: 'member',
    },
    tenants: [{ id: 'tenant-1', name: 'Tenant One', slug: 'tenant-one' }],
    projects: [
      {
        id: 'project-1',
        tenant_id: 'tenant-1',
        name: 'Project One',
        is_public: false,
      },
    ],
  };
}
