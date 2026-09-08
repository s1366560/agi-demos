import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import {
  wireCases,
  nativeScope,
  projectScope,
  config,
  capability,
  json,
  response,
  operation,
} from './nativeKnowledgeProcessingFixtures.mjs';
const require = createRequire(import.meta.url);
const { createDesktopNativeKnowledgeProcessingHttpV2: create } = require(
  `${process.env.AGISTACK_KNOWLEDGE_HTTP_TEST_DIST ?? '/tmp/agistack-desktop-test-dist'}/src/plugins/desktopNativeKnowledgeProcessingHttpV2.js`,
);
const invoke = (a, name, options = { expectedScope: nativeScope }) =>
  (Object.hasOwn(wireCases.find((c) => c.name === name).request, 'command')
    ? a.executeProcessing
    : a.queryProcessing)(operation(name), options);
const install = (fn) => {
  const old = globalThis.fetch;
  globalThis.fetch = fn;
  return () => {
    globalThis.fetch = old;
  };
};

test('all eleven shared fixture operations use authenticated loopback transport and live context before/after', async () => {
  let current, requests;
  const restore = install(async (url, init = {}) => {
    requests.push({ url: String(url), init });
    assert.equal(new URL(String(url)).origin, config.apiBaseUrl);
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer identity');
    assert.equal(new Headers(init.headers).get('X-Agistack-Launch'), 'launch');
    assert.equal(init.credentials, 'omit');
    if (String(url).endsWith('/context'))
      return json({ contract_version: '1.0.0', scope: nativeScope });
    assert.equal(new URL(String(url)).pathname, current.path);
    assert.deepEqual(JSON.parse(init.body), current.request);
    return json(response(current.name));
  });
  try {
    const a = create(config, projectScope, () => capability);
    for (current of wireCases) {
      requests = [];
      const r = await invoke(a, current.name);
      assert.deepEqual(r, response(current.name));
      assert.equal(requests.length, 3);
      assert.ok(Object.isFrozen(r.result));
    }
  } finally {
    restore();
  }
});

for (const row of wireCases)
  test(`only exact capability token admits ${row.name}`, async () => {
    let count = 0;
    const restore = install(async () => {
      count++;
      throw Error('unexpected fetch');
    });
    try {
      for (const cap of [
        null,
        { ...capability, allowed_actions: [] },
        {
          ...capability,
          allowed_actions: ['view', 'list', 'processing-query', 'processing-command'],
        },
        {
          ...capability,
          allowed_actions: capability.allowed_actions.filter((x) => x !== row.name),
        },
        { ...capability, provenance: 'declared' },
        { ...capability, authority_source: 'cloud_service' },
        { ...capability, availability: 'unavailable' },
        { ...capability, extra: true },
      ]) {
        await assert.rejects(
          invoke(
            create(config, projectScope, () => cap),
            row.name,
          ),
          (e) => e.status === 501,
        );
      }
      await assert.rejects(invoke(create(config, projectScope), row.name), (e) => e.status === 501);
      assert.equal(count, 0);
    } finally {
      restore();
    }
  });

test('semantic and every explicit command require observed context; other queries can discover it', async () => {
  let count = 0;
  const restore = install(async () => {
    count++;
    return json({ contract_version: '1.0.0', scope: nativeScope });
  });
  try {
    const a = create(config, projectScope, () => capability);
    for (const name of [
      'semantic',
      ...wireCases.filter((c) => c.request.command).map((c) => c.name),
    ]) {
      await assert.rejects(
        invoke(a, name, {}),
        (e) => e.message === 'native_knowledge_expected_scope_required',
      );
    }
    assert.equal(count, 0);
    for (const scope of [
      { ...nativeScope, context_revision: 2 },
      { ...nativeScope, generation: 2 },
      { ...nativeScope, digest: 'different' },
    ]) {
      await assert.rejects(
        invoke(a, 'semantic', { expectedScope: scope }),
        (e) => e.status === 409,
      );
    }
    assert.equal(count, 3);
  } finally {
    restore();
  }
});

for (const stage of ['before', 'context', 'post', 'after'])
  test(`abort at ${stage} rejects late response without retry`, async () => {
    const abort = new AbortController();
    let calls = 0;
    if (stage === 'before') abort.abort();
    const restore = install(async (url) => {
      calls++;
      if (
        (stage === 'context' && calls === 1) ||
        (stage === 'post' && calls === 2) ||
        (stage === 'after' && calls === 3)
      )
        abort.abort();
      return json(
        String(url).endsWith('/context')
          ? { contract_version: '1.0.0', scope: nativeScope }
          : response('index_one'),
      );
    });
    try {
      await assert.rejects(
        invoke(
          create(config, projectScope, () => capability),
          'index_one',
          { expectedScope: nativeScope, signal: abort.signal },
        ),
        (e) => e.name === 'AbortError',
      );
      assert.equal(calls, { before: 0, context: 1, post: 2, after: 3 }[stage]);
    } finally {
      restore();
    }
  });

for (const field of [
  'tenant_id',
  'project_id',
  'context_revision',
  'profile_id',
  'generation',
  'digest',
])
  test(`late ${field} change is fenced by live context`, async () => {
    let calls = 0;
    const restore = install(async () => {
      calls++;
      if (calls === 2) return json(response('semantic'));
      return json({
        contract_version: '1.0.0',
        scope:
          calls === 3
            ? {
                ...nativeScope,
                [field]:
                  typeof nativeScope[field] === 'number' ? nativeScope[field] + 1 : 'changed',
              }
            : nativeScope,
      });
    });
    try {
      await assert.rejects(
        invoke(
          create(config, projectScope, () => capability),
          'semantic',
        ),
        (e) => e.status === 409,
      );
      assert.equal(calls, 3);
    } finally {
      restore();
    }
  });

for (const stage of [1, 2, 3])
  test(`capability revocation after network phase ${stage} rejects response`, async () => {
    let current = capability,
      calls = 0;
    const restore = install(async (url) => {
      calls++;
      if (calls === stage) current = { ...capability, allowed_actions: [] };
      return json(
        String(url).endsWith('/context')
          ? { contract_version: '1.0.0', scope: nativeScope }
          : response('index_one'),
      );
    });
    try {
      await assert.rejects(
        invoke(
          create(config, projectScope, () => current),
          'index_one',
        ),
        (e) => e.status === 501,
      );
      assert.equal(calls, stage);
    } finally {
      restore();
    }
  });

test('invalid mode, URL, configured scope, capability revision and unknown options fail closed', async () => {
  let calls = 0;
  const restore = install(async () => {
    calls++;
    return json({ contract_version: '1.0.0', scope: nativeScope });
  });
  try {
    for (const patch of [
      { mode: 'cloud' },
      { apiBaseUrl: 'https://cloud.test' },
      { apiBaseUrl: 'http://127.0.0.1:43117/private' },
      { tenantId: 'other' },
    ])
      await assert.rejects(
        invoke(
          create({ ...config, ...patch }, projectScope, () => capability),
          'configuration',
        ),
      );
    await assert.rejects(
      invoke(
        create(config, { ...projectScope, extra: true }, () => capability),
        'configuration',
      ),
    );
    await assert.rejects(
      invoke(
        create(config, projectScope, () => ({
          ...capability,
          scope: { ...capability.scope, project_id: 'other' },
        })),
        'configuration',
      ),
      (e) => e.status === 409,
    );
    await assert.rejects(
      invoke(
        create(config, projectScope, () => capability),
        'configuration',
        { extra: true },
      ),
      (e) => e.status === 422,
    );
    assert.equal(calls, 0);
    await assert.rejects(
      invoke(
        create(config, projectScope, () => ({
          ...capability,
          authority_revision: 2,
        })),
        'configuration',
      ),
      (e) => e.status === 409,
    );
    assert.equal(calls, 1);
  } finally {
    restore();
  }
});

test('transport errors are returned once and discovery succeeds without expected scope', async () => {
  let calls = 0;
  const restore = install(async (url) => {
    calls++;
    return String(url).endsWith('/context')
      ? json({ contract_version: '1.0.0', scope: nativeScope })
      : json(
          {
            error: {
              code: 'knowledge_embedding_provider_unavailable',
              message: 'unavailable',
            },
          },
          503,
        );
  });
  try {
    const a = create(config, projectScope, () => capability);
    await assert.rejects(invoke(a, 'configuration', {}), (e) => e.status === 503);
    assert.equal(calls, 2);
  } finally {
    restore();
  }
});
