import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  createDesktopRouteScopeTransaction,
  DesktopRouteScopeTransactionError,
} from '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteScopeTransaction.js';
import { DEFAULT_CONFIG } from '/tmp/agistack-desktop-test-dist/src/types.js';

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    mode: 'cloud',
    apiBaseUrl: 'https://api.memstack.test',
    apiKey: 'cloud-session',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    ...overrides,
  };
}

function project(id, tenantId) {
  return {
    id,
    tenant_id: tenantId,
    name: `Project ${id}`,
  };
}

function workspaceContext(tenantId, projectId, revision) {
  return {
    tenant_id: tenantId,
    project_id: projectId,
    revision,
    updated_at: '2026-07-30T00:00:00Z',
  };
}

function transactionError(reasonCode) {
  return (error) => {
    assert.equal(error instanceof DesktopRouteScopeTransactionError, true);
    assert.equal(error.reasonCode, reasonCode);
    return true;
  };
}

test('same project route with an omitted workspace is a strict no-op', async () => {
  const current = {
    config: runtimeConfig(),
    authRevision: 9,
  };
  let authorityCreations = 0;
  let commits = 0;
  let refreshes = 0;
  const transaction = createDesktopRouteScopeTransaction({
    getCurrent: () => current,
    createAuthority: () => {
      authorityCreations += 1;
      throw new Error('authority must not be created for a no-op');
    },
    commit: () => {
      commits += 1;
    },
    refresh: async () => {
      refreshes += 1;
    },
  });

  const result = await transaction.switchScope(
    { tenantId: 'tenant-1', projectId: 'project-1' },
    new AbortController().signal,
  );

  assert.equal(result.status, 'unchanged');
  assert.equal(result.config.workspaceId, 'workspace-1');
  assert.equal(authorityCreations, 0);
  assert.equal(commits, 0);
  assert.equal(refreshes, 0);
});

test('project scope switch shares one signal and commits only after authority validation', async () => {
  const calls = [];
  const commits = [];
  const refreshes = [];
  const current = {
    config: runtimeConfig(),
    authRevision: 4,
  };
  const controller = new AbortController();
  let authorityConfig = null;
  const transaction = createDesktopRouteScopeTransaction({
    getCurrent: () => current,
    createAuthority: (config) => {
      authorityConfig = config;
      return {
        async listProjects(tenantId, signal) {
          calls.push({ operation: 'list', tenantId, signal });
          return [project('project-2', 'tenant-2')];
        },
        async getWorkspaceContext(signal) {
          calls.push({ operation: 'get', signal });
          return {
            context: workspaceContext('tenant-1', 'project-1', 7),
            membership_role: 'owner',
          };
        },
        async switchWorkspaceContext(
          tenantId,
          projectId,
          expectedRevision,
          idempotencyKey,
          signal,
        ) {
          calls.push({
            operation: 'switch',
            tenantId,
            projectId,
            expectedRevision,
            idempotencyKey,
            signal,
          });
          return {
            context: workspaceContext('tenant-2', 'project-2', 8),
            changed: true,
          };
        },
      };
    },
    commit: (value) => {
      calls.push({ operation: 'commit' });
      commits.push(value);
    },
    refresh: async (value, signal) => {
      calls.push({ operation: 'refresh', signal });
      refreshes.push(value);
    },
  });

  const result = await transaction.switchScope(
    { tenantId: 'tenant-2', projectId: 'project-2' },
    controller.signal,
  );

  assert.equal(result.status, 'applied');
  assert.deepEqual(
    calls.map((call) => call.operation),
    ['list', 'get', 'switch', 'commit', 'refresh'],
  );
  assert.equal(calls[0].signal, controller.signal);
  assert.equal(calls[1].signal, controller.signal);
  assert.equal(calls[2].signal, controller.signal);
  assert.equal(calls[4].signal, controller.signal);
  assert.equal(calls[2].expectedRevision, 7);
  assert.match(calls[2].idempotencyKey, /^[0-9a-f-]{36}$/i);
  assert.deepEqual(authorityConfig, {
    ...current.config,
    tenantId: 'tenant-2',
    projectId: '',
    workspaceId: '',
  });
  assert.equal(commits.length, 1);
  assert.equal(refreshes.length, 1);
  assert.equal(commits[0], refreshes[0]);
  assert.equal(commits[0].config.tenantId, 'tenant-2');
  assert.equal(commits[0].config.projectId, 'project-2');
  assert.equal(commits[0].config.workspaceId, '');
  assert.equal(commits[0].context.revision, 8);
  assert.deepEqual(commits[0].projects, [project('project-2', 'tenant-2')]);
});

test('auth and transport drift make an in-flight authority read stale', async (t) => {
  for (const drift of ['auth', 'transport']) {
    await t.test(drift, async () => {
      let current = {
        config: runtimeConfig(),
        authRevision: 1,
      };
      let commits = 0;
      const transaction = createDesktopRouteScopeTransaction({
        getCurrent: () => current,
        createAuthority: () => ({
          async listProjects() {
            current =
              drift === 'auth'
                ? { ...current, authRevision: 2 }
                : {
                    ...current,
                    config: {
                      ...current.config,
                      apiBaseUrl: 'https://other.memstack.test',
                    },
                  };
            return [project('project-2', 'tenant-1')];
          },
          async getWorkspaceContext() {
            throw new Error('stale request must stop before the next read');
          },
          async switchWorkspaceContext() {
            throw new Error('stale request must not mutate authority');
          },
        }),
        commit: () => {
          commits += 1;
        },
        refresh: async () => undefined,
      });

      await assert.rejects(
        transaction.switchScope(
          { tenantId: 'tenant-1', projectId: 'project-2' },
          new AbortController().signal,
        ),
        transactionError('desktop_route_scope_transaction_stale'),
      );
      assert.equal(commits, 0);
    });
  }
});

test('a newer no-op transaction supersedes an older pending authority read', async () => {
  const current = {
    config: runtimeConfig(),
    authRevision: 1,
  };
  let resolveProjects;
  const projectsPending = new Promise((resolve) => {
    resolveProjects = resolve;
  });
  let commits = 0;
  const transaction = createDesktopRouteScopeTransaction({
    getCurrent: () => current,
    createAuthority: () => ({
      listProjects: async () => projectsPending,
      getWorkspaceContext: async () => ({
        context: workspaceContext('tenant-1', 'project-1', 1),
        membership_role: 'owner',
      }),
      switchWorkspaceContext: async () => ({
        context: workspaceContext('tenant-1', 'project-2', 2),
        changed: true,
      }),
    }),
    commit: () => {
      commits += 1;
    },
    refresh: async () => undefined,
  });

  const older = transaction.switchScope(
    { tenantId: 'tenant-1', projectId: 'project-2' },
    new AbortController().signal,
  );
  const newer = await transaction.switchScope(
    { tenantId: 'tenant-1', projectId: 'project-1' },
    new AbortController().signal,
  );
  resolveProjects([project('project-2', 'tenant-1')]);

  assert.equal(newer.status, 'unchanged');
  await assert.rejects(
    older,
    transactionError('desktop_route_scope_transaction_stale'),
  );
  assert.equal(commits, 0);
});

test('scope response mismatch fails closed before commit or refresh', async () => {
  let commits = 0;
  let refreshes = 0;
  const transaction = createDesktopRouteScopeTransaction({
    getCurrent: () => ({
      config: runtimeConfig(),
      authRevision: 1,
    }),
    createAuthority: () => ({
      listProjects: async () => [project('project-2', 'tenant-1')],
      getWorkspaceContext: async () => ({
        context: workspaceContext('tenant-1', 'project-1', 2),
        membership_role: 'owner',
      }),
      switchWorkspaceContext: async () => ({
        context: workspaceContext('tenant-other', 'project-2', 3),
        changed: true,
      }),
    }),
    commit: () => {
      commits += 1;
    },
    refresh: async () => {
      refreshes += 1;
    },
  });

  await assert.rejects(
    transaction.switchScope(
      { tenantId: 'tenant-1', projectId: 'project-2' },
      new AbortController().signal,
    ),
    transactionError('desktop_route_scope_authority_mismatch'),
  );
  assert.equal(commits, 0);
  assert.equal(refreshes, 0);
});

test('a changed workspace-only scope fails with a stable unsupported code', async () => {
  let authorityCreations = 0;
  const transaction = createDesktopRouteScopeTransaction({
    getCurrent: () => ({
      config: runtimeConfig(),
      authRevision: 1,
    }),
    createAuthority: () => {
      authorityCreations += 1;
      throw new Error('unsupported workspace scope must not create authority');
    },
    commit: () => undefined,
    refresh: async () => undefined,
  });

  await assert.rejects(
    transaction.switchScope(
      {
        tenantId: 'tenant-1',
        projectId: 'project-1',
        workspaceId: 'workspace-2',
      },
      new AbortController().signal,
    ),
    transactionError('desktop_route_scope_workspace_unsupported'),
  );
  assert.equal(authorityCreations, 0);
});

test('an aborted mutation is reconciled by a fresh authority read on the next attempt', async () => {
  let serverContext = workspaceContext('tenant-1', 'project-1', 1);
  let switches = 0;
  const commits = [];
  const firstController = new AbortController();
  const current = {
    config: runtimeConfig(),
    authRevision: 1,
  };
  const transaction = createDesktopRouteScopeTransaction({
    getCurrent: () => current,
    createAuthority: () => ({
      listProjects: async (_tenantId, signal) => {
        assert.equal(signal.aborted, false);
        return [project('project-2', 'tenant-1')];
      },
      getWorkspaceContext: async (signal) => {
        assert.equal(signal.aborted, false);
        return { context: serverContext, membership_role: 'owner' };
      },
      switchWorkspaceContext: async (
        tenantId,
        projectId,
        _expectedRevision,
        _idempotencyKey,
        signal,
      ) => {
        switches += 1;
        serverContext = workspaceContext(tenantId, projectId, 2);
        assert.equal(signal, firstController.signal);
        firstController.abort(new DOMException('superseded', 'AbortError'));
        return { context: serverContext, changed: true };
      },
    }),
    commit: (value) => {
      commits.push(value);
    },
    refresh: async () => undefined,
  });

  await assert.rejects(
    transaction.switchScope(
      { tenantId: 'tenant-1', projectId: 'project-2' },
      firstController.signal,
    ),
    (error) => error instanceof DOMException && error.name === 'AbortError',
  );
  assert.equal(commits.length, 0);

  const reconciled = await transaction.switchScope(
    { tenantId: 'tenant-1', projectId: 'project-2' },
    new AbortController().signal,
  );
  assert.equal(reconciled.status, 'applied');
  assert.equal(switches, 1);
  assert.equal(commits.length, 1);
  assert.equal(commits[0].context.revision, 2);
});
