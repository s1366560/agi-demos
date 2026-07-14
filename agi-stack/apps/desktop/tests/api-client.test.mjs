import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  desktopApiCredential,
  desktopLaunchCapability,
  DesktopApiClient,
  DesktopApiError,
  isLegacyWorkspaceContextRouteMissing,
} = require(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('workspace context requests preserve the authoritative revision contract', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const context = {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      revision: calls.length - 1,
      updated_at: '2026-07-14T00:00:00Z',
    };
    return new Response(
      JSON.stringify(
        calls.length === 1
          ? { context, membership_role: 'owner' }
          : { context, changed: true },
      ),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
    });
    const current = await client.getWorkspaceContext();
    const switched = await client.switchWorkspaceContext(
      'tenant-1',
      'project-1',
      current.context.revision,
      'context-switch-1',
    );

    assert.equal(current.membership_role, 'owner');
    assert.equal(switched.context.revision, 1);
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method ?? 'GET']),
      [
        ['http://127.0.0.1:8088/api/v1/workspace-context', 'GET'],
        ['http://127.0.0.1:8088/api/v1/workspace-context/switch', 'POST'],
      ],
    );
    assert.deepEqual(JSON.parse(String(calls[1].init.body)), {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      expected_revision: 0,
      idempotency_key: 'context-switch-1',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workspace context compatibility fallback accepts only the legacy missing-route envelope', () => {
  assert.equal(
    isLegacyWorkspaceContextRouteMissing(
      new DesktopApiError('Not Found', 404, { detail: 'Not Found' }),
    ),
    true,
  );
  assert.equal(
    isLegacyWorkspaceContextRouteMissing(
      new DesktopApiError('unavailable', 404, {
        detail: { code: 'workspace_context_unavailable' },
      }),
    ),
    false,
  );
  assert.equal(
    isLegacyWorkspaceContextRouteMissing(
      new DesktopApiError('Not Found', 403, { detail: 'Not Found' }),
    ),
    false,
  );
});

test('respondToHitl sends the authenticated unified HITL payload', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({ success: true, message: 'Decision response received' }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'stale-cloud-token',
      localApiToken: 'local-session-token',
    });

    await client.respondToHitl({
      requestId: 'request-1',
      hitlType: 'decision',
      responseData: { decision: 'approve' },
    });

    assert.equal(calls.length, 1);
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/hitl/respond'
    );
    assert.equal(
      new Headers(calls[0]?.init?.headers).get('Authorization'),
      'Bearer stale-cloud-token'
    );
    assert.equal(
      new Headers(calls[0]?.init?.headers).get('X-Agistack-Launch'),
      'local-session-token'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      request_id: 'request-1',
      hitl_type: 'decision',
      response_data: { decision: 'approve' },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('authoritative run controls preserve run identity and expected revision', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        accepted: true,
        status: 'pause_requested',
        run: { id: 'run/1', status: 'running', revision: 7 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      localApiToken: 'launch-capability',
    });

    await client.pauseRun('run/1', 7);
    await client.resumeRun('run/1', 8);
    await client.cancelRun('run/1', 9);

    assert.deepEqual(
      calls.map((call) => [String(call.input), JSON.parse(String(call.init?.body))]),
      [
        [
          'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/pause',
          { expected_revision: 7 },
        ],
        [
          'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/resume',
          { expected_revision: 8 },
        ],
        [
          'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/cancel',
          { expected_revision: 9 },
        ],
      ]
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('run changes and structured inputs preserve snapshot, revision, and delivery contracts', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const url = String(input);
    if (url.includes('/changes?')) {
      return new Response(
        JSON.stringify({ id: 'snapshot-1', run_id: 'run/1', run_revision: 7, status: 'ready' }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    if (url.endsWith('/inputs') && init?.method !== 'POST') {
      return new Response(
        JSON.stringify({ run_id: 'run/1', run_revision: 7, inputs: [], total_count: 0 }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    if (url.endsWith('/promote-to-plan')) {
      return new Response(
        JSON.stringify({
          accepted: true,
          created: true,
          action: 'start_plan_turn',
          input: { id: 'input-1', status: 'promoted_to_plan' },
          conversation: { id: 'conversation-1', current_mode: 'plan' },
          source_run: { id: 'run/1', revision: 8, status: 'completed' },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    return new Response(
      JSON.stringify({
        accepted: true,
        created: true,
        action: 'send_message',
        conversation_id: 'conversation-1',
        message_id: 'message-1',
        delivery_mode: 'steer_now',
        run_id: 'run/1',
        run_revision: 7,
        queue_position: null,
        input: { id: 'input-1', status: 'pending_boundary' },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });
    await client.getRunChanges('run/1', 7);
    await client.createRunInput('run/1', {
      expectedRunRevision: 7,
      message: 'Keep the API stable',
      messageId: 'message-1',
      idempotencyKey: 'input-request-1',
      delivery: 'steer_now',
      references: [
        {
          type: 'code_range',
          snapshot_id: 'snapshot-1',
          environment_id: 'environment-1',
          path: 'src/lib.rs',
          start_line: 12,
          end_line: 12,
          side: 'new',
          patch_digest: 'patch-1',
        },
      ],
    });
    await client.listRunInputs('run/1');
    await client.promoteRunInput('input/1', 8, 'promote-input-1');

    assert.equal(
      String(calls[0].input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/changes?expected_revision=7'
    );
    assert.equal(
      String(calls[1].input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/inputs'
    );
    assert.deepEqual(JSON.parse(String(calls[1].init.body)), {
      expected_run_revision: 7,
      message: 'Keep the API stable',
      message_id: 'message-1',
      idempotency_key: 'input-request-1',
      delivery: 'steer_now',
      references: [
        {
          type: 'code_range',
          snapshot_id: 'snapshot-1',
          environment_id: 'environment-1',
          path: 'src/lib.rs',
          start_line: 12,
          end_line: 12,
          side: 'new',
          patch_digest: 'patch-1',
        },
      ],
    });
    assert.equal(
      String(calls[2].input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/inputs'
    );
    assert.equal(
      String(calls[3].input),
      'http://127.0.0.1:8088/api/v1/agent/run-inputs/input%2F1/promote-to-plan'
    );
    assert.deepEqual(JSON.parse(String(calls[3].init.body)), {
      expected_source_run_revision: 8,
      idempotency_key: 'promote-input-1',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('forkRecoveryRun binds one recovery fork to the source run revision', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        accepted: true,
        created: true,
        status: 'running',
        source_run: { id: 'run/1', status: 'disconnected', revision: 4 },
        run: { id: 'run/2', status: 'running', revision: 2 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    const result = await client.forkRecoveryRun(
      'run/1',
      4,
      'desktop-recovery-fork:run/1:4'
    );

    assert.equal(result.run.id, 'run/2');
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/fork'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      expected_revision: 4,
      idempotency_key: 'desktop-recovery-fork:run/1:4',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('startTerminal requests a terminal scoped to the authoritative run environment', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        success: true,
        session_id: 'terminal-1',
        run_id: 'run/1',
        run_revision: 7,
        conversation_id: 'conversation-1',
        project_id: 'project-1',
        environment_id: 'environment-1',
        resumable: false,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      projectId: 'project-1',
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.startTerminal('run/1', 7);

    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/projects/project-1/sandbox/terminal'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      run_id: 'run/1',
      expected_run_revision: 7,
    });
    assert.equal(
      client.terminalProxyUrl('terminal/1', 'bound/project'),
      'ws://127.0.0.1:8088/api/v1/projects/bound%2Fproject/sandbox/terminal/proxy/ws?session_id=terminal%2F1',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('automation reads and capability authority stay project scoped', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const url = String(input);
    if (url.endsWith('/runs?limit=50&offset=0')) {
      return new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (url.includes('/cron-jobs/automation%2F1')) {
      return new Response(
        JSON.stringify({ id: 'automation/1', project_id: 'project/1', name: 'Review' }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response(JSON.stringify({ items: [], total: 0 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      projectId: 'project/1',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
    });

    await client.listAutomations();
    await client.getAutomationCapabilities();
    await client.getAutomation('automation/1');
    await client.listAutomationRuns('automation/1');

    assert.deepEqual(
      calls.map((call) => String(call.input)),
      [
        'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs?include_disabled=true&limit=100&offset=0',
        'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/capabilities',
        'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/automation%2F1',
        'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/automation%2F1/runs?limit=50&offset=0',
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('listMyWork loads the project-scoped authoritative attention queue', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        project_id: 'project/1',
        total: 1,
        items: [
          {
            id: 'run-1',
            run_id: 'run-1',
            conversation_id: 'conversation-1',
            project_id: 'project/1',
            title: 'Review the run',
            capability_mode: 'code',
            group: 'ready_review',
            status: 'ready_review',
            required_action: 'review_result',
            revision: 4,
            permission_profile: 'workspace_write',
            created_at: '2026-07-13T00:00:00Z',
            updated_at: '2026-07-13T00:05:00Z',
          },
        ],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      localApiToken: 'launch-capability',
    });

    const result = await client.listMyWork('project/1');

    assert.equal(result.items[0]?.group, 'ready_review');
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/projects/project%2F1/my-work'
    );
    assert.equal(
      new Headers(calls[0]?.init?.headers).get('Authorization'),
      'Bearer authenticated-session'
    );
    assert.equal(
      new Headers(calls[0]?.init?.headers).get('X-Agistack-Launch'),
      'launch-capability'
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('reviewRun sends explicit approval or change feedback against one revision', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        accepted: true,
        status: 'completed',
        run: { id: 'run-1', status: 'completed', revision: 5 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.reviewRun('run-1', {
      action: 'request_changes',
      expectedRevision: 4,
      feedback: 'Add the missing verification evidence.',
    });

    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run-1/review'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      action: 'request_changes',
      expected_revision: 4,
      feedback: 'Add the missing verification evidence.',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('artifact review and delivery stay bound to immutable version revisions', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        accepted: true,
        status: 'approved',
        artifact_version: { id: 'artifact/version-2', status: 'approved', revision: 4 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.reviewArtifactVersion('artifact/version-2', {
      action: 'request_changes',
      expectedRevision: 3,
      runExpectedRevision: 8,
      feedback: 'Include the missing provenance.',
    });
    await client.deliverArtifactVersion('artifact/version-2', {
      expectedRevision: 4,
      idempotencyKey: 'artifact/version-2:4:deliver',
      destination: 'local_workspace',
    });

    assert.deepEqual(
      calls.map((call) => [String(call.input), JSON.parse(String(call.init?.body))]),
      [
        [
          'http://127.0.0.1:8088/api/v1/agent/artifact-versions/artifact%2Fversion-2/review',
          {
            action: 'request_changes',
            expected_revision: 3,
            run_expected_revision: 8,
            feedback: 'Include the missing provenance.',
          },
        ],
        [
          'http://127.0.0.1:8088/api/v1/agent/artifact-versions/artifact%2Fversion-2/deliver',
          {
            expected_revision: 4,
            idempotency_key: 'artifact/version-2:4:deliver',
            destination: 'local_workspace',
          },
        ],
      ]
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('desktop identity credentials stay separate from the Tauri launch capability', () => {
  assert.equal(
    desktopApiCredential({
      ...DEFAULT_CONFIG,
      apiKey: 'manual-local-key',
      localApiToken: '',
    }),
    'manual-local-key'
  );
  assert.equal(
    desktopApiCredential({
      ...DEFAULT_CONFIG,
      apiKey: 'manual-local-key',
      localApiToken: 'tauri-capability',
    }),
    'manual-local-key'
  );
  assert.equal(
    desktopLaunchCapability({
      ...DEFAULT_CONFIG,
      apiKey: 'authenticated-session',
      localApiToken: 'tauri-capability',
    }),
    'tauri-capability'
  );
});

test('agent WebSocket keeps launch and identity credentials in separate subprotocols', () => {
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
    apiKey: 'authenticated-session',
    localApiToken: 'tauri-capability',
  });

  const url = client.agentWsUrl('session-1');
  assert.equal(url, 'ws://127.0.0.1:8088/api/v1/agent/ws?session_id=session-1');
  assert.doesNotMatch(url, /tauri-capability/);
  assert.deepEqual(client.agentWsProtocols(), [
    'memstack.launch',
    'tauri-capability',
    'memstack.auth',
    'authenticated-session',
  ]);
});

test('local session bootstrap and context switch preserve the dual credential boundary', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(JSON.stringify({ success: true, context: {} }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const bootstrap = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: '',
      localApiToken: 'tauri-capability',
    });
    await bootstrap.createLocalSession(false);

    const authenticated = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      localApiToken: 'tauri-capability',
    });
    await authenticated.switchWorkspaceContext('orbital', 'agent-evals', 4, 'switch-5');
    await authenticated.signOut();

    const bootstrapHeaders = new Headers(calls[0]?.init?.headers);
    assert.equal(bootstrapHeaders.get('Authorization'), null);
    assert.equal(bootstrapHeaders.get('X-Agistack-Launch'), 'tauri-capability');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), { trusted_device: false });

    const switchHeaders = new Headers(calls[1]?.init?.headers);
    assert.equal(switchHeaders.get('Authorization'), 'Bearer authenticated-session');
    assert.equal(switchHeaders.get('X-Agistack-Launch'), 'tauri-capability');
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      tenant_id: 'orbital',
      project_id: 'agent-evals',
      expected_revision: 4,
      idempotency_key: 'switch-5',
    });
    assert.equal(
      String(calls[2]?.input),
      'http://127.0.0.1:8088/api/v1/auth/signout',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('trusted local resume sends only the launch capability and non-secret session reference', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    if (calls.length === 2) {
      return new Response(JSON.stringify({ detail: 'trusted local session unavailable' }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(
      JSON.stringify({
        access_token: 'rotated-bearer',
        token_type: 'bearer',
        must_change_password: false,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'stale-bearer-must-not-be-sent',
      localApiToken: 'current-launch-capability',
    });
    const resumed = await client.resumeLocalSession('local-session-1');
    const unavailable = await client.resumeLocalSession('revoked-session');

    assert.equal(resumed?.access_token, 'rotated-bearer');
    assert.equal(unavailable, null);
    const headers = new Headers(calls[0]?.init?.headers);
    assert.equal(headers.get('Authorization'), null);
    assert.equal(headers.get('X-Agistack-Launch'), 'current-launch-capability');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      session_id: 'local-session-1',
    });
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/auth/local-session/resume',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('createAgentConversation preserves the explicit Work or Code capability', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        id: 'conversation-1',
        project_id: 'project-1',
        agent_config: { capability_mode: 'code' },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.createAgentConversation('Implement review flow', 'project-1', 'code');

    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      project_id: 'project-1',
      title: 'Implement review flow',
      agent_config: {
        selected_agent_id: 'builtin:all-access',
        capability_mode: 'code',
      },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('updateAgentConversationMode can switch the active capability explicitly', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        id: 'conversation-1',
        project_id: 'project-1',
        agent_config: { capability_mode: 'work' },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.updateAgentConversationMode(
      'conversation-1',
      { capability_mode: 'work' },
      'project-1'
    );

    assert.equal(calls[0]?.init?.method, 'PATCH');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      capability_mode: 'work',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('switchPlanMode persists the explicit plan authority contract', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({ conversation_id: 'conversation-1', mode: 'plan' }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    const result = await client.switchPlanMode('conversation-1', 'plan');

    assert.deepEqual(result, { conversation_id: 'conversation-1', mode: 'plan' });
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/plan/mode'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      conversation_id: 'conversation-1',
      mode: 'plan',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('approvePlanAndStart uses one idempotent authority request', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        queued: true,
        created: true,
        conversation: { id: 'conversation-1', current_mode: 'build' },
        run: { id: 'run-1', status: 'queued', revision: 1 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    const result = await client.approvePlanAndStart({
      conversationId: 'conversation-1',
      projectId: 'project-1',
      planVersionId: 'plan-version-3',
      expectedPlanVersion: 3,
      permissionProfile: 'workspace_write',
      message: 'Execute the approved plan.',
      messageId: 'message-1',
      idempotencyKey: 'approval-1',
      environmentKind: 'worktree',
    });

    assert.equal(result.run.id, 'run-1');
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/plans/approve-and-start'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      conversation_id: 'conversation-1',
      project_id: 'project-1',
      plan_version_id: 'plan-version-3',
      expected_plan_version: 3,
      permission_profile: 'workspace_write',
      message: 'Execute the approved plan.',
      message_id: 'message-1',
      idempotency_key: 'approval-1',
      environment: { kind: 'worktree' },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('listAgentPlanTasks loads the structured plan for human review', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        conversation_id: 'conversation 1',
        tasks: [],
        total_count: 0,
        plan_version: {
          id: 'plan-version-4',
          conversation_id: 'conversation 1',
          version: 4,
          status: 'draft',
          tasks: [],
          created_at: '2026-07-13T08:00:00Z',
        },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });
    const result = await client.listAgentPlanTasks('conversation 1');

    assert.equal(result.total_count, 0);
    assert.equal(result.plan_version?.id, 'plan-version-4');
    assert.equal(result.plan_version?.version, 4);
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/plan/tasks/conversation%201'
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('management APIs keep runtime plugins distinct from MCP Apps', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        items: [
          {
            name: 'github',
            source: 'entrypoint',
            enabled: true,
            discovered: true,
            channel_types: [],
          },
        ],
        diagnostics: [],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
      tenantId: 'tenant 1',
    });
    const plugins = await client.listManagedPlugins();

    assert.equal(plugins[0].id, 'github');
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins'
    );
    assert.doesNotMatch(String(calls[0]?.input), /mcp\/apps/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
