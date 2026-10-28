import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { setImmediate } from 'node:timers/promises';
import test from 'node:test';
import { AppBridge as EsmAppBridge } from '@mcp-ui/client';

const require = createRequire(import.meta.url);
const clientRequire = createRequire(require.resolve('@mcp-ui/client'));
const { Server: CjsServer } = clientRequire('@modelcontextprotocol/sdk/server/index.js');
const { CallToolRequestSchema } = clientRequire('@modelcontextprotocol/sdk/types.js');
const reason = 'request cancelled by the app';
const completedResult = { content: [{ type: 'text', text: 'completed tool result' }] };

class MemoryTransport {
  sent = [];
  async start() {}
  async send(message) {
    this.sent.push(structuredClone(message));
  }
  async close() {
    this.onclose?.();
  }
  receive(message) {
    this.onmessage?.(structuredClone(message));
  }
  responses(id) {
    return this.sent.filter((message) => 'id' in message && message.id === id);
  }
}

async function connectBridge(Bridge, context, sdk = false) {
  const transport = new MemoryTransport();
  const info = { name: 'cancellation-test-host', version: '1' };
  const bridge = sdk
    ? new Bridge(info, { capabilities: { tools: {} } })
    : new Bridge(null, info, { serverTools: {} });
  const requests = new Map();
  const errors = [];
  bridge.onerror = (error) => errors.push(error);
  const oncalltool = async (_params, extra) => {
    let release;
    let fail;
    const pending = new Promise((resolve, reject) => {
      release = () => resolve(completedResult);
      fail = () => reject(new Error('tool completed with an error'));
    });
    requests.set(extra.requestId, { signal: extra.signal, release, fail });
    return pending;
  };
  if (sdk) bridge.setRequestHandler(CallToolRequestSchema, oncalltool);
  else bridge.oncalltool = oncalltool;
  context.after(async () => {
    for (const request of requests.values()) request.release();
    await setImmediate();
    await bridge.close();
  });
  await bridge.connect(transport);
  transport.receive({
    jsonrpc: '2.0', id: 'initialize', method: sdk ? 'initialize' : 'ui/initialize',
    params: sdk ? {
      clientInfo: { name: 'cancellation-test-client', version: '1' },
      capabilities: {}, protocolVersion: '2025-11-25',
    } : {
      appInfo: { name: 'cancellation-test-app', version: '1' },
      appCapabilities: {}, protocolVersion: '2026-01-26',
    },
  });
  await setImmediate();
  assert.equal(transport.responses('initialize').length, 1);
  assert.ok(transport.responses('initialize')[0].result);
  transport.receive({
    jsonrpc: '2.0',
    method: sdk ? 'notifications/initialized' : 'ui/notifications/initialized',
    params: {},
  });
  await setImmediate();
  assert.deepEqual(errors, []);

  return {
    transport,
    errors,
    async call(id) {
      transport.receive({
        jsonrpc: '2.0', id, method: 'tools/call',
        params: { name: 'held_tool', arguments: {} },
      });
      await setImmediate();
      const request = requests.get(id);
      assert.ok(request, 'public oncalltool handler must receive the request');
      assert.equal(request.signal.aborted, false);
      assert.deepEqual(transport.responses(id), []);
      return request;
    },
    async cancel(params) {
      transport.receive({ jsonrpc: '2.0', method: 'notifications/cancelled', params });
      await setImmediate();
    },
    async finish(...pending) {
      for (const request of pending) request.release();
      await setImmediate();
      assert.deepEqual(errors, []);
    },
  };
}

for (const [format, Bridge, sdk] of [
  ['ESM AppBridge', EsmAppBridge, false],
  ['CJS SDK Server', CjsServer, true],
]) {
  for (const id of [0, 1, '']) {
    test(`${format}: cancellation aborts request ${JSON.stringify(id)} and suppresses its late result`, async (context) => {
      const fixture = await connectBridge(Bridge, context, sdk);
      const request = await fixture.call(id);
      await fixture.cancel({ requestId: id, reason });
      const observed = { aborted: request.signal.aborted, reason: request.signal.reason };
      await fixture.finish(request);
      assert.deepEqual({
        ...observed, responses: fixture.transport.responses(id),
      }, { aborted: true, reason, responses: [] });
    });
  }

  for (const [cancelledId, remainingId] of [['0', 0], [0, '0']]) {
    test(`${format}: cancelling ${JSON.stringify(cancelledId)} preserves distinct ${JSON.stringify(remainingId)}`, async (context) => {
      const fixture = await connectBridge(Bridge, context, sdk);
      const cancelled = await fixture.call(cancelledId);
      const remaining = await fixture.call(remainingId);
      await fixture.cancel({ requestId: cancelledId, reason });
      const observed = {
        cancelledAborted: cancelled.signal.aborted,
        remainingAborted: remaining.signal.aborted,
      };
      await fixture.finish(cancelled, remaining);
      assert.deepEqual({
        ...observed,
        cancelledResponses: fixture.transport.responses(cancelledId),
        remainingResponses: fixture.transport.responses(remainingId),
      }, {
        cancelledAborted: true,
        remainingAborted: false,
        cancelledResponses: [],
        remainingResponses: [{ jsonrpc: '2.0', id: remainingId, result: completedResult }],
      });
    });
  }

  for (const [label, params] of [
    ['unknown request id', { requestId: 999, reason }],
    ['missing request id', { reason }],
  ]) {
    test(`${format}: cancellation with ${label} leaves other requests live`, async (context) => {
      const fixture = await connectBridge(Bridge, context, sdk);
      const zero = await fixture.call(0);
      const another = await fixture.call(1);
      const sentBefore = fixture.transport.sent.length;
      await fixture.cancel(params);
      assert.equal(zero.signal.aborted, false);
      assert.equal(another.signal.aborted, false);
      assert.equal(fixture.transport.sent.length, sentBefore, 'notification must not get a response');
      assert.deepEqual(fixture.errors, [], 'optional requestId must pass the SDK notification schema');
      await fixture.finish(zero, another);
      for (const id of [0, 1]) {
        assert.deepEqual(fixture.transport.responses(id), [
          { jsonrpc: '2.0', id, result: completedResult },
        ]);
      }
    });
  }

  test(`${format}: late cancellation cannot abort a completed or unrelated new request`, async (context) => {
    const fixture = await connectBridge(Bridge, context, sdk);
    const completed = await fixture.call(0);
    await fixture.finish(completed);
    const remaining = await fixture.call('0');
    const sentBefore = structuredClone(fixture.transport.sent);
    await fixture.cancel({ requestId: 0, reason });
    assert.equal(completed.signal.aborted, false);
    assert.equal(remaining.signal.aborted, false);
    assert.deepEqual(fixture.transport.sent, sentBefore);
    await fixture.finish(remaining);
    for (const id of [0, '0']) {
      assert.deepEqual(fixture.transport.responses(id), [
        { jsonrpc: '2.0', id, result: completedResult },
      ]);
    }
  });

  test(`${format}: cancelled request zero suppresses a late handler error`, async (context) => {
    const fixture = await connectBridge(Bridge, context, sdk);
    const request = await fixture.call(0);
    await fixture.cancel({ requestId: 0, reason });
    const aborted = request.signal.aborted;
    request.fail();
    await setImmediate();
    assert.deepEqual(fixture.errors, []);
    assert.deepEqual({ aborted, responses: fixture.transport.responses(0) }, {
      aborted: true, responses: [],
    });
  });
}
