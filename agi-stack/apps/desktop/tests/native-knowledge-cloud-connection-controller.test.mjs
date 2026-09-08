import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const require = createRequire(import.meta.url);
function loadSource(relative) {
  const path = new URL(relative, import.meta.url);
  const source = readFileSync(path, 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
  });
  const module = { exports: {} };
  new Function('module', 'exports', 'require', outputText)(module, module.exports, require);
  return module.exports;
}
const { createNativeKnowledgeCloudConnectionController: createController } = loadSource(
  '../src/features/project-knowledge/nativeKnowledgeCloudConnectionController.ts',
);
const { DesktopCloudAuthenticationAuthority } = loadSource(
  '../electron/main/cloudAuthenticationAuthority.ts',
);
const scope = {
  tenant_id: 'local-tenant',
  project_id: 'local-project',
  context_revision: 4,
  profile_id: 'native-profile',
  generation: 9,
  digest: 'a'.repeat(64),
};
const authority = {
  available: true,
  scope: {
    authority: 'local',
    tenantId: 'local-tenant',
    projectId: 'local-project',
  },
  userId: 'local-actor',
  sessionId: 'local-session',
  contextRevision: 4,
  generationDigest: scope.digest,
  allowedActions: ['sync_status'],
};
const connection = {
  connection_revision: 'b'.repeat(64),
  authority: 'https://cloud.example.test',
  actor_id: 'cloud-actor',
};
const generation = {
  contract_version: '1.0.0',
  descriptor: {
    profile_id: 'cloud-profile',
    generation: 81,
    digest: 'c'.repeat(64),
  },
};
const enrollment = {
  contract_version: '1.0.0',
  tenant_id: 'remote-tenant',
  project_id: 'remote-project',
  actor_id: connection.actor_id,
  enabled: false,
  can_enroll: true,
  bootstrap_count: 0,
  next_cursor: 0,
  replayed: false,
  generation,
};
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function fixture(overrides = {}) {
  const calls = [];
  const authCalls = [];
  let enabled = false;
  const input = {
    authority,
    sourceClient: {
      observeScope: async (localScope, options) => {
        assert.deepEqual(localScope, authority.scope);
        assert.equal(options.expectedActorId, authority.userId);
        return scope;
      },
    },
    authClient: {
      getStatus: async () => ({ status: 'authenticated' }),
      loginWithPassword: async () => {
        authCalls.push('login');
        return { status: 'authenticated' };
      },
      forceChangePassword: async () => ({ status: 'authenticated' }),
      signOut: async () => {
        authCalls.push('signout');
        return { success: true };
      },
      cancelPendingAuthentication: async () => {
        authCalls.push('cancel');
        return { cancelled: true };
      },
    },
    client: {
      execute: async (localScope, command, options) => {
        calls.push(command);
        assert.deepEqual(localScope, authority.scope);
        assert.deepEqual(options.expectedScope, scope);
        let result;
        if (command.operation === 'connection') result = { connection };
        else if (command.operation === 'tenants')
          result = {
            connection,
            items: [{ id: 'remote-tenant', name: 'Remote tenant' }],
          };
        else if (command.operation === 'projects')
          result = {
            connection,
            tenant_id: command.tenant_id,
            items: [
              {
                id: 'remote-project',
                tenant_id: 'remote-tenant',
                name: 'Remote project',
              },
            ],
          };
        else {
          if (command.operation === 'enroll') enabled = true;
          result = {
            connection,
            enrollment: { ...enrollment, enabled },
            ...(command.operation === 'bind' ? { association_state: 'verified', status: {} } : {}),
          };
        }
        return { contract_version: '1.0.0', scope, result };
      },
    },
    ...overrides,
  };
  return { controller: createController(input), input, calls, authCalls };
}

test('mount is read-only and uses observed tenant/project, enrollment and cloud generation', async () => {
  const { controller, calls, authCalls } = fixture();
  await controller.refresh();
  assert.deepEqual(
    calls.map(({ operation }) => operation),
    ['connection', 'tenants'],
  );
  assert.deepEqual(authCalls, []);
  await controller.selectTenant('invented');
  assert.equal(calls.length, 2);
  await controller.selectTenant('remote-tenant');
  await controller.selectProject('remote-project');
  await controller.bind();
  assert.equal(calls.at(-1).operation, 'enrollment');
  await controller.enroll();
  assert.deepEqual(calls.at(-1).expected_generation, generation);
  assert.equal(controller.getSnapshot().bound, false);
  await controller.bind();
  assert.equal(controller.getSnapshot().bound, true);
  assert.deepEqual(calls.at(-1), {
    operation: 'bind',
    tenant_id: 'remote-tenant',
    project_id: 'remote-project',
    expected_connection_revision: connection.connection_revision,
    expected_generation: generation,
  });
  await controller.disconnect();
  assert.deepEqual(authCalls, ['signout']);
  assert.equal(controller.getSnapshot().bound, false);
  assert.equal(controller.getSnapshot().connection, null);
  assert.deepEqual(authority.scope, {
    authority: 'local',
    tenantId: 'local-tenant',
    projectId: 'local-project',
  });
});

test('late login after disconnect cannot publish connected UI', async () => {
  const pending = deferred();
  const current = fixture();
  current.input.authClient.loginWithPassword = () => pending.promise;
  const controller = createController(current.input);
  const login = controller.login({
    apiBaseUrl: connection.authority,
    username: 'user',
    password: 'secret',
    trustedDevice: false,
  });
  await controller.disconnect();
  pending.resolve({ status: 'authenticated' });
  await login;
  assert.equal(controller.getSnapshot().connection, null);
  assert.deepEqual(current.calls, []);
});

test('a replaced controller cannot publish a late tenant list', async () => {
  const pending = deferred();
  const current = fixture({ client: { execute: () => pending.promise } });
  const load = current.controller.refresh();
  await new Promise((done) => setImmediate(done));
  current.controller.stop();
  pending.resolve({ contract_version: '1.0.0', scope, result: { connection } });
  await load;
  assert.equal(current.controller.getSnapshot().connection, null);
});

test('host password-change state survives renderer owner retirement during vault save', async () => {
  let vault = null;
  let mounted;
  let remounted;
  let replacementRefresh;
  let forceChanged = false;
  const native = new DesktopCloudAuthenticationAuthority({
    now: () => 1700000000000,
    randomId: () => 'device_attempt_12345678',
    fetch: async (url) =>
      new Response(
        JSON.stringify(
          url.endsWith('/token')
            ? {
                access_token: 'main-only-credential',
                token_type: 'bearer',
                must_change_password: true,
              }
            : { success: true, message: 'changed' },
        ),
        { status: 200 },
      ),
    loadTrustedSession: async () => vault,
    saveTrustedSession: async ({ input }) => {
      // The existing main-process authority transition retires the renderer owner.
      mounted.stop();
      vault = input;
      remounted = createController({ ...base.input, authClient });
      replacementRefresh = remounted.refresh();
    },
    clearTrustedSession: async () => {
      vault = null;
    },
  });
  const authClient = {
    getStatus: () => native.getStatus(),
    loginWithPassword: (input) => native.loginWithPassword(input),
    forceChangePassword: async (input) => {
      const result = await native.forceChangePassword(input);
      forceChanged = true;
      return result;
    },
    signOut: () => native.signOut(),
    cancelPendingAuthentication: () => native.cancelPendingAuthentication(),
  };
  const base = fixture();
  mounted = createController({ ...base.input, authClient });
  await mounted.login({
    apiBaseUrl: connection.authority,
    username: 'user',
    password: 'temporary',
    trustedDevice: true,
  });
  await replacementRefresh;
  assert.equal(remounted.getSnapshot().phase, 'password_change_required');
  assert.equal(base.calls.length, 0);
  assert.equal(JSON.stringify(remounted.getSnapshot()).includes('main-only-credential'), false);
  await remounted.changePassword({
    currentPassword: 'temporary',
    newPassword: 'changed-password',
  });
  assert.equal(forceChanged, true);
  assert.equal(remounted.getSnapshot().phase, 'ready');
  assert.deepEqual(await native.getStatus(), { status: 'authenticated' });
  assert.equal(remounted.getSnapshot().connection.actor_id, 'cloud-actor');
  assert.equal(authority.userId, 'local-actor');
});
