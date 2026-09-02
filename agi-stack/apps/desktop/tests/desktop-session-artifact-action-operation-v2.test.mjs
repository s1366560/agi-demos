import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopSessionArtifactActionAuthorityUnavailableErrorV2,
  createDesktopSessionArtifactActionOperationsV2,
  withDesktopSessionArtifactActionAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopSessionArtifactActionAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46852',
    apiKey: 'artifact-action-session',
    localApiToken: 'artifact-action-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace/project-1',
    ...overrides,
  };
}

function artifactVersion(overrides = {}) {
  return {
    id: 'artifact-version-2',
    artifact_id: 'artifact-1',
    source_artifact_id: 'source-artifact-1',
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    version: 2,
    status: 'approved',
    revision: 4,
    filename: 'report.md',
    mime_type: 'text/markdown',
    path: '/workspace/project-1/report.md',
    relative_path: 'report.md',
    bytes: 128,
    sources: [{ kind: 'file', path: 'source.md' }],
    checks: [{ kind: 'hash', status: 'passed' }],
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:01:00Z',
    approved_at: '2026-09-02T00:01:00Z',
    delivered_at: null,
    superseded_at: null,
    feedback: null,
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
    revision: 9,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:01:00Z',
    authorization_snapshot: {},
    ...overrides,
  };
}

function reviewOutcome(overrides = {}) {
  return {
    accepted: true,
    status: 'approved',
    artifact_version: artifactVersion(),
    run: null,
    ...overrides,
  };
}

function changesRequestedOutcome(overrides = {}) {
  return reviewOutcome({
    status: 'changes_requested',
    artifact_version: artifactVersion({
      status: 'superseded',
      revision: 4,
      approved_at: null,
      superseded_at: '2026-09-02T00:01:00Z',
      feedback: 'Include provenance.',
    }),
    run: run(),
    ...overrides,
  });
}

function deliveryOutcome(overrides = {}) {
  return {
    accepted: true,
    status: 'delivered',
    artifact_version: artifactVersion({
      status: 'delivered',
      revision: 5,
      delivered_at: '2026-09-02T00:02:00Z',
    }),
    delivery: {
      id: 'delivery-1',
      artifact_version_id: 'artifact-version-2',
      artifact_id: 'artifact-1',
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      destination: 'local_workspace',
      receipt: { artifact_version_id: 'artifact-version-2', bytes: 128 },
      idempotency_key: 'artifact-version-2:4:deliver',
      created_at: '2026-09-02T00:02:00Z',
    },
    ...overrides,
  };
}

function serviceFixture(received = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config) {
      received.push({ kind: 'bind', config });
      return Object.freeze({
        async reviewArtifactVersion(artifactVersionId, input) {
          received.push({
            kind: 'reviewArtifactVersion',
            artifactVersionId,
            input,
          });
          return (
            overrides.reviewResponse ??
            (input.action === 'request_changes' ? changesRequestedOutcome() : reviewOutcome())
          );
        },
        async deliverArtifactVersion(artifactVersionId, input) {
          received.push({
            kind: 'deliverArtifactVersion',
            artifactVersionId,
            input,
          });
          return overrides.deliveryResponse ?? deliveryOutcome();
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
  return createDesktopSessionArtifactActionOperationsV2(() => actions).bindOperation(
    config,
    conversationId,
  );
}

test('facade freezes review and delivery commands before exact session leases', async () => {
  const lifecycle = [];
  const received = [];
  const config = runtimeConfig();
  const operations = createDesktopSessionArtifactActionOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle),
  );
  const client = operations.bindOperation(config, 'conversation-1');
  const reviewInput = {
    action: 'request_changes',
    expectedRevision: 3,
    runExpectedRevision: 8,
    feedback: 'Include provenance.',
  };
  const deliveryInput = {
    expectedRevision: 4,
    idempotencyKey: 'artifact-version-2:4:deliver',
    destination: 'local_workspace',
  };
  const reviewPending = client.reviewArtifactVersion('artifact-version-2', reviewInput);
  const deliveryPending = client.deliverArtifactVersion('artifact-version-2', deliveryInput);
  config.tenantId = 'mutated-tenant';
  reviewInput.feedback = 'mutated';
  deliveryInput.destination = 'mutated';
  const [reviewed, delivered] = await Promise.all([reviewPending, deliveryPending]);

  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(client), true);
  const calls = received.filter(({ kind }) => kind !== 'bind');
  for (const call of calls) {
    assert.equal(Object.isFrozen(call.input), true);
  }
  assert.equal(calls[0].input.feedback, 'Include provenance.');
  assert.equal(calls[1].input.destination, 'local_workspace');
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request }) => request),
    [
      {
        service: 'service:desktop-renderer.session-artifact-action-authority',
        version: '1.0.0',
        scope: {
          kind: 'session',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          session_id: 'conversation-1',
        },
      },
      {
        service: 'service:desktop-renderer.session-artifact-action-authority',
        version: '1.0.0',
        scope: {
          kind: 'session',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          session_id: 'conversation-1',
        },
      },
    ],
  );
  assert.equal(lifecycle.filter(({ type }) => type === 'release').length, 2);
  for (const outcome of [reviewed, delivered]) {
    assert.equal(Object.isFrozen(outcome), true);
    assert.equal(Object.isFrozen(outcome.artifact_version), true);
    assert.equal(Object.isFrozen(outcome.artifact_version.sources), true);
  }
  assert.equal(Object.isFrozen(delivered.delivery), true);
  assert.equal(Object.isFrozen(delivered.delivery.receipt), true);
});

test('invalid config, identity and commands fail before lease acquisition', async () => {
  let acquisitions = 0;
  const actions = {
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  };
  const cases = [
    [
      runtimeConfig({ tenantId: '' }),
      'conversation-1',
      'review',
      'artifact-1',
      {
        action: 'approve',
        expectedRevision: 3,
      },
    ],
    [runtimeConfig(), '', 'review', 'artifact-1', { action: 'approve', expectedRevision: 3 }],
    [
      runtimeConfig(),
      ' conversation-1',
      'review',
      'artifact-1',
      {
        action: 'approve',
        expectedRevision: 3,
      },
    ],
    [
      runtimeConfig(),
      'conversation-1',
      'review',
      '',
      {
        action: 'approve',
        expectedRevision: 3,
      },
    ],
    [
      runtimeConfig(),
      'conversation-1',
      'review',
      'artifact-1',
      {
        action: 'reject',
        expectedRevision: 3,
      },
    ],
    [
      runtimeConfig(),
      'conversation-1',
      'review',
      'artifact-1',
      {
        action: 'approve',
        expectedRevision: -1,
      },
    ],
    [
      runtimeConfig(),
      'conversation-1',
      'review',
      'artifact-1',
      {
        action: 'approve',
        expectedRevision: 3,
        feedback: 'not allowed',
      },
    ],
    [
      runtimeConfig(),
      'conversation-1',
      'review',
      'artifact-1',
      {
        action: 'request_changes',
        expectedRevision: 3,
        feedback: 'missing run revision',
      },
    ],
    [
      runtimeConfig(),
      'conversation-1',
      'review',
      'artifact-1',
      {
        action: 'request_changes',
        expectedRevision: 3,
        runExpectedRevision: 8,
        feedback: '   ',
      },
    ],
    [
      runtimeConfig(),
      'conversation-1',
      'deliver',
      'artifact-1',
      {
        expectedRevision: 4,
        idempotencyKey: 'short',
        destination: 'local_workspace',
      },
    ],
    [
      runtimeConfig(),
      'conversation-1',
      'deliver',
      'artifact-1',
      {
        expectedRevision: 4,
        idempotencyKey: ' valid-key-1',
        destination: 'local_workspace',
      },
    ],
    [
      runtimeConfig(),
      'conversation-1',
      'deliver',
      'artifact-1',
      {
        expectedRevision: 4,
        idempotencyKey: 'valid-key-1',
        destination: ' ',
      },
    ],
  ];

  for (const [config, conversationId, kind, artifactVersionId, input] of cases) {
    const operations = createDesktopSessionArtifactActionOperationsV2(() => actions);
    let client;
    try {
      client = operations.bindOperation(config, conversationId);
    } catch (error) {
      assert.equal(error instanceof RuntimeV2Error, true);
      assert.equal(error.code, 'desktop_session_artifact_action_input_invalid');
      continue;
    }
    await assert.rejects(
      kind === 'review'
        ? client.reviewArtifactVersion(artifactVersionId, input)
        : client.deliverArtifactVersion(artifactVersionId, input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_artifact_action_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
});

test('response validation rejects cross-session, revision and receipt drift', async () => {
  const invalidResponses = [
    ['review', { reviewResponse: reviewOutcome({ accepted: false }) }],
    ['review', { reviewResponse: reviewOutcome({ status: 'changes_requested' }) }],
    [
      'review',
      {
        reviewResponse: reviewOutcome({
          artifact_version: artifactVersion({ id: 'artifact-other' }),
        }),
      },
    ],
    [
      'review',
      {
        reviewResponse: reviewOutcome({
          artifact_version: artifactVersion({
            conversation_id: 'conversation-2',
          }),
        }),
      },
    ],
    [
      'review',
      {
        reviewResponse: reviewOutcome({
          artifact_version: artifactVersion({ revision: 7 }),
        }),
      },
    ],
    [
      'review',
      {
        reviewResponse: reviewOutcome({
          run: run({ conversation_id: 'conversation-2' }),
        }),
      },
    ],
    [
      'review',
      {
        reviewResponse: reviewOutcome({
          run: run({ project_id: 'project-2' }),
        }),
      },
    ],
    [
      'deliver',
      {
        deliveryResponse: deliveryOutcome({ status: 'accepted' }),
      },
    ],
    [
      'deliver',
      {
        deliveryResponse: deliveryOutcome({
          artifact_version: artifactVersion({
            status: 'delivered',
            revision: 3,
          }),
        }),
      },
    ],
    [
      'deliver',
      {
        deliveryResponse: deliveryOutcome({
          delivery: {
            ...deliveryOutcome().delivery,
            conversation_id: 'conversation-2',
          },
        }),
      },
    ],
    [
      'deliver',
      {
        deliveryResponse: deliveryOutcome({
          delivery: {
            ...deliveryOutcome().delivery,
            artifact_version_id: 'artifact-other',
          },
        }),
      },
    ],
    [
      'deliver',
      {
        deliveryResponse: deliveryOutcome({
          delivery: {
            ...deliveryOutcome().delivery,
            idempotency_key: 'different-idempotency-key',
          },
        }),
      },
    ],
    [
      'deliver',
      {
        deliveryResponse: deliveryOutcome({
          delivery: {
            ...deliveryOutcome().delivery,
            destination: 'remote_workspace',
          },
        }),
      },
    ],
    [
      'deliver',
      {
        deliveryResponse: deliveryOutcome({
          delivery: { ...deliveryOutcome().delivery, receipt: undefined },
        }),
      },
    ],
  ];

  for (const [kind, overrides] of invalidResponses) {
    const client = createClient(
      acceptedActions(serviceFixture([], overrides), 'sha256:invalid-response'),
    );
    await assert.rejects(
      kind === 'review'
        ? client.reviewArtifactVersion('artifact-version-2', {
            action: 'approve',
            expectedRevision: 3,
          })
        : client.deliverArtifactVersion('artifact-version-2', {
            expectedRevision: 4,
            idempotencyKey: 'artifact-version-2:4:deliver',
            destination: 'local_workspace',
          }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_artifact_action_response_invalid',
    );
  }
});

test('missing service, invalid shape and escaped authority fail closed', async () => {
  const unavailable = createDesktopSessionArtifactActionOperationsV2(() => null);
  const unavailableClient = unavailable.bindOperation(runtimeConfig(), 'conversation-1');
  await assert.rejects(
    unavailableClient.reviewArtifactVersion('artifact-version-2', {
      action: 'approve',
      expectedRevision: 3,
    }),
    (error) =>
      error instanceof DesktopSessionArtifactActionAuthorityUnavailableErrorV2 &&
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
    rejectedClient.reviewArtifactVersion('artifact-version-2', {
      action: 'approve',
      expectedRevision: 3,
    }),
    (error) =>
      error instanceof DesktopSessionArtifactActionAuthorityUnavailableErrorV2 &&
      error.runtimeCode === 'missing_service',
  );
  for (const service of [
    {},
    { bindOperation: () => ({}) },
    {
      bindOperation: () => ({
        reviewArtifactVersion: async () => reviewOutcome(),
        deliverArtifactVersion: async () => deliveryOutcome(),
        legacyFallback: () => undefined,
      }),
    },
  ]) {
    const invalid = createClient(acceptedActions(service, 'sha256:invalid'));
    await assert.rejects(
      invalid.reviewArtifactVersion('artifact-version-2', {
        action: 'approve',
        expectedRevision: 3,
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_session_artifact_action_service_invalid',
    );
  }

  let escaped;
  await withDesktopSessionArtifactActionAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    {
      kind: 'review',
      config: runtimeConfig(),
      conversationId: 'conversation-1',
      artifactVersionId: 'artifact-version-2',
      input: { action: 'approve', expectedRevision: 3 },
    },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  await assert.rejects(
    escaped.reviewArtifactVersion('artifact-version-2', {
      action: 'approve',
      expectedRevision: 3,
    }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_session_artifact_action_operation_released',
  );
});

test('operation error outranks release error and HMR pins each action generation', async () => {
  const releaseFailureActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) =>
        operation({
          bindOperation: () => ({
            reviewArtifactVersion: async () => {
              throw new Error('artifact_action_operation_failed');
            },
            deliverArtifactVersion: async () => deliveryOutcome(),
          }),
        }),
      release: async () => {
        throw new Error('artifact_action_release_failed');
      },
    }),
  };
  await assert.rejects(
    createClient(releaseFailureActions).reviewArtifactVersion('artifact-version-2', {
      action: 'approve',
      expectedRevision: 3,
    }),
    /artifact_action_operation_failed/u,
  );

  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const oldService = serviceFixture([], { reviewResponse: oldResponse });
  let actions = acceptedActions(oldService, 'sha256:old', lifecycle);
  const operations = createDesktopSessionArtifactActionOperationsV2(() => actions);
  const client = operations.bindOperation(runtimeConfig(), 'conversation-1');
  const oldPending = client.reviewArtifactVersion('artifact-version-2', {
    action: 'approve',
    expectedRevision: 3,
  });
  actions = acceptedActions(
    serviceFixture([], {
      reviewResponse: reviewOutcome({
        artifact_version: artifactVersion({ updated_at: 'new-generation' }),
      }),
    }),
    'sha256:new',
    lifecycle,
  );
  const next = await client.reviewArtifactVersion('artifact-version-2', {
    action: 'approve',
    expectedRevision: 3,
  });
  resolveOld(
    reviewOutcome({
      artifact_version: artifactVersion({ updated_at: 'old-generation' }),
    }),
  );
  const old = await oldPending;
  assert.equal(next.artifact_version.updated_at, 'new-generation');
  assert.equal(old.artifact_version.updated_at, 'old-generation');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:sha256:old', 'acquire:sha256:new', 'release:sha256:new', 'release:sha256:old'],
  );
});
