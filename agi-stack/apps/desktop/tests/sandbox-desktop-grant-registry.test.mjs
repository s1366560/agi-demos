import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  SandboxDesktopGrantRegistry: Registry,
} = require('/tmp/agistack-desktop-test-dist/electron/main/sandboxDesktopGrantRegistry.js');
const request = () => ({
  requestId: 'request_0123456789abcd',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  descriptor: {
    contract_version: 1,
    project_id: 'project-1',
    protocol: 'kasmvnc-1',
    auth_mode: 'scoped_http_only_cookie',
    proxy_url: '/api/v1/projects/project-1/sandbox/desktop/proxy/vnc.html',
  },
});
const authorization = () => ({
  apiBaseUrl: 'https://cloud.invalid',
  credential: 'private-fixture-value',
  expiresAt: null,
});
function fixture(extra = {}) {
  const counts = { authorize: 0, blank: 0 };
  const registry = new Registry({
    authorize: async () => {
      counts.authorize++;
      return authorization();
    },
    randomId: () => 'grant_0123456789abcde',
    blankFrame: async () => {
      counts.blank++;
    },
    ...extra,
  });
  return { registry, counts };
}
function details(reply, extra = {}) {
  return {
    id: 1,
    webContentsId: 7,
    url: reply.frameUrl,
    method: 'GET',
    resourceType: 'subFrame',
    frame: { frameTreeNodeId: 12, parentFrameTreeNodeId: 11, name: reply.frameName },
    ...extra,
  };
}
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

test('open returns opaque metadata and only exact admitted frame receives Authorization without Cookie', async () => {
  const { registry } = fixture();
  const reply = await registry.open(7, 11, request());
  assert.equal(JSON.stringify(reply).includes('private-fixture-value'), false);
  const result = registry.beforeRequest(details(reply), {
    cookie: 'old-cookie',
    authorization: 'renderer-value',
    Accept: 'text/html',
  });
  assert.equal(result.kind, 'authorized');
  assert.deepEqual(result.requestHeaders, {
    Accept: 'text/html',
    Authorization: 'Bearer private-fixture-value',
  });
  assert.deepEqual(
    registry.responseHeaders(details(reply), {
      'Set-Cookie': ['secret'],
      'content-type': ['text/html'],
    }),
    { 'content-type': ['text/html'] },
  );
  registry.completeRequest(1);
  await registry.close(7, { requestId: request().requestId, grantId: reply.grantId });
  assert.equal(registry.beforeRequest(details(reply), {}).kind, 'blocked');
});
test('close before open IPC tombstones request and performs zero authorization', async () => {
  const { registry, counts } = fixture();
  await registry.close(7, { requestId: request().requestId });
  await assert.rejects(registry.open(7, 11, request()));
  assert.equal(counts.authorize, 0);
});
test('pending authorization abort produces no late grant while close drains authorization', async () => {
  const gate = deferred();
  const { registry, counts } = fixture({ authorize: () => gate.promise });
  const pending = registry.open(7, 11, request());
  const rejected = assert.rejects(pending);
  let closed = false;
  const closing = registry.close(7, { requestId: request().requestId }).then(() => {
    closed = true;
  });
  await rejected;
  assert.equal(closed, false);
  gate.resolve(authorization());
  await closing;
  assert.equal(counts.blank, 0);
  await assert.rejects(registry.open(7, 11, request()));
});
test('revoke is synchronous before blank navigation resolves and preserves cleanup failure', async () => {
  const gate = deferred();
  const { registry } = fixture({ blankFrame: () => gate.promise });
  const reply = await registry.open(7, 11, request());
  assert.equal(registry.beforeRequest(details(reply), {}).kind, 'authorized');
  registry.completeRequest(1);
  let closed = false;
  const closing = registry.revokeOwner(7).then(() => {
    closed = true;
  });
  assert.equal(registry.beforeRequest(details(reply), {}).kind, 'blocked');
  assert.equal(closed, false);
  gate.resolve();
  await closing;
  assert.equal(closed, true);
});
test('expired opening authorization explicitly rejects and active expiration revokes before headers', async () => {
  const expired = fixture({
    authorize: async () => ({ ...authorization(), expiresAt: new Date(1000).toISOString() }),
    now: () => 2000,
  });
  await assert.rejects(expired.registry.open(7, 11, request()), /expired/);
  let now = 1000;
  const { registry } = fixture({
    authorize: async () => ({ ...authorization(), expiresAt: new Date(2000).toISOString() }),
    now: () => now,
  });
  const reply = await registry.open(7, 11, request());
  now = 3000;
  assert.equal(registry.beforeRequest(details(reply), {}).kind, 'blocked');
  await registry.revokeAll();
});
test('same frame leaving its URL never revives its authorization on a later request', async () => {
  const { registry } = fixture();
  const reply = await registry.open(7, 11, request());
  assert.equal(registry.beforeRequest(details(reply), {}).kind, 'authorized');
  registry.completeRequest(1);
  registry.observeFrameNavigation(7, 12, 'https://other.invalid');
  assert.equal(registry.beforeRequest(details(reply), {}).kind, 'blocked');
  await registry.revokeAll();
});
test('same request ID redirect cannot carry injected Authorization outside the proxy prefix', async () => {
  const { registry } = fixture();
  const reply = await registry.open(7, 11, request());
  registry.beforeRequest(details(reply), {});
  assert.equal(
    registry.beforeRequest(
      details(reply, { url: 'https://other.invalid', resourceType: 'script' }),
      { Authorization: 'private-fixture-value' },
    ).kind,
    'blocked',
  );
  registry.completeRequest(1);
  await registry.revokeAll();
});
test('unrelated requests and headers remain unchanged and sibling frame cannot borrow credentials', async () => {
  const { registry } = fixture();
  const reply = await registry.open(7, 11, request());
  const headers = { 'Set-Cookie': 'ordinary' };
  assert.equal(
    registry.responseHeaders({ id: 99, url: 'https://unrelated.invalid' }, headers),
    headers,
  );
  assert.equal(
    registry.beforeRequest(details(reply, { id: 99, url: 'https://unrelated.invalid' }), {}).kind,
    'unrelated',
  );
  registry.beforeRequest(details(reply), {});
  registry.completeRequest(1);
  const sibling = { ...details(reply).frame, frameTreeNodeId: 13 };
  assert.equal(
    registry.beforeRequest(details(reply, { id: 2, frame: sibling }), {}).kind,
    'blocked',
  );
  await registry.revokeAll();
});
test('all revocations drain even when one frame blank fails', async () => {
  const { registry, counts } = fixture({
    blankFrame: async (owner) => {
      counts.blank++;
      if (owner === 7) throw new Error('blank failed');
    },
  });
  const first = await registry.open(7, 11, request());
  const second = await registry.open(8, 11, request());
  registry.beforeRequest(details(first), {});
  registry.beforeRequest(details(second, { id: 2, webContentsId: 8 }), {});
  registry.completeRequest(1);
  registry.completeRequest(2);
  await assert.rejects(registry.revokeAll(), /blank failed/);
  assert.equal(counts.blank, 2);
  assert.equal(registry.beforeRequest(details(first), {}).kind, 'blocked');
  assert.equal(
    registry.beforeRequest(details(second, { id: 2, webContentsId: 8 }), {}).kind,
    'blocked',
  );
});
test('wrong grant close cannot revoke a different handle and frame destruction clears owner resources', async () => {
  const { registry, counts } = fixture();
  const reply = await registry.open(7, 11, request());
  registry.beforeRequest(details(reply), {});
  registry.completeRequest(1);
  assert.throws(() =>
    registry.close(7, { requestId: request().requestId, grantId: 'another_0123456789abcd' }),
  );
  registry.observeFrameDestroyed(7, 12);
  await registry.revokeAll();
  assert.equal(counts.blank, 0);
});

test('authority transition blocks new authorization throughout revocation and actual mutation', async () => {
  const blank = deferred(),
    mutation = deferred(),
    entered = deferred();
  const { registry, counts } = fixture({ blankFrame: () => blank.promise });
  const first = await registry.open(7, 11, request());
  registry.beforeRequest(details(first), {});
  registry.completeRequest(1);
  const switching = registry.withAuthorityTransition(async () => {
    entered.resolve();
    await mutation.promise;
  });
  const next = { ...request(), requestId: 'request_next_0123456789' };
  await assert.rejects(registry.open(7, 11, next), /authority_transition/);
  assert.equal(counts.authorize, 1);
  blank.resolve();
  await entered.promise;
  await assert.rejects(registry.open(7, 11, next), /authority_transition/);
  assert.equal(counts.authorize, 1);
  mutation.resolve();
  await switching;
  await registry.open(7, 11, next);
  assert.equal(counts.authorize, 2);
  await registry.revokeAll();
});
test('concurrent authority mutations serialize and admission stays blocked until the last finishes', async () => {
  const one = deferred(),
    two = deferred(),
    startedOne = deferred(),
    startedTwo = deferred();
  const { registry } = fixture();
  const first = registry.withAuthorityTransition(async () => {
    startedOne.resolve();
    await one.promise;
  });
  let secondStarted = false;
  const second = registry.withAuthorityTransition(async () => {
    secondStarted = true;
    startedTwo.resolve();
    await two.promise;
  });
  await startedOne.promise;
  assert.equal(secondStarted, false);
  one.resolve();
  await first;
  await startedTwo.promise;
  await assert.rejects(registry.open(7, 11, request()), /authority_transition/);
  two.resolve();
  await second;
  await registry.open(7, 11, request());
  await registry.revokeAll();
});
test('failed authority mutation releases the barrier while preserving its primary error', async () => {
  const { registry } = fixture();
  const primary = new Error('vault mutation failed');
  await assert.rejects(
    registry.withAuthorityTransition(async () => {
      throw primary;
    }),
    (error) => error === primary,
  );
  await registry.open(7, 11, request());
  await registry.revokeAll();
});
