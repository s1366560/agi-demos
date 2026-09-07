import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { cases, nativeScope, projectScope, cloudResolution } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const {
  createDesktopProjectMemoriesHttpAuthorityV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopProjectMemoriesHttpProjectionV2.js');
const config = {
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'identity',
  localApiToken: 'launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'local',
};
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
const pathFor = (op) => {
  if (['sync_link', 'sync_push', 'sync_pull'].includes(op)) return op.replace('_', '-');
  if (['resolve_pull', 'resolve_push', 'resume_resolution', 'reconcile_resolution'].includes(op))
    return `sync-${op.replaceAll('_', '-')}`;
  if (
    [
      'cloud_conflict_context',
      'resolution',
      'resolution_by_key',
      'resolutions',
      'pending_resolutions',
      'reconciliation_context',
    ].includes(op)
  )
    return 'sync-cloud-query';
  return 'query';
};

test('all typed sync operations use only native context and existing native HTTP routes', async () => {
  const original = globalThis.fetch;
  let current, requests;
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    assert.equal(new URL(String(url)).origin, config.apiBaseUrl);
    assert.equal(new Headers(init.headers).get('X-Agistack-Launch'), 'launch');
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer identity');
    if (String(url).endsWith('/context'))
      return json({ contract_version: '1.0.0', scope: nativeScope });
    const [command, result] = current;
    assert.equal(new URL(String(url)).pathname, `/api/v1/knowledge/${pathFor(command.operation)}`);
    const body = JSON.parse(init.body);
    assert.deepEqual(body.scope, nativeScope);
    if (['resolve_pull', 'resolve_push'].includes(command.operation)) {
      assert.deepEqual(body.resolution, command.resolution);
      assert.equal(new Headers(init.headers).get('Idempotency-Key'), command.idempotency_key);
      assert.equal(Object.hasOwn(body, 'idempotency_key'), false);
    }
    assert.equal(Object.hasOwn(body, 'actor'), false);
    assert.equal(Object.hasOwn(body, 'url'), false);
    return json({ contract_version: '1.0.0', scope: nativeScope, result });
  };
  try {
    const authority = createDesktopProjectMemoriesHttpAuthorityV2(config, projectScope);
    for (current of cases) {
      requests = [];
      const response = await authority.executeSync(current[0], { expectedScope: nativeScope });
      assert.deepEqual(response.result, current[1]);
      assert.equal(requests.length, 2);
    }
  } finally {
    globalThis.fetch = original;
  }
});

test('native sync rejects cloud or non-loopback transport without a request', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => {
    throw Error('must not send');
  };
  try {
    const cloud = createDesktopProjectMemoriesHttpAuthorityV2(
      { ...config, mode: 'cloud', apiBaseUrl: 'https://cloud.test' },
      { ...projectScope, authority: 'cloud' },
    );
    await assert.rejects(
      cloud.executeSync({ operation: 'sync_push' }),
      (error) => error.status === 501,
    );
    const bad = createDesktopProjectMemoriesHttpAuthorityV2(
      { ...config, apiBaseUrl: 'https://cloud.test' },
      projectScope,
    );
    await assert.rejects(
      bad.executeSync({ operation: 'sync_push' }),
      (error) => error.status === 422,
    );
  } finally {
    globalThis.fetch = original;
  }
});

test('stale resolution context and abort after context discovery never send a mutation', async () => {
  const original = globalThis.fetch;
  const command = {
    operation: 'resolve_push',
    resolution: cloudResolution,
    idempotency_key: 'stable',
  };
  const authority = createDesktopProjectMemoriesHttpAuthorityV2(config, projectScope);
  try {
    let requests = 0;
    globalThis.fetch = async () => {
      requests++;
      return json({ contract_version: '1.0.0', scope: { ...nativeScope, context_revision: 8 } });
    };
    await assert.rejects(
      authority.executeSync(command, { expectedScope: nativeScope }),
      (error) => error.status === 409,
    );
    assert.equal(requests, 1);
    const abort = new AbortController();
    globalThis.fetch = async () => {
      requests++;
      abort.abort();
      return json({ contract_version: '1.0.0', scope: nativeScope });
    };
    await assert.rejects(
      authority.executeSync(command, { signal: abort.signal, expectedScope: nativeScope }),
      {
        name: 'AbortError',
      },
    );
    assert.equal(requests, 2);
  } finally {
    globalThis.fetch = original;
  }
});

test('unknown native write result preserves caller key and exact decision bytes for explicit retry', async () => {
  const original = globalThis.fetch;
  const [command, result] = cases.find(([c]) => c.operation === 'resolve_push');
  const bodies = [],
    keys = [];
  globalThis.fetch = async (url, init) => {
    if (String(url).endsWith('/context'))
      return json({ contract_version: '1.0.0', scope: nativeScope });
    bodies.push(init.body);
    keys.push(new Headers(init.headers).get('Idempotency-Key'));
    return bodies.length === 1
      ? json({ error: { code: 'knowledge_storage_error' } }, 500)
      : json({ contract_version: '1.0.0', scope: nativeScope, result });
  };
  try {
    const authority = createDesktopProjectMemoriesHttpAuthorityV2(config, projectScope);
    await assert.rejects(
      authority.executeSync(command, { expectedScope: nativeScope }),
      (error) => error.message === 'knowledge_storage_error',
    );
    assert.equal(bodies.length, 1);
    await authority.executeSync(command, { expectedScope: nativeScope });
    assert.equal(bodies[0], bodies[1]);
    assert.deepEqual(keys, [command.idempotency_key, command.idempotency_key]);
  } finally {
    globalThis.fetch = original;
  }
});

test('selected-state native commands require observed scope and reject every scope drift before mutation', async () => {
  const original = globalThis.fetch;
  const authority = createDesktopProjectMemoriesHttpAuthorityV2(config, projectScope);
  const selected = cases.filter(([c]) =>
    [
      'sync_link',
      'resolve_pull',
      'resolve_push',
      'resume_resolution',
      'reconcile_resolution',
    ].includes(c.operation),
  );
  try {
    let requests = 0;
    globalThis.fetch = async () => {
      requests++;
      throw Error('unexpected request');
    };
    for (const [command] of selected) {
      await assert.rejects(
        authority.executeSync(command),
        (error) =>
          error.message === 'native_knowledge_expected_scope_required' && error.status === 422,
      );
    }
    assert.equal(requests, 0);
    for (const [key, value] of Object.entries(nativeScope)) {
      globalThis.fetch = async (url) => {
        requests++;
        assert(String(url).endsWith('/context'));
        return json({
          contract_version: '1.0.0',
          scope: {
            ...nativeScope,
            [key]: typeof value === 'number' ? value + 1 : value + '-changed',
          },
        });
      };
      for (const [command] of selected) {
        await assert.rejects(
          authority.executeSync(command, { expectedScope: nativeScope }),
          (error) => error.status === 409,
        );
      }
    }
    assert.equal(requests, selected.length * 6);
  } finally {
    globalThis.fetch = original;
  }
});

test('abort or native scope replacement after a POST never returns an accepted resolution', async () => {
  const original = globalThis.fetch;
  const [command, result] = cases.find(([c]) => c.operation === 'resolve_push');
  const authority = createDesktopProjectMemoriesHttpAuthorityV2(config, projectScope);
  try {
    for (const mode of ['abort', 'replacement']) {
      const abort = new AbortController();
      let requests = 0;
      globalThis.fetch = async (url) => {
        requests++;
        if (String(url).endsWith('/context'))
          return json({ contract_version: '1.0.0', scope: nativeScope });
        if (mode === 'abort') abort.abort();
        return json({
          contract_version: '1.0.0',
          scope:
            mode === 'replacement'
              ? { ...nativeScope, generation: nativeScope.generation + 1 }
              : nativeScope,
          result,
        });
      };
      await assert.rejects(
        authority.executeSync(command, { expectedScope: nativeScope, signal: abort.signal }),
        (error) => (mode === 'abort' ? error.name === 'AbortError' : error.status === 409),
      );
      assert.equal(requests, 2);
    }
  } finally {
    globalThis.fetch = original;
  }
});
