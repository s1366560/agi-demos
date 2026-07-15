import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DEFAULT_CONFIG, LOCAL_DEV_SERVER_PRESETS, mergeLocalRuntimeStatus } = require(
  '/tmp/agistack-desktop-test-dist/src/types.js'
);

test('Rust desktop backend is the default server preset with Python retained as fallback', () => {
  assert.deepEqual(LOCAL_DEV_SERVER_PRESETS[0], {
    id: 'agistack-rust',
    label: 'agi-stack desktop :8088',
    apiBaseUrl: 'http://127.0.0.1:8088',
  });
  assert.deepEqual(LOCAL_DEV_SERVER_PRESETS[1], {
    id: 'memstack-python',
    label: 'MemStack reference :8000',
    apiBaseUrl: 'http://127.0.0.1:8000',
  });
  assert.equal(DEFAULT_CONFIG.apiBaseUrl, 'http://127.0.0.1:8088');
});

test('local runtime status replaces the capability without restoring an LLM secret', () => {
  const merged = mergeLocalRuntimeStatus(
    {
      ...DEFAULT_CONFIG,
      apiKey: 'stale-cloud-token',
      localApiToken: 'stale-local-capability',
      llmApiKey: '',
    },
    {
      running: true,
      api_base_url: 'http://127.0.0.1:54321',
      api_token: 'fresh-local-capability',
      workspace_root: '/tmp/workspace',
      tool_count: 1,
      tools: ['bash'],
      config: {
        provider: 'mock',
        base_url: 'http://127.0.0.1:11434/v1',
        model: '',
        workspace_root: '/tmp/workspace',
      },
    }
  );

  assert.equal(merged.apiBaseUrl, 'http://127.0.0.1:54321');
  assert.equal(merged.apiKey, 'stale-cloud-token');
  assert.equal(merged.localApiToken, 'fresh-local-capability');
  assert.equal(merged.llmApiKey, '');
});
