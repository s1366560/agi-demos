import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  IAB_BACKEND_NAME,
  IAB_ERR_HANDLER,
  IAB_ERR_INVALID_PARAMS,
  IAB_ERR_METHOD_NOT_FOUND,
  IAB_ERR_PARSE,
  IAB_PROTOCOL_VERSION,
  IabInvalidParamsError,
  buildIabHelloResult,
  createIabRpcRouter,
  encodeIabNotification,
  parseIabTurnEndedLeases,
} = require('/tmp/agistack-desktop-test-dist/electron/main/iab/iabMessageRouter.js');

test('hello answers with the iab backend handshake', () => {
  const hello = buildIabHelloResult();
  assert.equal(hello.protocolVersion, IAB_PROTOCOL_VERSION);
  assert.equal(hello.backend, IAB_BACKEND_NAME);
  assert.equal(hello.backend, 'iab');
  assert.equal(Array.isArray(hello.capabilities), true);
  assert.equal(hello.capabilities.includes('cdp'), true);
});

test('router dispatches requests and encodes results', async () => {
  const router = createIabRpcRouter({
    hello: () => buildIabHelloResult(),
    getTabs: () => ({ tabs: [] }),
  });
  const helloResponse = JSON.parse(await router('{"jsonrpc":"2.0","id":1,"method":"hello"}'));
  assert.equal(helloResponse.id, 1);
  assert.equal(helloResponse.result.protocolVersion, 1);
  assert.equal(helloResponse.result.backend, 'iab');

  const tabsResponse = JSON.parse(await router('{"jsonrpc":"2.0","id":"x","method":"getTabs"}'));
  assert.deepEqual(tabsResponse.result, { tabs: [] });
});

test('router maps errors to the contract codes', async () => {
  const router = createIabRpcRouter({
    broken: () => {
      throw new Error('tab 7 does not exist');
    },
    invalid: () => {
      throw new IabInvalidParamsError('tabId missing');
    },
  });
  const unknown = JSON.parse(await router('{"jsonrpc":"2.0","id":2,"method":"nope"}'));
  assert.equal(unknown.error.code, IAB_ERR_METHOD_NOT_FOUND);
  assert.equal(IAB_ERR_METHOD_NOT_FOUND, -32601);

  const invalid = JSON.parse(await router('{"jsonrpc":"2.0","id":3,"method":"invalid"}'));
  assert.equal(invalid.error.code, IAB_ERR_INVALID_PARAMS);
  assert.equal(IAB_ERR_INVALID_PARAMS, -32602);

  const handler = JSON.parse(await router('{"jsonrpc":"2.0","id":4,"method":"broken"}'));
  assert.equal(handler.error.code, IAB_ERR_HANDLER);
  assert.equal(IAB_ERR_HANDLER, 1);
  assert.match(handler.error.message, /tab 7/);

  const unparsable = JSON.parse(await router('not json'));
  assert.equal(unparsable.error.code, IAB_ERR_PARSE);

  const noEnvelope = JSON.parse(await router('{"id":5,"method":"hello"}'));
  assert.equal(noEnvelope.error.code, -32600);
});

test('router answers null for notifications', async () => {
  const router = createIabRpcRouter({ hello: () => buildIabHelloResult() });
  assert.equal(await router('{"jsonrpc":"2.0","method":"hello"}'), null);
});

test('notifications encode with the wire shape', () => {
  const encoded = JSON.parse(encodeIabNotification('onCDPEvent', { tabId: 3, method: 'Page.loadEventFired', params: {} }));
  assert.equal(encoded.jsonrpc, '2.0');
  assert.equal(encoded.method, 'onCDPEvent');
  assert.equal(encoded.params.tabId, 3);
  assert.equal('id' in encoded, false);
});

test('turnEnded lease parsing enforces the contract shape', () => {
  const leases = parseIabTurnEndedLeases({
    leases: [
      { tabId: 7, origin: 'agent', mark: 'deliverable' },
      { tabId: 8, origin: 'user' },
    ],
  });
  assert.deepEqual(
    leases.map((lease) => [lease.tabId, lease.origin, lease.mark]),
    [
      [7, 'agent', 'deliverable'],
      [8, 'user', null],
    ],
  );
  assert.throws(() => parseIabTurnEndedLeases({ leases: [{ tabId: 7, origin: 'robot' }] }), IabInvalidParamsError);
  assert.throws(() => parseIabTurnEndedLeases({ leases: [{ tabId: -1, origin: 'agent' }] }), IabInvalidParamsError);
  assert.throws(() => parseIabTurnEndedLeases({ leases: [{ tabId: 7, origin: 'agent', mark: 'archive' }] }), IabInvalidParamsError);
  assert.throws(() => parseIabTurnEndedLeases({}), IabInvalidParamsError);
});
