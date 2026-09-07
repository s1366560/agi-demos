import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopSessionRunInputAuthorityUnavailableErrorV2,
  createDesktopSessionRunInputOperationsV2,
  withDesktopSessionRunInputAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopSessionRunInputAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46991',
    apiKey: 'run-input-session',
    localApiToken: 'run-input-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace/project-1',
    ...overrides,
  };
}

function conversation(overrides = {}) {
  return {
    id: 'conversation-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: 'workspace-1',
    user_id: 'user-1',
    title: 'Conversation one',
    status: 'active',
    message_count: 1,
    created_at: '2026-09-02T00:00:00Z',
    agent_config: {},
    ...overrides,
  };
}

function reference(overrides = {}) {
  return {
    type: 'code_range',
    snapshot_id: 'snapshot-1',
    environment_id: 'environment-1',
    path: 'src/main.ts',
    start_line: 8,
    end_line: 10,
    side: 'new',
    patch_digest: 'patch-1',
    ...overrides,
  };
}

function contextItem(overrides = {}) {
  return {
    kind: 'agent',
    resource_id: 'agent-1',
    label: 'Planner',
    metadata: { execution_slot: 'primary', revision: 2 },
    ...overrides,
  };
}

function createRequest(overrides = {}) {
  return {
    expectedRunRevision: 7,
    message: 'Review the focused change',
    messageId: 'message-1',
    idempotencyKey: 'run-input-key-1',
    delivery: 'queue_next',
    references: [reference()],
    contextItems: [contextItem()],
    ...overrides,
  };
}

function receipt(overrides = {}) {
  return {
    id: 'input-1',
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    expected_run_revision: 7,
    message_id: 'message-1',
    idempotency_key: 'run-input-key-1',
    delivery: 'queue_next',
    status: 'queued',
    sequence: 1,
    queue_position: 1,
    content: 'Review the focused change',
    references: [reference()],
    context_items: [contextItem()],
    applied_round: null,
    applied_at: null,
    injected_via: 'control_channel',
    dispatch_status: 'dispatched',
    dispatch_attempts: 1,
    dispatch_lease_expires_at: null,
    dispatch_error_code: null,
    promotion_idempotency_key: null,
    promoted_at: null,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:01Z',
    ...overrides,
  };
}

function acknowledgement(overrides = {}) {
  return {
    accepted: true,
    created: true,
    action: 'send_message',
    conversation_id: 'conversation-1',
    message_id: 'message-1',
    delivery_mode: 'queue_next',
    run_id: 'run-1',
    run_revision: 7,
    queue_position: 1,
    input: receipt(),
    ...overrides,
  };
}

function listing(overrides = {}) {
  return {
    run_id: 'run-1',
    run_revision: 7,
    inputs: [receipt()],
    total_count: 1,
    ...overrides,
  };
}

function promotion(overrides = {}) {
  return {
    accepted: true,
    created: true,
    action: 'start_plan_turn',
    input: receipt({
      status: 'promoted_to_plan',
      promotion_idempotency_key: 'promotion-key-1',
      promoted_at: '2026-09-02T00:00:02Z',
    }),
    conversation: {
      id: 'conversation-1',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: 'workspace-1',
      current_mode: 'plan',
    },
    source_run: {
      id: 'run-1',
      conversation_id: 'conversation-1',
      project_id: 'project-1',
      revision: 7,
    },
    ...overrides,
  };
}

function serviceFixture(received = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config, identity) {
      received.push({ kind: 'bind-operation', config, identity });
      return Object.freeze({
        async createRunInput(runId, request, signal) {
          received.push({ kind: 'create', runId, request, signal });
          if (overrides.createError) throw overrides.createError;
          return overrides.create ?? acknowledgement({
            run_id: runId,
            conversation_id: identity.session_id,
            input: receipt({ run_id: runId, conversation_id: identity.session_id }),
          });
        },
        async listRunInputs(runId, signal) {
          received.push({ kind: 'list', runId, signal });
          if (overrides.listError) throw overrides.listError;
          return overrides.list ?? listing({
            run_id: runId,
            inputs: [receipt({ run_id: runId, conversation_id: identity.session_id })],
          });
        },
        async promoteRunInput(runId, inputId, expectedRevision, idempotencyKey, signal) {
          received.push({
            kind: 'promote',
            runId,
            inputId,
            expectedRevision,
            idempotencyKey,
            signal,
          });
          if (overrides.promoteError) throw overrides.promoteError;
          return overrides.promote ?? promotion({
            input: receipt({
              id: inputId,
              run_id: runId,
              conversation_id: identity.session_id,
              status: 'promoted_to_plan',
              promotion_idempotency_key: idempotencyKey,
              promoted_at: '2026-09-02T00:00:02Z',
            }),
            conversation: {
              id: identity.session_id,
              tenant_id: identity.tenant_id,
              project_id: identity.project_id,
              workspace_id: identity.workspace_id,
              current_mode: 'plan',
            },
            source_run: {
              id: runId,
              conversation_id: identity.session_id,
              project_id: identity.project_id,
              revision: expectedRevision,
            },
          });
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
  return createDesktopSessionRunInputOperationsV2(() => actions);
}

test('create, list and promote freeze session scope and nested input before acquisition', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const session = conversation();
  const request = createRequest();
  const authority = operations(
    acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle),
  );

  const createdPending = authority.createRunInput({
    config,
    conversation: session,
    runId: 'run-1',
    request,
    signal: controller.signal,
  });
  const listedPending = authority.listRunInputs({
    config,
    conversation: session,
    runId: 'run-1',
    signal: controller.signal,
  });
  const promotedPending = authority.promoteRunInput({
    config,
    conversation: session,
    runId: 'run-1',
    inputId: 'input-1',
    expectedSourceRunRevision: 7,
    idempotencyKey: 'promotion-key-1',
    signal: controller.signal,
  });
  config.tenantId = 'mutated-tenant';
  session.id = 'mutated-conversation';
  request.references[0].path = 'mutated.ts';
  request.contextItems[0].metadata.revision = 99;

  const [created, listed, promoted] = await Promise.all([
    createdPending,
    listedPending,
    promotedPending,
  ]);
  assert.equal(created.input.references[0].path, 'src/main.ts');
  assert.equal(listed.inputs[0].conversation_id, 'conversation-1');
  assert.equal(promoted.conversation.id, 'conversation-1');
  assert.equal(Object.isFrozen(created), true);
  assert.equal(Object.isFrozen(created.input), true);
  assert.equal(Object.isFrozen(created.input.references), true);
  assert.equal(Object.isFrozen(created.input.context_items[0].metadata), true);
  assert.equal(Object.isFrozen(listed.inputs), true);
  assert.equal(Object.isFrozen(promoted.conversation), true);
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request: lease }) => lease),
    Array.from({ length: 3 }, () => ({
      service: 'service:desktop-renderer.session-run-input-authority',
      version: '1.0.0',
      scope: {
        kind: 'session',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        session_id: 'conversation-1',
      },
    })),
  );
  const binding = received.find(({ kind }) => kind === 'bind-operation');
  assert.equal(Object.isFrozen(binding.config), true);
  assert.equal(Object.isFrozen(binding.identity), true);
  assert.equal(binding.identity.workspace_id, 'workspace-1');
  const createdRequest = received.find(({ kind }) => kind === 'create').request;
  assert.equal(Object.isFrozen(createdRequest), true);
  assert.equal(createdRequest.references[0].path, 'src/main.ts');
  assert.equal(createdRequest.contextItems[0].metadata.revision, 2);
  assert.equal(
    received
      .filter(({ kind }) => kind === 'create' || kind === 'list' || kind === 'promote')
      .every(({ signal }) => signal === controller.signal),
    true,
  );
});

test('invalid identity, request and exact operation shape fail before lease acquisition', () => {
  let acquisitions = 0;
  const authority = operations({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  });
  const base = {
    config: runtimeConfig(),
    conversation: conversation(),
    runId: 'run-1',
  };
  const invalidCreateInputs = [
    { ...base, runId: ' run-1', request: createRequest() },
    { ...base, request: createRequest({ expectedRunRevision: 0 }) },
    { ...base, request: createRequest({ delivery: 'later' }) },
    {
      ...base,
      request: createRequest({ references: [reference(), reference()] }),
    },
    {
      ...base,
      request: createRequest({ contextItems: [contextItem(), contextItem()] }),
    },
    { ...base, request: createRequest(), signal: {} },
    { ...base, request: createRequest(), legacy: true },
  ];
  for (const input of invalidCreateInputs) {
    assert.throws(
      () => authority.createRunInput(input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_input_input_invalid',
    );
  }
  assert.throws(
    () =>
      authority.createRunInput({
        ...base,
        conversation: conversation({ tenant_id: 'tenant-2' }),
        request: createRequest(),
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_input_scope_mismatch',
  );
  assert.throws(
    () =>
      authority.promoteRunInput({
        ...base,
        inputId: 'input-1',
        expectedSourceRunRevision: 0,
        idempotencyKey: 'promotion-key-1',
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_input_input_invalid',
  );
  assert.equal(acquisitions, 0);
});

test('response validation rejects run, conversation, receipt and promotion identity drift', async () => {
  const createInput = {
    config: runtimeConfig(),
    conversation: conversation(),
    runId: 'run-1',
    request: createRequest(),
  };
  for (const create of [
    acknowledgement({ run_id: 'run-2' }),
    acknowledgement({ message_id: 'message-2' }),
    acknowledgement({ input: receipt({ idempotency_key: 'other-key' }) }),
  ]) {
    await assert.rejects(
      operations(acceptedActions(serviceFixture([], { create }), 'sha256:bad-create'))
        .createRunInput(createInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_input_response_invalid',
    );
  }
  for (const list of [
    listing({ run_id: 'run-2' }),
    listing({ total_count: 2 }),
    listing({ inputs: [receipt(), receipt()] }),
  ]) {
    await assert.rejects(
      operations(acceptedActions(serviceFixture([], { list }), 'sha256:bad-list'))
        .listRunInputs({
          config: runtimeConfig(),
          conversation: conversation(),
          runId: 'run-1',
        }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_input_response_invalid',
    );
  }
  for (const promote of [
    promotion({ conversation: { ...promotion().conversation, tenant_id: 'tenant-2' } }),
    promotion({ source_run: { ...promotion().source_run, revision: 8 } }),
    promotion({ input: receipt({ promotion_idempotency_key: 'other-key' }) }),
  ]) {
    await assert.rejects(
      operations(acceptedActions(serviceFixture([], { promote }), 'sha256:bad-promote'))
        .promoteRunInput({
          config: runtimeConfig(),
          conversation: conversation(),
          runId: 'run-1',
          inputId: 'input-1',
          expectedSourceRunRevision: 7,
          idempotencyKey: 'promotion-key-1',
        }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_input_response_invalid',
    );
  }
});

test('missing, rejected, malformed and escaped run-input authorities fail closed', async () => {
  const listInput = {
    config: runtimeConfig(),
    conversation: conversation(),
    runId: 'run-1',
  };
  assert.throws(
    () => operations(null).listRunInputs(listInput),
    (error) =>
      error instanceof DesktopSessionRunInputAuthorityUnavailableErrorV2 &&
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
      }).listRunInputs(listInput),
      (error) =>
        error instanceof DesktopSessionRunInputAuthorityUnavailableErrorV2 &&
        error.runtimeCode === runtimeCode,
    );
  }
  for (const service of [
    {},
    { bindOperation: () => ({}) },
    {
      bindOperation: () => ({
        createRunInput: async () => acknowledgement(),
        listRunInputs: async () => listing(),
        promoteRunInput: async () => promotion(),
        legacyFallback: () => undefined,
      }),
    },
  ]) {
    await assert.rejects(
      operations(acceptedActions(service, 'sha256:invalid-service')).listRunInputs(listInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_run_input_service_invalid',
    );
  }

  let escaped;
  await withDesktopSessionRunInputAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    { kind: 'list', ...listInput },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  assert.throws(
    () => escaped.listRunInputs('run-1'),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_run_input_operation_released',
  );
});

test('operation failure outranks release failure while successful cleanup failure surfaces', async () => {
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    runId: 'run-1',
  };
  let failureReleases = 0;
  await assert.rejects(
    operations({
      acquireServiceOperationLease: async () => ({
        status: 'accepted',
        digest: 'sha256:release-failure',
        useService: (operation) =>
          operation(serviceFixture([], { listError: new Error('list_failed') })),
        release: async () => {
          failureReleases += 1;
          throw new Error('release_failed');
        },
      }),
    }).listRunInputs(input),
    /list_failed/u,
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
          throw new Error('release_failed');
        },
      }),
    }).listRunInputs(input),
    /release_failed/u,
  );
  assert.equal(successReleases, 1);
});

test('HMR pins an in-flight run-input read and routes the next read to the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  let actions = acceptedActions(
    serviceFixture([], { list: oldResponse }),
    'sha256:old',
    lifecycle,
  );
  const authority = createDesktopSessionRunInputOperationsV2(() => actions);
  const input = {
    config: runtimeConfig(),
    conversation: conversation(),
    runId: 'run-1',
  };
  const oldPending = authority.listRunInputs(input);
  actions = acceptedActions(
    serviceFixture([], {
      list: listing({ inputs: [receipt({ id: 'input-new' })] }),
    }),
    'sha256:new',
    lifecycle,
  );
  const next = await authority.listRunInputs(input);
  resolveOld(listing({ inputs: [receipt({ id: 'input-old' })] }));
  const old = await oldPending;

  assert.equal(next.inputs[0].id, 'input-new');
  assert.equal(old.inputs[0].id, 'input-old');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:sha256:old', 'acquire:sha256:new', 'release:sha256:new', 'release:sha256:old'],
  );
});
