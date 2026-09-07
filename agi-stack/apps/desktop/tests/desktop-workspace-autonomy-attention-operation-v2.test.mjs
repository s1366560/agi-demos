import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopWorkspaceAutonomyAttentionAuthorityUnavailableErrorV2,
  createDesktopWorkspaceAutonomyAttentionOperationsV2,
} = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceAutonomyAttentionAuthorityModuleV2.js'
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46951',
    apiKey: 'workspace-attention-session',
    localApiToken: 'workspace-attention-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace/project-1',
    ...overrides,
  };
}

function attention(overrides = {}) {
  return {
    attention_id: 'attention-1',
    root_task_id: 'root-task-1',
    source_kind: 'judge_block',
    source_id: 'judge-1',
    reason: 'Operator decision required',
    status: 'open',
    created_at_ms: 17,
    ...overrides,
  };
}

function serviceFixture(received = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config, workspaceId) {
      received.push({ kind: 'bind-operation', config, workspaceId });
      return Object.freeze({
        async listWorkspaceAutonomyAttentions(signal) {
          received.push({ kind: 'list', signal });
          return typeof overrides.attentions === 'function'
            ? overrides.attentions()
            : (overrides.attentions ?? [attention()]);
        },
        async getWorkspaceAuthorityRevision(signal) {
          received.push({ kind: 'revision', signal });
          return overrides.revision ?? 7;
        },
        async retryWorkspaceAutonomyAttention(attentionId, signal) {
          received.push({ kind: 'retry', attentionId, signal });
          return (
            overrides.retryResponse ?? {
              attention_id: attentionId,
              status: 'retry_queued',
            }
          );
        },
        async resolveWorkspaceAutonomyAttention(
          attentionId,
          expectedRevision,
          idempotencyKey,
          signal,
        ) {
          received.push({
            kind: 'resolve',
            attentionId,
            expectedRevision,
            idempotencyKey,
            signal,
          });
          return (
            overrides.resolveResponse ?? {
              attention_id: attentionId,
              status: 'resolved',
              committed_revision: expectedRevision + 1,
              replayed: false,
            }
          );
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = []) {
  return {
    acquireServiceOperationLease: async (request) => {
      lifecycle.push({ type: 'acquire', digest, request });
      let released = false;
      return {
        status: 'accepted',
        digest,
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(service);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push({ type: 'release', digest });
        },
      };
    },
  };
}

function operations(actions) {
  return createDesktopWorkspaceAutonomyAttentionOperationsV2(() => actions);
}

test('list, retry and resolve workflows each pin one frozen project generation', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const authority = operations(
    acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle),
  );

  const listPending = authority.listWorkspaceAutonomyAttentions({
    config,
    workspaceId: 'workspace-1',
    signal: controller.signal,
  });
  const retryPending = authority.withRetryWorkspaceAutonomyAttention(
    {
      config,
      workspaceId: 'workspace-1',
      attentionId: 'attention-1',
      signal: controller.signal,
    },
    async (client) => {
      await client.retryWorkspaceAutonomyAttention('attention-1', controller.signal);
      return client.listWorkspaceAutonomyAttentions(controller.signal);
    },
  );
  const resolvePending = authority.withResolveWorkspaceAutonomyAttention(
    {
      config,
      workspaceId: 'workspace-1',
      actorId: 'actor-1',
      attentionId: 'attention-1',
      expectedRevision: null,
      idempotencyKey: 'desktop-attention-idempotency-1',
      signal: controller.signal,
    },
    async (client, prepared) => {
      const revision = await client.getWorkspaceAuthorityRevision(controller.signal);
      await client.resolveWorkspaceAutonomyAttention(
        prepared.attentionId,
        revision,
        prepared.idempotencyKey,
        controller.signal,
      );
      return client.listWorkspaceAutonomyAttentions(controller.signal);
    },
  );
  config.tenantId = 'mutated-tenant';
  config.workspaceId = 'mutated-workspace';

  const [listed, retried, resolved] = await Promise.all([
    listPending,
    retryPending,
    resolvePending,
  ]);
  assert.equal(Object.isFrozen(authority), true);
  for (const value of [listed, retried, resolved]) {
    assert.equal(Object.isFrozen(value), true);
    assert.equal(Object.isFrozen(value[0]), true);
    assert.equal(value[0].attention_id, 'attention-1');
  }
  assert.equal(received.filter(({ kind }) => kind === 'bind-operation').length, 3);
  for (const item of received.filter(({ kind }) => kind === 'bind-operation')) {
    assert.equal(item.config.tenantId, 'tenant-1');
    assert.equal(item.config.workspaceId, 'workspace-1');
    assert.equal(item.workspaceId, 'workspace-1');
    assert.equal(Object.isFrozen(item.config), true);
  }
  assert.equal(
    received.every(({ signal }) => signal === undefined || signal === controller.signal),
    true,
  );
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request }) => request),
    Array.from({ length: 3 }, () => ({
      service: 'service:desktop-renderer.workspace-autonomy-attention-authority',
      version: '1.0.0',
      scope: {
        kind: 'project',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
      },
    })),
  );
  assert.equal(lifecycle.filter(({ type }) => type === 'release').length, 3);
});

test('invalid operation identity fails before acquisition or mutation', async () => {
  let acquisitions = 0;
  const authority = operations({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  });
  const listInput = { config: runtimeConfig(), workspaceId: 'workspace-1' };
  for (const input of [
    { ...listInput, config: runtimeConfig({ tenantId: '' }) },
    { ...listInput, workspaceId: ' workspace-1' },
    { ...listInput, workspaceId: 'workspace-2' },
    { ...listInput, signal: {} },
    { ...listInput, legacy: true },
  ]) {
    assert.throws(
      () => authority.listWorkspaceAutonomyAttentions(input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_autonomy_attention_input_invalid',
    );
  }
  for (const input of [
    {
      ...listInput,
      actorId: '',
      attentionId: 'attention-1',
      expectedRevision: null,
      idempotencyKey: 'desktop-attention-idempotency-1',
    },
    {
      ...listInput,
      actorId: 'actor-1',
      attentionId: '',
      expectedRevision: null,
      idempotencyKey: 'desktop-attention-idempotency-1',
    },
    {
      ...listInput,
      actorId: 'actor-1',
      attentionId: 'attention-1',
      expectedRevision: -1,
      idempotencyKey: 'desktop-attention-idempotency-1',
    },
    {
      ...listInput,
      actorId: 'actor-1',
      attentionId: 'attention-1',
      expectedRevision: null,
      idempotencyKey: 'short',
    },
  ]) {
    assert.throws(
      () => authority.withResolveWorkspaceAutonomyAttention(input, () => undefined),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_autonomy_attention_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);

  const live = operations(
    acceptedActions(serviceFixture(), 'sha256:guarded-identity'),
  );
  await assert.rejects(
    live.withRetryWorkspaceAutonomyAttention(
      { ...listInput, attentionId: 'attention-1' },
      (client) => client.retryWorkspaceAutonomyAttention('attention-2'),
    ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_autonomy_attention_input_invalid',
  );
  await assert.rejects(
    live.withResolveWorkspaceAutonomyAttention(
      {
        ...listInput,
        actorId: 'actor-1',
        attentionId: 'attention-1',
        expectedRevision: null,
        idempotencyKey: 'desktop-attention-idempotency-1',
      },
      (client) =>
        client.resolveWorkspaceAutonomyAttention(
          'attention-1',
          7,
          'desktop-attention-idempotency-1',
        ),
    ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_autonomy_attention_input_invalid',
  );
});

test('all authority responses are shape-checked at the generation boundary', async () => {
  const base = { config: runtimeConfig(), workspaceId: 'workspace-1' };
  for (const attentions of [
    [{ ...attention(), status: 'resolved' }],
    [attention(), attention()],
    [{ ...attention(), legacy: true }],
  ]) {
    await assert.rejects(
      operations(
        acceptedActions(serviceFixture([], { attentions }), 'sha256:bad-list'),
      ).listWorkspaceAutonomyAttentions(base),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_autonomy_attention_response_invalid',
    );
  }
  await assert.rejects(
    operations(
      acceptedActions(serviceFixture([], { revision: -1 }), 'sha256:bad-revision'),
    ).withResolveWorkspaceAutonomyAttention(
      {
        ...base,
        actorId: 'actor-1',
        attentionId: 'attention-1',
        expectedRevision: null,
        idempotencyKey: 'desktop-attention-idempotency-1',
      },
      (client) => client.getWorkspaceAuthorityRevision(),
    ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_autonomy_attention_response_invalid',
  );
  await assert.rejects(
    operations(
      acceptedActions(
        serviceFixture([], {
          retryResponse: { attention_id: 'attention-2', status: 'retry_queued' },
        }),
        'sha256:bad-retry',
      ),
    ).withRetryWorkspaceAutonomyAttention(
      { ...base, attentionId: 'attention-1' },
      (client) => client.retryWorkspaceAutonomyAttention('attention-1'),
    ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_autonomy_attention_response_invalid',
  );
});

test('missing generation, rejected or malformed services and escaped authorities fail closed', async () => {
  const base = { config: runtimeConfig(), workspaceId: 'workspace-1' };
  assert.throws(
    () => operations(null).listWorkspaceAutonomyAttentions(base),
    (error) =>
      error instanceof DesktopWorkspaceAutonomyAttentionAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  for (const runtimeCode of ['missing_service', 'service_version_mismatch']) {
    await assert.rejects(
      operations({
        acquireServiceOperationLease: async () => ({
          status: 'rejected',
          reasonCode: 'desktop_renderer_service_resolve_failed',
          runtimeCode,
        }),
      }).listWorkspaceAutonomyAttentions(base),
      (error) =>
        error instanceof DesktopWorkspaceAutonomyAttentionAuthorityUnavailableErrorV2 &&
        error.runtimeCode === runtimeCode,
    );
  }
  for (const service of [
    {},
    { bindOperation: () => ({}) },
    {
      bindOperation: () => ({
        listWorkspaceAutonomyAttentions: async () => [],
        getWorkspaceAuthorityRevision: async () => 1,
        retryWorkspaceAutonomyAttention: async () => ({
          attention_id: 'attention-1',
          status: 'retry_queued',
        }),
        resolveWorkspaceAutonomyAttention: async () => ({
          attention_id: 'attention-1',
          status: 'resolved',
          committed_revision: 2,
          replayed: false,
        }),
        legacyFallback: () => undefined,
      }),
    },
  ]) {
    await assert.rejects(
      operations(acceptedActions(service, 'sha256:invalid-service'))
        .listWorkspaceAutonomyAttentions(base),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_autonomy_attention_service_invalid',
    );
  }

  let escaped;
  await operations(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
  ).withRetryWorkspaceAutonomyAttention(
    { ...base, attentionId: 'attention-1' },
    (client) => {
      escaped = client;
      return 'complete';
    },
  );
  assert.throws(
    () => escaped.listWorkspaceAutonomyAttentions(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_autonomy_attention_operation_released',
  );
});

test('operation errors outrank release failures and successful cleanup failures surface once', async () => {
  const input = { config: runtimeConfig(), workspaceId: 'workspace-1' };
  let failureReleases = 0;
  await assert.rejects(
    operations({
      acquireServiceOperationLease: async () => ({
        status: 'accepted',
        digest: 'sha256:release-failure',
        useService: (operation) => operation(serviceFixture([], { attentions: Promise.reject(new Error('attention_operation_failed')) })),
        release: async () => {
          failureReleases += 1;
          throw new Error('attention_release_failed');
        },
      }),
    }).listWorkspaceAutonomyAttentions(input),
    /attention_operation_failed/u,
  );
  assert.equal(failureReleases, 1);

  let successReleases = 0;
  await assert.rejects(
    operations({
      acquireServiceOperationLease: async () => ({
        status: 'accepted',
        digest: 'sha256:release-failure',
        useService: (operation) => operation(serviceFixture()),
        release: async () => {
          successReleases += 1;
          throw new Error('attention_release_failed');
        },
      }),
    }).listWorkspaceAutonomyAttentions(input),
    /attention_release_failed/u,
  );
  assert.equal(successReleases, 1);
});

test('HMR keeps retry and canonical reread on the old generation', async () => {
  const lifecycle = [];
  let actions;
  const oldReceived = [];
  const oldService = serviceFixture(oldReceived, {
    attentions: () => [attention({ source_id: 'old-generation' })],
  });
  const newService = serviceFixture([], {
    attentions: () => [attention({ source_id: 'new-generation' })],
  });
  actions = acceptedActions(oldService, 'sha256:old', lifecycle);
  const authority = createDesktopWorkspaceAutonomyAttentionOperationsV2(() => actions);
  const input = {
    config: runtimeConfig(),
    workspaceId: 'workspace-1',
    attentionId: 'attention-1',
  };

  const old = await authority.withRetryWorkspaceAutonomyAttention(input, async (client) => {
    await client.retryWorkspaceAutonomyAttention('attention-1');
    actions = acceptedActions(newService, 'sha256:new', lifecycle);
    return client.listWorkspaceAutonomyAttentions();
  });
  const next = await authority.withRetryWorkspaceAutonomyAttention(input, async (client) => {
    await client.retryWorkspaceAutonomyAttention('attention-1');
    return client.listWorkspaceAutonomyAttentions();
  });

  assert.equal(old[0].source_id, 'old-generation');
  assert.equal(next[0].source_id, 'new-generation');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    [
      'acquire:sha256:old',
      'release:sha256:old',
      'acquire:sha256:new',
      'release:sha256:new',
    ],
  );
});
