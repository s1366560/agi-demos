import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient, DesktopApiError } = require(
  '/tmp/agistack-desktop-test-dist/src/api/client.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop sandbox upload imports bytes into the selected project', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ url: new URL(String(input)), init, body: JSON.parse(String(init?.body)) });
    return new Response(
      JSON.stringify({
        success: true,
        is_error: false,
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              path: '/workspace/input/evidence.txt',
              size_bytes: 4,
            }),
          },
        ],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'cloud-session',
      projectId: 'project-1',
    });
    const result = await client.uploadSandboxFile({
      name: 'evidence.txt',
      type: 'text/plain',
      size: 4,
      arrayBuffer: async () => Uint8Array.from([65, 66, 67, 68]).buffer,
    });

    assert.deepEqual(result, {
      filename: 'evidence.txt',
      sandbox_path: '/workspace/input/evidence.txt',
      mime_type: 'text/plain',
      size_bytes: 4,
    });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url.pathname, '/api/v1/projects/project-1/sandbox/execute');
    assert.equal(calls[0].init.method, 'POST');
    assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer cloud-session');
    assert.deepEqual(calls[0].body, {
      tool_name: 'import_file',
      arguments: {
        filename: 'evidence.txt',
        content_base64: 'QUJDRA==',
        destination: '/workspace/input',
        overwrite: true,
      },
      timeout: 60,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('desktop sandbox upload fails closed when the tool response has no authoritative path', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({ success: true, is_error: false, content: [{ type: 'text', text: '{}' }] }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'cloud-session',
      projectId: 'project-1',
    });
    await assert.rejects(
      client.uploadSandboxFile({
        name: 'evidence.txt',
        type: 'text/plain',
        size: 1,
        arrayBuffer: async () => Uint8Array.of(65).buffer,
      }),
      (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 502);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
