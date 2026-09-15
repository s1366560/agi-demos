import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopSessionRunControlAuthorityUnavailableErrorV2,
  createDesktopSessionRunControlOperationsV2,
  withDesktopSessionRunControlAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopSessionRunControlAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46853',
    apiKey: 'run-control-session',
    localApiToken: 'run-control-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace/project-1',
    ...overrides,
  };
}

function run(overrides = {}) {
  return {
    id: 'run-1',
    conversation_id: 'conversation-1',
    project_id: 'project-1',
    plan_version_id: 'plan-1',
    idempotency_key: 'run-idempotency-1',
    message_id: 'message-1',
    request_message: 'Build the report',
    status: 'running',
    revision: 8,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:01:00Z',
    authorization_snapshot: {},
    ...overrides,
  };
}

function controlOutcome(status, expectedRevision, overrides = {}) {
  return {
    accepted: true,
    status,
    run: run({ status, revision: expectedRevision + 1 }),
    ...overrides,
  };
}

function requestedOutcome(status, expectedRevision, overrides = {}) {
  return {
    accepted: true,
    status,
    run: run({ status: 'running', revision: expectedRevision }),
    ...overrides,
  };
}

function forkOutcome(expectedRevision, idempotencyKey, overrides = {}) {
  return {
    accepted: true,
    created: true,
    status: 'running',
    source_run: run({ status: 'disconnected', revision: expectedRevision }),
    run: run({
      id: 'recovery-run-1',
      status: 'running',
      revision: 0,
      idempotency_key: idempotencyKey,
    }),
    ...overrides,
  };
}

function serviceFixture(received = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config, identity) {
      received.push({ kind: 'bind', config, identity });
      return Object.freeze({
        async pauseRun(runId, expectedRevision) {
          received.push({ kind: 'pause', runId, expectedRevision });
          return overrides.pauseResponse ?? requestedOutcome('pause_requested', expectedRevision);
        },
        async resumeRun(runId, expectedRevision) {
          received.push({ kind: 'resume', runId, expectedRevision });
          return overrides.resumeResponse ?? controlOutcome('running', expectedRevision);
        },
        async forkRecoveryRun(runId, expectedRevision, idempotencyKey) {
          received.push({ kind: 'fork', runId, expectedRevision, idempotencyKey });
          return (
            overrides.forkResponse ?? forkOutcome(expectedRevision, idempotencyKey)
          );
        },
        async cancelRun(runId, expectedRevision) {
          received.push({ kind: 'cancel', runId, expectedRevision });
          return overrides.cancelResponse ?? requestedOutcome('cancel_requested', expectedRevision);
        },
        async reviewRun(runId, input) {
          received.push({ kind: 'review', runId, input });
          const status = input.action === 'approve' ? 'completed' : 'running';
          return overrides.reviewResponse ?? controlOutcome(status, input.expectedRevision);
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

function createClient(actions, config = runtimeConfig(), conversationId = 'conversation-1') {
  return createDesktopSessionRunControlOperationsV2(() => actions).bindOperation(
    config,
    conversationId,
  );
}

test('facade freezes five commands before exact session generation leases', async () => {
  const lifecycle = [];
  const received = [];
  const config = runtimeConfig();
  const operations = createDesktopSessionRunControlOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle),
  );
  const client = operations.bindOperation(config, 'conversation-1');
  const reviewInput = {
    action: 'request_changes',
    expectedRevision: 11,
    feedback: 'Add the missing evidence.',
  };
  const pending = [
    client.pauseRun('run-1', 7),
    client.resumeRun('run-1', 8),
    client.forkRecoveryRun('run-1', 9, 'desktop-recovery-fork:run-1:9'),
    client.cancelRun('run-1', 10),
    client.reviewRun('run-1', reviewInput),
  ];
  config.tenantId = 'mutated-tenant';
  reviewInput.feedback = 'mutated';
  const outcomes = await Promise.all(pending);

  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(client), true);
  const bindCalls = received.filter(({ kind }) => kind === 'bind');
  assert.equal(bindCalls.length, 5);
  for (const call of bindCalls) {
    assert.equal(call.config.tenantId, 'tenant-1');
    assert.equal(Object.isFrozen(call.config), true);
    assert.deepEqual(call.identity, {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      session_id: 'conversation-1',
    });
    assert.equal(Object.isFrozen(call.identity), true);
  }
  assert.equal(
    received.find(({ kind }) => kind === 'review').input.feedback,
    'Add the missing evidence.',
  );
  assert.equal(Object.isFrozen(received.find(({ kind }) => kind === 'review').input), true);
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request }) => request),
    Array.from({ length: 5 }, () => ({
      service: 'service:desktop-renderer.session-run-control-authority',
      version: '1.0.0',
      scope: {
        kind: 'session',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        session_id: 'conversation-1',
      },
    })),
  );
  assert.equal(lifecycle.filter(({ type }) => type === 'release').length, 5);
  for (const outcome of outcomes) {
    assert.equal(Object.isFrozen(outcome), true);
    assert.equal(Object.isFrozen(outcome.run), true);
    assert.equal(Object.isFrozen(outcome.run.authorization_snapshot), true);
  }
  assert.equal(Object.isFrozen(outcomes[2].source_run), true);
});

test('invalid config, identity and commands fail before lease acquisition', async () => {
  let acquisitions = 0;
  const actions = {
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  };
  assert.throws(
    () => createClient(actions, runtimeConfig({ tenantId: '' })),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_control_input_invalid',
  );
  assert.throws(
    () => createClient(actions, runtimeConfig(), ' conversation-1'),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_control_input_invalid',
  );

  const cases = [
    (client) => client.pauseRun('', 7),
    (client) => client.resumeRun('run-1', -1),
    (client) => client.cancelRun(' run-1', 10),
    (client) => client.forkRecoveryRun('run-1', 9, 'short'),
    (client) => client.forkRecoveryRun('run-1', 9, ' invalid-key'),
    (client) => client.reviewRun('run-1', { action: 'reject', expectedRevision: 11 }),
    (client) =>
      client.reviewRun('run-1', {
        action: 'approve',
        expectedRevision: 11,
        feedback: 'not allowed',
      }),
    (client) =>
      client.reviewRun('run-1', {
        action: 'request_changes',
        expectedRevision: 11,
        feedback: '   ',
      }),
  ];
  for (const invoke of cases) {
    await assert.rejects(
      invoke(createClient(actions)),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_control_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
});

test('response validation rejects identity, status, revision and JSON drift', async () => {
  const invalidControlResponses = [
    requestedOutcome('pause_requested', 7, { accepted: false }),
    requestedOutcome('paused', 7),
    requestedOutcome('pause_requested', 7, { run: run({ id: 'run-2', revision: 7 }) }),
    requestedOutcome('pause_requested', 7, {
      run: run({ conversation_id: 'conversation-2', revision: 7 }),
    }),
    requestedOutcome('pause_requested', 7, {
      run: run({ project_id: 'project-2', revision: 7 }),
    }),
    requestedOutcome('pause_requested', 7, { run: run({ revision: 8 }) }),
    requestedOutcome('pause_requested', 7, {
      run: run({ revision: 7, authorization_snapshot: undefined }),
    }),
    requestedOutcome('pause_requested', 7, {
      run: run({ revision: 7, authorization_snapshot: { cost: NaN } }),
    }),
  ];
  for (const pauseResponse of invalidControlResponses) {
    await assert.rejects(
      createClient(
        acceptedActions(serviceFixture([], { pauseResponse }), 'sha256:invalid-control'),
      ).pauseRun('run-1', 7),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_control_response_invalid',
    );
  }

  const resumeClient = createClient(
    acceptedActions(
      serviceFixture([], {
        resumeResponse: {
          accepted: true,
          status: 'restart_requested',
          run: run({ status: 'interrupted', revision: 8 }),
        },
      }),
      'sha256:restart-requested',
    ),
  );
  assert.equal((await resumeClient.resumeRun('run-1', 8)).status, 'restart_requested');

  const terminalClient = createClient(
    acceptedActions(
      serviceFixture([], {
        cancelResponse: controlOutcome('cancelled', 10),
        reviewResponse: controlOutcome('completed', 11),
      }),
      'sha256:terminal-outcomes',
    ),
  );
  assert.equal((await terminalClient.cancelRun('run-1', 10)).status, 'cancelled');
  assert.equal(
    (await terminalClient.reviewRun('run-1', { action: 'approve', expectedRevision: 11 }))
      .status,
    'completed',
  );

  const invalidTransitionCases = [
    [
      'resume',
      { resumeResponse: requestedOutcome('running', 8) },
      (client) => client.resumeRun('run-1', 8),
    ],
    [
      'resume',
      {
        resumeResponse: {
          accepted: true,
          status: 'restart_requested',
          run: run({ status: 'disconnected', revision: 8 }),
        },
      },
      (client) => client.resumeRun('run-1', 8),
    ],
    [
      'cancel',
      {
        cancelResponse: {
          ...controlOutcome('cancelled', 10),
          status: 'cancel_requested',
        },
      },
      (client) => client.cancelRun('run-1', 10),
    ],
    [
      'review',
      {
        reviewResponse: controlOutcome('completed', 10, {
          run: run({ status: 'completed', revision: 11 }),
        }),
      },
      (client) => client.reviewRun('run-1', { action: 'approve', expectedRevision: 11 }),
    ],
  ];
  for (const [, overrides, invoke] of invalidTransitionCases) {
    await assert.rejects(
      invoke(
        createClient(
          acceptedActions(serviceFixture([], overrides), 'sha256:invalid-transition'),
        ),
      ),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_control_response_invalid',
    );
  }

  const validFork = forkOutcome(9, 'desktop-recovery-fork:run-1:9');
  const invalidForkResponses = [
    { ...validFork, created: 'yes' },
    { ...validFork, source_run: run({ status: 'running', revision: 9 }) },
    { ...validFork, source_run: run({ status: 'disconnected', revision: 8 }) },
    { ...validFork, run: run({ status: 'running', revision: 0 }) },
    {
      ...validFork,
      run: run({
        id: 'recovery-run-1',
        conversation_id: 'conversation-2',
        status: 'running',
        revision: 0,
        idempotency_key: 'desktop-recovery-fork:run-1:9',
      }),
    },
    {
      ...validFork,
      run: run({
        id: 'recovery-run-1',
        status: 'running',
        revision: 0,
        idempotency_key: 'different-idempotency-key',
      }),
    },
    { ...validFork, status: 'paused' },
  ];
  for (const forkResponse of invalidForkResponses) {
    await assert.rejects(
      createClient(
        acceptedActions(serviceFixture([], { forkResponse }), 'sha256:invalid-fork'),
      ).forkRecoveryRun('run-1', 9, 'desktop-recovery-fork:run-1:9'),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_control_response_invalid',
    );
  }
});

test('invalid service, command drift and escaped authority fail closed', async () => {
  const unavailable = createDesktopSessionRunControlOperationsV2(() => null);
  await assert.rejects(
    unavailable.bindOperation(runtimeConfig(), 'conversation-1').pauseRun('run-1', 7),
    (error) =>
      error instanceof DesktopSessionRunControlAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  const rejectedClient = createClient({
    acquireServiceOperationLease: async () => ({
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_resolve_failed',
      runtimeCode: 'missing_service',
    }),
  });
  await assert.rejects(
    rejectedClient.pauseRun('run-1', 7),
    (error) =>
      error instanceof DesktopSessionRunControlAuthorityUnavailableErrorV2 &&
      error.runtimeCode === 'missing_service',
  );
  for (const service of [
    {},
    { bindOperation: () => ({}) },
    {
      bindOperation: () => ({
        pauseRun: async () => requestedOutcome('pause_requested', 7),
        resumeRun: async () => controlOutcome('running', 8),
        forkRecoveryRun: async () => forkOutcome(9, 'desktop-recovery-fork:run-1:9'),
        cancelRun: async () => controlOutcome('cancelled', 10),
        reviewRun: async () => controlOutcome('completed', 11),
        legacyFallback: () => undefined,
      }),
    },
  ]) {
    await assert.rejects(
      createClient(acceptedActions(service, 'sha256:invalid')).pauseRun('run-1', 7),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_control_service_invalid',
    );
  }

  let escaped;
  await withDesktopSessionRunControlAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    {
      kind: 'pause',
      config: runtimeConfig(),
      conversationId: 'conversation-1',
      runId: 'run-1',
      expectedRevision: 7,
    },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  await assert.rejects(
    escaped.pauseRun('run-1', 7),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_control_operation_released',
  );
  await assert.rejects(
    withDesktopSessionRunControlAuthorityOperationV2(
      acceptedActions(serviceFixture(), 'sha256:command-drift'),
      {
        kind: 'pause',
        config: runtimeConfig(),
        conversationId: 'conversation-1',
        runId: 'run-1',
        expectedRevision: 7,
      },
      (authority) => authority.pauseRun('run-1', 8),
    ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_control_input_invalid',
  );
});

test('operation error outranks release error and HMR pins each mutation generation', async () => {
  const releaseFailureActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) =>
        operation({
          bindOperation: () => ({
            pauseRun: async () => {
              throw new Error('run_control_operation_failed');
            },
            resumeRun: async () => controlOutcome('running', 8),
            forkRecoveryRun: async () =>
              forkOutcome(9, 'desktop-recovery-fork:run-1:9'),
            cancelRun: async () => controlOutcome('cancelled', 10),
            reviewRun: async () => controlOutcome('completed', 11),
          }),
        }),
      release: async () => {
        throw new Error('run_control_release_failed');
      },
    }),
  };
  await assert.rejects(
    createClient(releaseFailureActions).pauseRun('run-1', 7),
    /run_control_operation_failed/u,
  );

  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  let actions = acceptedActions(
    serviceFixture([], { pauseResponse: oldResponse }),
    'sha256:old',
    lifecycle,
  );
  const operations = createDesktopSessionRunControlOperationsV2(() => actions);
  const client = operations.bindOperation(runtimeConfig(), 'conversation-1');
  const oldPending = client.pauseRun('run-1', 7);
  actions = acceptedActions(
    serviceFixture([], {
      pauseResponse: requestedOutcome('pause_requested', 7, {
        run: run({ status: 'running', revision: 7, updated_at: 'new-generation' }),
      }),
    }),
    'sha256:new',
    lifecycle,
  );
  const next = await client.pauseRun('run-1', 7);
  resolveOld(
    requestedOutcome('pause_requested', 7, {
      run: run({ status: 'running', revision: 7, updated_at: 'old-generation' }),
    }),
  );
  const old = await oldPending;
  assert.equal(next.run.updated_at, 'new-generation');
  assert.equal(old.run.updated_at, 'old-generation');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:sha256:old', 'acquire:sha256:new', 'release:sha256:new', 'release:sha256:old'],
  );
});

test('only cloud cancellation accepts an unchanged queued request receipt', async () => {
  const response = { accepted: true, status: 'cancel_requested', run: run({ status: 'queued', revision: 8 }) };
  const actions = acceptedActions(serviceFixture([], { cancelResponse: response }), 'sha256:cancel', []);
  const cloudClient = createClient(actions, runtimeConfig({ mode: 'cloud' }));
  const outcome = await cloudClient.cancelRun('run-1', 8);
  assert.equal(outcome.status, 'cancel_requested');
  assert.equal(outcome.run.status, 'queued');
  const localClient = createClient(actions);
  await assert.rejects(localClient.cancelRun('run-1', 8));
});
