import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient, DesktopApiError } = require(
  '/tmp/agistack-desktop-test-dist/src/api/client.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const helperSource = readFileSync(
  new URL('../sidecar/src/workspace_core_helper.rs', import.meta.url),
  'utf8',
);
const importerSource = readFileSync(
  new URL('../sidecar/src/workspace_core_legacy_import.rs', import.meta.url),
  'utf8',
);
const retirementSource = readFileSync(
  new URL('../sidecar/src/local_runtime/local_history_retirement.rs', import.meta.url),
  'utf8',
);

function localConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
    apiKey: 'sidecar-token',
    localApiToken: 'launch-token',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    ...overrides,
  };
}

function installBroker(invoke) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window');
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: { __MEMSTACK_DESKTOP__: { core: { invoke } } },
  });
  return () => {
    if (previous === undefined) delete globalThis.window;
    else Object.defineProperty(globalThis, 'window', previous);
  };
}

test('local conversation history reads cloud and never falls back to the sidecar', async () => {
  const fetches = [];
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    fetches.push({ input: String(input), init });
    return new Response(JSON.stringify({ leaked: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
  const restore = installBroker(async (command, args) => {
    calls.push({ command, args });
    return {
      status: 200,
      body: { items: [], total: 0, has_more: false, offset: 0, limit: 500, next_offset: null },
    };
  });
  try {
    const client = new DesktopApiClient(localConfig());
    const page = await client.listConversations('project-1', 'workspace-1');
    assert.equal(page.total, 0);
    assert.equal(fetches.length, 0);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].command, 'cloud_request');
    assert.equal(calls[0].args.request.method, 'GET');
    assert.match(calls[0].args.request.path, /^\/api\/v1\/agent\/conversations\?/u);
    assert.equal(JSON.stringify(calls).includes('sidecar-token'), false);
    await client.runAgentMessage('conversation-1', 'hello', 'message-1', 'project-1');
    assert.equal(fetches.length, 1);
    assert.equal(new URL(fetches[0].input).origin, 'http://127.0.0.1:8088');
    assert.equal(fetches[0].init.method, 'POST');
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test('cloud history failure stays visible and does not read the sidecar', async () => {
  const fetches = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    fetches.push(true);
    return new Response(JSON.stringify({ items: [{ id: 'local-fake' }] }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
  const restore = installBroker(async () => ({
    status: 503,
    body: { detail: 'cloud_unavailable' },
  }));
  try {
    const client = new DesktopApiClient(localConfig());
    await assert.rejects(client.getConversationMessages('conversation-1', 'project-1'), (error) => {
      assert.equal(error instanceof DesktopApiError, true);
      assert.equal(error.status, 503);
      assert.equal(error.message, 'cloud_unavailable');
      return true;
    });
    assert.equal(fetches.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
    restore();
  }
});

test('missing cloud broker does not invent local history', async () => {
  const fetches = [];
  const originalFetch = globalThis.fetch;
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window');
  delete globalThis.window;
  globalThis.fetch = async () => {
    fetches.push(true);
    return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const client = new DesktopApiClient(localConfig());
    await assert.rejects(
      client.getConversationMessages('conversation-1', 'project-1'),
      (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 503);
        assert.equal(error.payload.detail, 'cloud_history_unavailable');
        return true;
      },
    );
    assert.equal(fetches.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
    if (previous === undefined) delete globalThis.window;
    else Object.defineProperty(globalThis, 'window', previous);
  }
});

test('legacy workspace import no longer reads local history tables', () => {
  assert.match(helperSource, /stage_empty_workspace_history_snapshot/u);
  assert.doesNotMatch(helperSource, /stage_legacy_workspace_snapshot/u);
  assert.doesNotMatch(importerSource, /desktop_workspaces/u);
  assert.doesNotMatch(importerSource, /desktop_workspace_messages/u);
  assert.match(retirementSource, /upload_outbox/u);
  assert.match(retirementSource, /application_vault_records/u);
  assert.match(retirementSource, /desktop_custom_keep|PRESERVED_TABLES/u);
  const productionRetirement = retirementSource.split('#[cfg(test)]')[0];
  assert.doesNotMatch(productionRetirement, /remove_dir_all|std::fs::remove_dir/u);
  assert.match(productionRetirement, /BEGIN IMMEDIATE/u);
  assert.match(productionRetirement, /ROLLBACK/u);
});
