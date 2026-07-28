import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  AutomationRunOutcomeUnknownError,
  automationRunAttemptKey,
  createDesktopAutomationApi,
  settleAutomationRunAttempt,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/automations/automationClient.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const automationsPageSource = readFileSync(
  new URL('../src/features/automations/AutomationsPage.tsx', import.meta.url),
  'utf8',
);
const sidebarSource = readFileSync(
  new URL('../src/features/navigation/DesktopSidebar.tsx', import.meta.url),
  'utf8',
);

test('Automations is a visible first-class primary navigation destination', () => {
  const primaryItems = sidebarSource.match(/const primaryItems = \[[\s\S]*?\] as const;/u)?.[0] ?? '';
  assert.match(primaryItems, /id: 'automations'/u);
  assert.match(primaryItems, /labelKey: 'nav\.automations'/u);
});

test('App composes the narrow automation API and the page invokes guarded run-now', () => {
  assert.match(appSource, /createDesktopAutomationApi/u);
  assert.match(appSource, /api=\{automationApi\}/u);
  assert.match(automationsPageSource, /api\.runAutomation/u);
  assert.match(automationsPageSource, /expected_revision: job\.revision/u);
  assert.match(automationsPageSource, /onRun=\{\(\) => void runJob\(selectedJob\)\}/u);
  assert.match(automationsPageSource, /onClick=\{onRun\}/u);
});

test('automation run-now uses the scoped guarded contract without expanding DesktopApiClient', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return new Response(
      JSON.stringify({
        receipt_id: 'receipt-1',
        run_id: 'run-1',
        job_id: 'automation/1',
        status: 'queued',
        duplicate: false,
      }),
      { status: 202, headers: { 'content-type': 'application/json' } },
    );
  };

  const baseApi = {
    createAutomation: async () => {
      throw new Error('not used');
    },
    deleteAutomation: async () => {
      throw new Error('not used');
    },
    getAutomationCapabilities: async () => {
      throw new Error('not used');
    },
    listAutomations: async () => {
      throw new Error('not used');
    },
    listAutomationRuns: async () => {
      throw new Error('not used');
    },
    toggleAutomation: async () => {
      throw new Error('not used');
    },
    updateAutomation: async () => {
      throw new Error('not used');
    },
  };

  try {
    const api = createDesktopAutomationApi(baseApi, {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      localApiToken: 'launch-capability',
      mode: 'local',
      projectId: 'project/1',
    });
    const response = await api.runAutomation(
      'automation/1',
      {
        expected_revision: 7,
        idempotency_key: 'run-now-1',
        conversation_id: 'conversation-1',
      },
      'project/1',
    );

    assert.deepEqual(response, {
      receipt_id: 'receipt-1',
      run_id: 'run-1',
      job_id: 'automation/1',
      status: 'queued',
      duplicate: false,
    });
    assert.equal(
      calls[0]?.input,
      'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/automation%2F1/run',
    );
    assert.equal(calls[0]?.init?.method, 'POST');
    assert.equal(calls[0]?.init?.headers.get('Authorization'), 'Bearer authenticated-session');
    assert.equal(calls[0]?.init?.headers.get('X-Agistack-Launch'), 'launch-capability');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      expected_revision: 7,
      idempotency_key: 'run-now-1',
      conversation_id: 'conversation-1',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('automation run-now validates project, job, revision, and idempotency before fetch', async () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    throw new Error('unexpected fetch');
  };
  const baseApi = {};

  try {
    const api = createDesktopAutomationApi(baseApi, {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      mode: 'cloud',
    });
    await assert.rejects(
      api.runAutomation(
        '',
        { expected_revision: 0, idempotency_key: '' },
        '',
      ),
      /project id is required/u,
    );
    assert.equal(fetchCalls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('two confirmed run-now clicks use different idempotency keys', () => {
  const attempts = new Map();
  let sequence = 0;
  const createKey = () => `uuid-${++sequence}`;
  const input = {
    expected_revision: 7,
    conversation_id: 'conversation-1',
  };

  const first = automationRunAttemptKey(attempts, 'automation-1', input, createKey);
  settleAutomationRunAttempt(attempts, 'automation-1');
  const second = automationRunAttemptKey(attempts, 'automation-1', input, createKey);

  assert.equal(first, 'run-uuid-1');
  assert.equal(second, 'run-uuid-2');
  assert.notEqual(second, first);
});

test('an ambiguous run-now retry reuses its key until a definite result retires it', () => {
  const attempts = new Map();
  let sequence = 0;
  const createKey = () => `uuid-${++sequence}`;
  const input = {
    expected_revision: 7,
    conversation_id: 'conversation-1',
  };

  const first = automationRunAttemptKey(attempts, 'automation-1', input, createKey);
  settleAutomationRunAttempt(
    attempts,
    'automation-1',
    new AutomationRunOutcomeUnknownError(),
  );
  const ambiguousRetry = automationRunAttemptKey(
    attempts,
    'automation-1',
    input,
    createKey,
  );
  settleAutomationRunAttempt(attempts, 'automation-1');
  const nextExplicitRun = automationRunAttemptKey(
    attempts,
    'automation-1',
    input,
    createKey,
  );

  assert.equal(ambiguousRetry, first);
  assert.equal(nextExplicitRun, 'run-uuid-2');
});

test('a transport failure marks the run-now outcome unknown', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new TypeError('connection reset');
  };
  const baseApi = {};

  try {
    const api = createDesktopAutomationApi(baseApi, {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      mode: 'cloud',
    });
    await assert.rejects(
      api.runAutomation(
        'automation-1',
        { expected_revision: 1, idempotency_key: 'run-now-1' },
        'project-1',
      ),
      AutomationRunOutcomeUnknownError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a response body transport failure leaves the run-now outcome unknown', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    status: 202,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => {
      throw new Error('response stream reset');
    },
  });

  try {
    const api = createDesktopAutomationApi({}, {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      mode: 'cloud',
    });
    await assert.rejects(
      api.runAutomation(
        'automation-1',
        { expected_revision: 1, idempotency_key: 'run-now-1' },
        'project-1',
      ),
      AutomationRunOutcomeUnknownError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a malformed successful receipt leaves the run-now outcome unknown', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ status: 'queued' }), {
      status: 202,
      headers: { 'content-type': 'application/json' },
    });

  try {
    const api = createDesktopAutomationApi({}, {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      mode: 'cloud',
    });
    await assert.rejects(
      api.runAutomation(
        'automation-1',
        { expected_revision: 1, idempotency_key: 'run-now-1' },
        'project-1',
      ),
      AutomationRunOutcomeUnknownError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a server error leaves the run-now outcome unknown', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: 'execution state unavailable' }), {
      status: 500,
      headers: { 'content-type': 'application/json' },
    });

  try {
    const api = createDesktopAutomationApi({}, {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      mode: 'cloud',
    });
    await assert.rejects(
      api.runAutomation(
        'automation-1',
        { expected_revision: 1, idempotency_key: 'run-now-1' },
        'project-1',
      ),
      AutomationRunOutcomeUnknownError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('an explicit conflict is a definite run-now result', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: 'revision conflict' }), {
      status: 409,
      headers: { 'content-type': 'application/json' },
    });

  try {
    const api = createDesktopAutomationApi({}, {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      mode: 'cloud',
    });
    await assert.rejects(
      api.runAutomation(
        'automation-1',
        { expected_revision: 1, idempotency_key: 'run-now-1' },
        'project-1',
      ),
      (error) => {
        assert.equal(error.name, 'DesktopApiError');
        assert.equal(error.status, 409);
        assert.equal(error instanceof AutomationRunOutcomeUnknownError, false);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('retryable 408, 425, and 429 responses leave the run-now outcome unknown', async () => {
  const originalFetch = globalThis.fetch;

  try {
    for (const status of [408, 425, 429]) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify({ detail: `retryable ${status}` }), {
          status,
          headers: { 'content-type': 'application/json' },
        });
      const api = createDesktopAutomationApi({}, {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'http://127.0.0.1:8088',
        apiKey: 'authenticated-session',
        mode: 'cloud',
      });
      await assert.rejects(
        api.runAutomation(
          'automation-1',
          { expected_revision: 1, idempotency_key: 'run-now-1' },
          'project-1',
        ),
        AutomationRunOutcomeUnknownError,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a receipt for another automation leaves the run-now outcome unknown', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        receipt_id: 'receipt-1',
        run_id: 'run-1',
        job_id: 'automation-2',
        status: 'queued',
        duplicate: false,
      }),
      { status: 202, headers: { 'content-type': 'application/json' } },
    );

  try {
    const api = createDesktopAutomationApi({}, {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      mode: 'cloud',
    });
    await assert.rejects(
      api.runAutomation(
        'automation-1',
        { expected_revision: 1, idempotency_key: 'run-now-1' },
        'project-1',
      ),
      AutomationRunOutcomeUnknownError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a receipt with an invalid run status leaves the run-now outcome unknown', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        receipt_id: 'receipt-1',
        run_id: 'run-1',
        job_id: 'automation-1',
        status: 'accepted',
        duplicate: false,
      }),
      { status: 202, headers: { 'content-type': 'application/json' } },
    );

  try {
    const api = createDesktopAutomationApi({}, {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      mode: 'cloud',
    });
    await assert.rejects(
      api.runAutomation(
        'automation-1',
        { expected_revision: 1, idempotency_key: 'run-now-1' },
        'project-1',
      ),
      AutomationRunOutcomeUnknownError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
