import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createSandboxRuntimeSurfaceClient,
  parseSandboxRuntimeCapabilitySnapshot,
  remoteDesktopReconnectDelay,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/sandbox/sandboxRuntimeSurfaceClient.js'
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const availableSnapshot = {
  service_version: '0.1.0',
  contract_version: 2,
  terminal_interactive: {
    availability: 'available',
    contract_version: 1,
    reason_code: null,
  },
  terminal_resume: {
    availability: 'unavailable',
    contract_version: 2,
    reason_code: 'terminal_session_v2_registry_unavailable',
  },
  files: {
    availability: 'available',
    contract_version: 1,
    reason_code: null,
  },
  kasm_vnc: {
    availability: 'available',
    contract_version: 1,
    reason_code: null,
  },
};

const localRuntimeSnapshot = {
  service_version: '0.1.0',
  contract_version: 2,
  terminal_interactive: {
    availability: 'available',
    contract_version: 1,
    reason_code: null,
  },
  terminal_resume: {
    availability: 'unavailable',
    contract_version: 2,
    reason_code: 'local_terminal_resume_unavailable',
  },
  files: {
    availability: 'available',
    contract_version: 1,
    reason_code: null,
  },
  kasm_vnc: {
    availability: 'not_applicable',
    contract_version: 1,
    reason_code: 'local_kasm_vnc_not_applicable',
  },
};

test('sandbox capability snapshot is exact, versioned, and fail closed', () => {
  assert.deepEqual(parseSandboxRuntimeCapabilitySnapshot(availableSnapshot), availableSnapshot);
  assert.equal(
    parseSandboxRuntimeCapabilitySnapshot({ ...availableSnapshot, inferred: true }),
    null
  );
  assert.equal(
    parseSandboxRuntimeCapabilitySnapshot({
      ...availableSnapshot,
      contract_version: 1,
    }),
    null
  );
  assert.equal(
    parseSandboxRuntimeCapabilitySnapshot({
      ...availableSnapshot,
      kasm_vnc: {
        availability: 'available',
        contract_version: 1,
        reason_code: 'available_but_has_reason',
      },
    }),
    null
  );
});

test('local runtime snapshot preserves native terminal and file authority without Kasm inference', () => {
  assert.deepEqual(
    parseSandboxRuntimeCapabilitySnapshot(localRuntimeSnapshot),
    localRuntimeSnapshot
  );
});

test('runtime client loads capabilities before opening an iframe session', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    if (String(input).endsWith('/sandbox/capabilities')) {
      return Response.json(availableSnapshot);
    }
    return Response.json({
      contract_version: 1,
      project_id: 'project/1',
      protocol: 'kasmvnc-1',
      proxy_url: '/api/v1/projects/project%2F1/sandbox/desktop/proxy/vnc.html',
      auth_mode: 'scoped_http_only_cookie',
    });
  };
  const client = createSandboxRuntimeSurfaceClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://api.memstack.test/root',
    apiKey: 'session-credential',
    projectId: 'project/1',
  });

  try {
    const snapshot = await client.loadCapabilities();
    const opened = await client.openRemoteDesktop(snapshot, { resolution: '1920x1080' });

    assert.equal(opened.status, 'ready');
    assert.equal(
      opened.value.frame_url,
      'https://api.memstack.test/api/v1/projects/project%2F1/sandbox/desktop/proxy/vnc.html'
    );
    assert.deepEqual(Object.keys(opened.value.descriptor).sort(), [
      'auth_mode',
      'contract_version',
      'project_id',
      'protocol',
      'proxy_url',
    ]);
    assert.equal(calls.length, 2);
    assert.equal(
      calls[0].url,
      'https://api.memstack.test/root/api/v1/projects/project%2F1/sandbox/capabilities'
    );
    assert.equal(calls[0].init.credentials, 'include');
    assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer session-credential');
    assert.equal(
      calls[1].url,
      'https://api.memstack.test/root/api/v1/projects/project%2F1/' +
        'sandbox/desktop/session?resolution=1920x1080'
    );
    assert.equal(calls[1].init.method, 'POST');
    assert.equal(calls[1].init.credentials, 'include');
    assert.doesNotMatch(calls[1].url, /token|password|credential/iu);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('runtime client does not probe remote desktop when capability is unavailable', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('must not probe');
  };
  const client = createSandboxRuntimeSurfaceClient({
    ...DEFAULT_CONFIG,
    projectId: 'project-1',
  });
  const snapshot = {
    ...availableSnapshot,
    kasm_vnc: {
      availability: 'unavailable',
      contract_version: 1,
      reason_code: 'kasm_runtime_unavailable',
    },
  };

  try {
    assert.deepEqual(await client.openRemoteDesktop(snapshot, { resolution: '1920x1080' }), {
      status: 'unavailable',
      reason_code: 'kasm_runtime_unavailable',
    });
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('runtime client rejects untrusted frame origins', async () => {
  const originalFetch = globalThis.fetch;
  const responses = [
    {
      ...availableSnapshot,
    },
    {
      contract_version: 1,
      project_id: 'project-1',
      protocol: 'kasmvnc-1',
      proxy_url: 'https://attacker.test/vnc.html',
      auth_mode: 'scoped_http_only_cookie',
    },
  ];
  globalThis.fetch = async () => Response.json(responses.shift());
  const client = createSandboxRuntimeSurfaceClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://api.memstack.test',
    projectId: 'project-1',
  });

  try {
    const snapshot = await client.loadCapabilities();
    await assert.rejects(
      client.openRemoteDesktop(snapshot, { resolution: '1920x1080' }),
      /sandbox remote desktop descriptor is invalid/
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('remote desktop reconnect delay is bounded exponential backoff', () => {
  assert.deepEqual(
    [0, 1, 2, 3, 4, 8, 20].map(remoteDesktopReconnectDelay),
    [1_000, 2_000, 4_000, 8_000, 15_000, 15_000, 15_000]
  );
});
