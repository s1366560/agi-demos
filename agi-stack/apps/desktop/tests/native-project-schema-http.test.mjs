import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  require,
  dist,
  scope,
  actor,
  options,
  projectScope,
  config,
  document,
  change,
  receipt,
  envelope,
  capability,
  json,
  install,
  observation,
} from './nativeProjectSchemaFixtures.mjs';
const {
  createDesktopNativeProjectSchemaHttpV2: create,
  observeDesktopNativeProjectSchemaCapabilitiesV2: observe,
} = require(`${dist}/src/plugins/desktopNativeProjectSchemaHttpV2.js`);
const { requestNativeProjectSchemaJsonV2: request } = require(
  `${dist}/src/plugins/desktopNativeProjectSchemaTransportV2.js`,
);
const { MAX_SCHEMA_RESPONSE_BYTES: MAX } = require(
  `${dist}/src/features/project-administration/nativeProjectSchemaSchemaGenerated.js`,
);
const cases = [
  { method: 'read', command: null, result: { document: null } },
  {
    method: 'bootstrap',
    command: { change_id: change, expected_revision: 0, document },
    result: { receipt },
  },
  {
    method: 'replace',
    command: {
      change_id: change,
      expected_revision: 1,
      document: { ...document, revision: 2 },
    },
    result: {
      receipt: {
        ...receipt,
        sequence: 2,
        document: { ...document, revision: 2 },
      },
    },
  },
  { method: 'receipt', command: { change_id: change }, result: { receipt } },
  {
    method: 'history',
    command: { after_revision: 0, limit: 1 },
    result: {
      schema_id: document.schema_id,
      after_revision: 0,
      upper_revision: 1,
      next_after_revision: 1,
      has_more: false,
      items: [receipt],
    },
  },
];
const invoke = (client, row, opts = options) =>
  row.command === null ? client[row.method](opts) : client[row.method](row.command, opts);
for (const row of cases)
  test(`schema ${row.method} uses fixed POST body, native credentials and observations before/after`, async () => {
    const seen = [];
    let guards = 0;
    const restore = install(async (url, init) => {
      seen.push(new URL(String(url)).pathname);
      const headers = new Headers(init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer identity');
      assert.equal(headers.get('X-Agistack-Launch'), 'launch');
      assert.equal(headers.get('X-Expected-Revision'), null);
      assert.equal(headers.get('Idempotency-Key'), null);
      assert.equal(init.redirect, 'error');
      assert.equal(init.credentials, 'omit');
      const observed = observation(url);
      if (observed) return observed;
      assert.equal(init.method, 'POST');
      assert.equal(seen.at(-1), `/api/v1/knowledge/schema/${row.method}`);
      assert.deepEqual(JSON.parse(init.body), { scope, ...row.command });
      return json(envelope(`schema_${row.method}`, row.result));
    });
    try {
      const value = await invoke(
        create(
          config,
          projectScope,
          () => capability,
          () => {
            guards++;
          },
        ),
        row,
      );
      assert.deepEqual(value.result, row.result);
      assert.ok(Object.isFrozen(value.result));
      assert.equal(seen.length, 5);
      assert.ok(guards >= 5);
    } finally {
      restore();
    }
  });
test('schema authority cannot be constructed without both live callbacks; missing or forged capability performs no request', async () => {
  assert.throws(() => create(config, projectScope));
  assert.throws(() => create(config, projectScope, () => capability));
  let count = 0;
  const restore = install(async () => {
    count++;
    throw Error('unexpected request');
  });
  try {
    for (const cap of [
      null,
      { ...capability, authority: 'cloud' },
      {
        ...capability,
        result: { ...capability.result, provenance: 'declared' },
      },
      {
        ...capability,
        result: {
          ...capability.result,
          allowed_actions: [],
          availability: 'unavailable',
        },
      },
      { ...capability, actor_id: 'foreign' },
    ])
      await assert.rejects(
        create(
          config,
          projectScope,
          () => cap,
          () => {},
        ).read(options),
      );
    assert.equal(count, 0);
  } finally {
    restore();
  }
});
test('command and expected scope remain frozen across an asynchronous preflight', async () => {
  const command = structuredClone(cases[1].command),
    opts = structuredClone(options);
  let release;
  const paused = new Promise((resolve) => {
    release = resolve;
  });
  let count = 0,
    body;
  const restore = install(async (url, init) => {
    if (count++ === 0) await paused;
    const observed = observation(url);
    if (observed) return observed;
    body = JSON.parse(init.body);
    return json(envelope('schema_bootstrap', { receipt }));
  });
  try {
    const pending = create(
      config,
      projectScope,
      () => capability,
      () => {},
    ).bootstrap(command, opts);
    command.document.revision = 9;
    command.expected_revision = 8;
    opts.expectedScope.generation = 9;
    release();
    await pending;
    assert.equal(body.expected_revision, 0);
    assert.equal(body.document.revision, 1);
    assert.equal(body.scope.generation, 1);
  } finally {
    restore();
  }
});
test('capability discovery observes actor and exact scope without opening schema actions', async () => {
  const closed = {
    ...capability,
    result: {
      ...capability.result,
      availability: 'unavailable',
      allowed_actions: [],
    },
  };
  let calls = 0;
  const restore = install(async (url, init) => {
    calls++;
    const observed = observation(url);
    if (observed) return observed;
    assert.equal(init.method, 'GET');
    assert.ok(String(url).endsWith('/schema/capabilities'));
    return json(closed);
  });
  try {
    assert.deepEqual(await observe(config, projectScope, options, () => {}), closed);
    assert.equal(calls, 5);
  } finally {
    restore();
  }
});
test('late mutation response after lease invalidation is discarded with no automatic retry', async () => {
  let active = true,
    mutations = 0;
  const restore = install(async (url) => {
    const observed = observation(url);
    if (observed) return observed;
    mutations++;
    active = false;
    return json(envelope('schema_bootstrap', { receipt }));
  });
  try {
    await assert.rejects(
      create(
        config,
        projectScope,
        () => capability,
        () => {
          if (!active) throw Error('lease expired');
        },
      ).bootstrap(cases[1].command, options),
      /lease expired/,
    );
    assert.equal(mutations, 1);
  } finally {
    restore();
  }
});
test('late context or actor changes reject accepted response without rebasing intent', async () => {
  for (const target of ['actor', 'scope']) {
    let submitted = false,
      mutations = 0;
    const restore = install(async (url) => {
      if (String(url).endsWith('/auth/me'))
        return json({
          user_id: submitted && target === 'actor' ? 'foreign' : actor,
          is_active: true,
        });
      if (String(url).endsWith('/knowledge/context'))
        return json({
          contract_version: '1.0.0',
          scope: submitted && target === 'scope' ? { ...scope, generation: 2 } : scope,
        });
      mutations++;
      submitted = true;
      return json(envelope('schema_bootstrap', { receipt }));
    });
    try {
      await assert.rejects(
        create(
          config,
          projectScope,
          () => capability,
          () => {},
        ).bootstrap(cases[1].command, options),
      );
      assert.equal(mutations, 1);
    } finally {
      restore();
    }
  }
});
const trackCancel = (stream, notify) => {
  const get = stream.getReader.bind(stream);
  stream.getReader = (...args) => {
    const reader = get(...args);
    const cancel = reader.cancel.bind(reader);
    reader.cancel = (...values) => {
      notify();
      return cancel(...values);
    };
    return reader;
  };
  return stream;
};
const transport = (current = () => {}) =>
  request(config, '/api/v1/knowledge/schema/read', { method: 'POST', body: { scope } }, current);
test('chunked overflow cancels and releases the response reader before parsing', async () => {
  let cancelled = false;
  const stream = new ReadableStream({
    pull(controller) {
      controller.enqueue(new Uint8Array(65536));
    },
    cancel() {
      cancelled = true;
    },
  });
  trackCancel(stream, () => {
    cancelled = true;
  });
  const restore = install(
    async () => new Response(stream, { headers: { 'content-type': 'application/json' } }),
  );
  try {
    await assert.rejects(transport(), (error) => error.status === 413);
    assert.equal(cancelled, true);
    assert.equal(stream.locked, false);
  } finally {
    restore();
  }
});
test('UTF-8 byte cap accepts exact boundary and rejects the next code point', async () => {
  for (const extra of [0, 1]) {
    // Quotes use two bytes; a Chinese character is three UTF-8 bytes.
    const text = '"' + '界'.repeat((MAX - 2) / 3 + extra) + '"';
    const bytes = new TextEncoder().encode(text);
    let cancelled = false;
    const stream = new ReadableStream({
      start(controller) {
        for (let offset = 0; offset < bytes.length; offset += 10001)
          controller.enqueue(bytes.slice(offset, offset + 10001));
        controller.close();
      },
      cancel() {
        cancelled = true;
      },
    });
    trackCancel(stream, () => {
      cancelled = true;
    });
    const restore = install(
      async () =>
        new Response(stream, {
          headers: { 'content-type': 'application/json' },
        }),
    );
    try {
      if (extra) await assert.rejects(transport(), (error) => error.status === 413);
      else assert.equal((await transport()).length, (MAX - 2) / 3);
      assert.equal(stream.locked, false);
      if (extra) assert.equal(cancelled, true);
    } finally {
      restore();
    }
  }
});
test('duplicate JSON keys and invalid UTF-8 fail before the response shape decoder', async () => {
  for (const body of ['{"result":{"document":null,"document":{}}}', new Uint8Array([0xff])]) {
    let cancelled = false;
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(typeof body === 'string' ? new TextEncoder().encode(body) : body);
        controller.close();
      },
      cancel() {
        cancelled = true;
      },
    });
    trackCancel(stream, () => {
      cancelled = true;
    });
    const restore = install(
      async () =>
        new Response(stream, {
          headers: { 'content-type': 'application/json' },
        }),
    );
    try {
      await assert.rejects(transport());
      assert.equal(stream.locked, false);
      if (body instanceof Uint8Array) assert.equal(cancelled, true);
    } finally {
      restore();
    }
  }
});
test('redirect and server status policy never repeats a schema mutation', async () => {
  for (const status of [307, 409, 503]) {
    let calls = 0;
    const restore = install(async () => {
      calls++;
      return json({ error: { code: 'project_schema_test_error' } }, status);
    });
    try {
      await assert.rejects(transport(), (error) =>
        status === 307 ? true : error.status === status,
      );
      assert.equal(calls, 1);
    } finally {
      restore();
    }
  }
});
