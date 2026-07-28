import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
  createSandboxRuntimeClient,
  parseKasmProxySession,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/sandbox/sandboxRuntimeClient.js'
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const availableFiles = {
  availability: 'available',
  contract_version: 1,
  reason_code: null,
};

test('cloud terminal operations fail closed without canonical run authority', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('legacy project-only terminal routes must not be probed');
  };
  try {
    const client = createSandboxRuntimeClient(
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'https://api.memstack.test',
        mode: 'cloud',
        projectId: 'project-1',
      },
      {
        ...SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
        terminal_interactive: {
          availability: 'degraded',
          contract_version: 1,
          reason_code: 'terminal_interactive_canonical_run_authority_unavailable',
        },
        terminal_resume: {
          availability: 'unavailable',
          contract_version: 2,
          reason_code: 'terminal_session_v2_canonical_run_authority_unavailable',
        },
      }
    );

    assert.deepEqual(
      await client.createTerminalSession('project-1', 'run-1', 4),
      {
        status: 'unavailable',
        reason_code: 'terminal_session_v2_canonical_run_authority_unavailable',
      }
    );
    assert.deepEqual(
      await client.resumeTerminalSession('project-1', 'session-1', 'resume-token'),
      {
        status: 'unavailable',
        reason_code: 'terminal_session_v2_canonical_run_authority_unavailable',
      }
    );
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('cloud terminal operations use strict TerminalSessionV2 create and resume routes', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const expiresAt = new Date(Date.now() + 300_000).toISOString();
  const createdAt = new Date(Date.now() - 1_000).toISOString();
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    const body = JSON.parse(String(init?.body ?? '{}'));
    const isResume = String(input).endsWith('/sessions/session-1/resume');
    return new Response(
      JSON.stringify({
        contract_version: 2,
        session_id: isResume ? 'session-1' : 'session-created',
        resume_token: isResume ? body.resume_token : 'created-resume-token',
        project_id: 'project/1',
        conversation_id: 'conversation-1',
        run_id: 'run-1',
        run_revision: 4,
        environment_id: 'environment-1',
        cwd: '/workspace',
        created_at: createdAt,
        expires_at: expiresAt,
        resumable: true,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = createSandboxRuntimeClient(
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'https://api.memstack.test',
        apiKey: 'session-credential',
        mode: 'cloud',
        projectId: 'project/1',
      },
      {
        ...SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
        terminal_interactive: {
          availability: 'available',
          contract_version: 1,
          reason_code: null,
        },
        terminal_resume: {
          availability: 'available',
          contract_version: 2,
          reason_code: null,
        },
      }
    );

    const created = await client.createTerminalSession('project/1', 'run-1', 4);
    const resumed = await client.resumeTerminalSession(
      'project/1',
      'session-1',
      'resume-token'
    );

    assert.equal(created.status, 'ready');
    assert.equal(created.value.session_id, 'session-created');
    assert.equal(resumed.status, 'ready');
    assert.equal(resumed.value.resume_token, 'resume-token');
    assert.equal(
      calls[0].url,
      'https://api.memstack.test/api/v1/projects/project%2F1/sandbox/terminal/sessions'
    );
    assert.deepEqual(JSON.parse(calls[0].init.body), {
      run_id: 'run-1',
      expected_run_revision: 4,
    });
    assert.equal(
      calls[1].url,
      'https://api.memstack.test/api/v1/projects/project%2F1/sandbox/terminal/sessions/session-1/resume'
    );
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      resume_token: 'resume-token',
    });
    assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer session-credential');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sandbox file operations fail closed without a declared structured authority', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('unavailable routes must not be probed');
  };
  try {
    const client = createSandboxRuntimeClient(
      { ...DEFAULT_CONFIG, projectId: 'project-1' },
      SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE
    );
    assert.deepEqual(await client.listFiles({ path: '/workspace' }), {
      status: 'unavailable',
      reason_code: 'sandbox_file_api_unavailable',
    });
    assert.deepEqual(await client.readFile({ path: '/workspace/README.md' }), {
      status: 'unavailable',
      reason_code: 'sandbox_file_api_unavailable',
    });
    assert.deepEqual(await client.downloadFile({ path: '/workspace/report.pdf' }), {
      status: 'unavailable',
      reason_code: 'sandbox_file_api_unavailable',
    });
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sandbox files use distinct structured list, read, and download routes', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    if (url.includes('/download?')) {
      return new Response(new Uint8Array([1, 2, 3]), {
        status: 200,
        headers: {
          'content-disposition': 'attachment; filename=\"report.pdf\"',
          'content-length': '3',
          'content-type': 'application/pdf',
          'x-memstack-file-contract-version': '1',
          'x-memstack-file-authority': 'native_workspace',
          'x-memstack-file-isolation': 'not_applicable',
        },
      });
    }
    if (url.includes('/content?')) {
      return new Response(
        JSON.stringify({
          contract_version: 1,
          authority: 'native_workspace',
          isolation: 'not_applicable',
          path: '/workspace/README.md',
          encoding: 'utf-8',
          content: '# Ready',
          mime_type: 'text/markdown',
          size_bytes: 7,
          revision: 'file-r1',
          truncated: false,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    return new Response(
      JSON.stringify({
        contract_version: 1,
        authority: 'native_workspace',
        isolation: 'not_applicable',
        root: '/',
        path: '/workspace',
        entries: [
          {
            path: '/workspace/README.md',
            name: 'README.md',
            kind: 'file',
            size_bytes: 7,
            mime_type: 'text/markdown',
          },
        ],
        cursor: null,
        revision: 'files-r1',
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = createSandboxRuntimeClient(
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'https://api.memstack.test',
        apiKey: 'session-credential',
        projectId: 'project/1',
      },
      {
        ...SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
        files: availableFiles,
      }
    );
    const listed = await client.listFiles({ path: '/workspace', limit: 25 });
    const read = await client.readFile({ path: '/workspace/README.md', max_bytes: 1024 });
    const downloaded = await client.downloadFile({
      path: '/workspace/report.pdf',
      max_bytes: 1024,
    });

    assert.equal(listed.status, 'ready');
    assert.equal(listed.value.authority, 'native_workspace');
    assert.equal(listed.value.isolation, 'not_applicable');
    assert.equal(read.status, 'ready');
    assert.equal(read.value.authority, 'native_workspace');
    assert.equal(read.value.isolation, 'not_applicable');
    assert.equal(read.value.content, '# Ready');
    assert.equal(downloaded.status, 'ready');
    assert.equal(downloaded.value.authority, 'native_workspace');
    assert.equal(downloaded.value.isolation, 'not_applicable');
    assert.equal(downloaded.value.filename, 'report.pdf');
    assert.equal(downloaded.value.mime_type, 'application/pdf');
    assert.equal(downloaded.value.bytes.size, 3);
    assert.deepEqual(calls, [
      'https://api.memstack.test/api/v1/projects/project%2F1/sandbox/files?' +
        'path=%2Fworkspace&limit=25',
      'https://api.memstack.test/api/v1/projects/project%2F1/sandbox/files/content?' +
        'path=%2Fworkspace%2FREADME.md&max_bytes=1024',
      'https://api.memstack.test/api/v1/projects/project%2F1/sandbox/files/download?' +
        'path=%2Fworkspace%2Freport.pdf&max_bytes=1024',
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sandbox authority and isolation pairs fail closed across runtime modes', async () => {
  const originalFetch = globalThis.fetch;
  const responses = [
    {
      contract_version: 1,
      authority: 'sandbox',
      isolation: 'isolated',
      root: '/',
      path: '/workspace',
      entries: [],
      cursor: null,
      revision: 'files-cloud-r1',
    },
    {
      contract_version: 1,
      authority: 'native_workspace',
      isolation: 'isolated',
      root: '/',
      path: '/workspace',
      entries: [],
      cursor: null,
      revision: 'files-invalid-r1',
    },
    {
      contract_version: 1,
      authority: 'native_workspace',
      isolation: 'not_applicable',
      root: '/',
      path: '/workspace',
      entries: [],
      cursor: null,
      revision: 'files-local-r1',
    },
  ];
  globalThis.fetch = async () =>
    new Response(JSON.stringify(responses.shift()), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  const cloudClient = createSandboxRuntimeClient(
    {
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'https://api.memstack.test',
      mode: 'cloud',
      projectId: 'project-1',
    },
    {
      ...SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
      files: availableFiles,
    }
  );
  const localClient = createSandboxRuntimeClient(
    { ...DEFAULT_CONFIG, projectId: 'project-1' },
    {
      ...SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
      files: availableFiles,
    }
  );

  try {
    const cloud = await cloudClient.listFiles({ path: '/workspace' });
    assert.equal(cloud.status, 'ready');
    assert.equal(cloud.value.authority, 'sandbox');
    assert.equal(cloud.value.isolation, 'isolated');
    await assert.rejects(
      localClient.listFiles({ path: '/workspace' }),
      /sandbox file authority contract is invalid/
    );
    const local = await localClient.listFiles({ path: '/workspace' });
    assert.equal(local.status, 'ready');
    assert.equal(local.value.authority, 'native_workspace');
    assert.equal(local.value.isolation, 'not_applicable');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sandbox file paths and oversized downloads fail closed', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return new Response(new Uint8Array(2048), {
      status: 200,
      headers: { 'content-length': '2048' },
    });
  };
  const client = createSandboxRuntimeClient(
    { ...DEFAULT_CONFIG, projectId: 'project-1' },
    {
      ...SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
      files: availableFiles,
    }
  );

  try {
    await assert.rejects(
      client.readFile({ path: '/workspace/../etc/passwd' }),
      /sandbox file path is invalid/
    );
    assert.equal(calls, 0);
    await assert.rejects(
      client.downloadFile({ path: '/workspace/large.bin', max_bytes: 1024 }),
      /sandbox file exceeds the download limit/
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sandbox text reads enforce the actual encoded byte limit', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        contract_version: 1,
        authority: 'native_workspace',
        isolation: 'not_applicable',
        path: '/workspace/large.txt',
        encoding: 'utf-8',
        content: '界界',
        mime_type: 'text/plain',
        size_bytes: 2,
        revision: 'file-r2',
        truncated: false,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  const client = createSandboxRuntimeClient(
    { ...DEFAULT_CONFIG, projectId: 'project-1' },
    {
      ...SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
      files: availableFiles,
    }
  );

  try {
    await assert.rejects(
      client.readFile({ path: '/workspace/large.txt', max_bytes: 4 }),
      /sandbox file content contract is invalid/
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sandbox file payloads reject undeclared fields', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    Response.json({
      contract_version: 1,
      authority: 'native_workspace',
      isolation: 'not_applicable',
      root: '/',
      path: '/workspace',
      entries: [],
      cursor: null,
      revision: 'files-r1',
      credential: 'must-not-be-accepted',
    });
  const client = createSandboxRuntimeClient(
    { ...DEFAULT_CONFIG, projectId: 'project-1' },
    {
      ...SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
      files: availableFiles,
    }
  );

  try {
    await assert.rejects(
      client.listFiles({ path: '/workspace' }),
      /sandbox file listing contract is invalid/
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sandbox downloads prefer a bounded RFC 5987 filename', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(new Uint8Array([1]), {
      headers: {
        'content-disposition':
          'attachment; filename="download"; filename*=UTF-8\'\'report-%E6%B5%8B%E8%AF%95.pdf',
        'content-length': '1',
        'content-type': 'application/pdf',
        'x-memstack-file-contract-version': '1',
        'x-memstack-file-authority': 'native_workspace',
        'x-memstack-file-isolation': 'not_applicable',
      },
    });
  const client = createSandboxRuntimeClient(
    { ...DEFAULT_CONFIG, projectId: 'project-1' },
    {
      ...SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
      files: availableFiles,
    }
  );

  try {
    const result = await client.downloadFile({
      path: '/workspace/report.pdf',
      max_bytes: 1024,
    });
    assert.equal(result.status, 'ready');
    assert.equal(result.value.filename, 'report-测试.pdf');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('KasmVNC descriptors accept only scoped proxy-cookie authority without credentials', () => {
  assert.deepEqual(
    parseKasmProxySession(
      {
        contract_version: 1,
        project_id: 'project-1',
        protocol: 'kasmvnc-1',
        proxy_url: '/api/v1/projects/project-1/sandbox/desktop/proxy/vnc.html',
        auth_mode: 'scoped_http_only_cookie',
      },
      'project-1'
    ),
    {
      contract_version: 1,
      project_id: 'project-1',
      protocol: 'kasmvnc-1',
      proxy_url: '/api/v1/projects/project-1/sandbox/desktop/proxy/vnc.html',
      auth_mode: 'scoped_http_only_cookie',
    }
  );
  assert.equal(
    parseKasmProxySession(
      {
        contract_version: 1,
        project_id: 'project-1',
        protocol: 'kasmvnc-1',
        proxy_url: '/api/v1/projects/project-1/sandbox/desktop/proxy/vnc.html',
        auth_mode: 'scoped_http_only_cookie',
        password: 'must-never-reach-renderer',
      },
      'project-1'
    ),
    null
  );
  assert.equal(
    parseKasmProxySession(
      {
        contract_version: 1,
        project_id: 'other-project',
        protocol: 'kasmvnc-1',
        proxy_url: '/api/v1/projects/other-project/sandbox/desktop/proxy/vnc.html',
        auth_mode: 'scoped_http_only_cookie',
      },
      'project-1'
    ),
    null
  );
  assert.equal(
    parseKasmProxySession(
      {
        contract_version: 1,
        project_id: 'project-1',
        protocol: 'kasmvnc-1',
        proxy_url:
          '/api/v1/projects/project-1/sandbox/desktop/proxy/vnc.html?password=leak',
        auth_mode: 'scoped_http_only_cookie',
      },
      'project-1'
    ),
    null
  );
  assert.equal(
    parseKasmProxySession(
      {
        contract_version: 1,
        project_id: 'project-1',
        protocol: 'kasmvnc-1',
        proxy_url: '/api/v1/projects/project-1/sandbox/desktop/proxy/websockify',
        auth_mode: 'scoped_http_only_cookie',
      },
      'project-1'
    ),
    null
  );
});
