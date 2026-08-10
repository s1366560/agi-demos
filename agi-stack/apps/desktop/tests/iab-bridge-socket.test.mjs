import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { connectIabBridgeSocket } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/iab/bridgeSocket.js',
);
const {
  buildIabHelloResult,
  createIabRpcRouter,
} = require('/tmp/agistack-desktop-test-dist/electron/main/iab/iabMessageRouter.js');

const WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
const TOKEN = 'a'.repeat(64);

/** Server→client text frame: unmasked, per RFC 6455. */
function serverTextFrame(text) {
  const payload = Buffer.from(text, 'utf8');
  let header;
  if (payload.length < 126) {
    header = Buffer.from([0x81, payload.length]);
  } else if (payload.length < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(payload.length, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(payload.length), 2);
  }
  return Buffer.concat([header, payload]);
}

/** Minimal masked-frame reader for the mock server side. */
function readClientFrames(state, chunk) {
  state.buffer = state.buffer.length === 0 ? chunk : Buffer.concat([state.buffer, chunk]);
  const messages = [];
  while (true) {
    const buffer = state.buffer;
    if (buffer.length < 2) break;
    let length = buffer[1] & 0x7f;
    let offset = 2;
    if (length === 126) {
      if (buffer.length < 4) break;
      length = buffer.readUInt16BE(2);
      offset = 4;
    } else if (length === 127) {
      if (buffer.length < 10) break;
      length = Number(buffer.readBigUInt64BE(2));
      offset = 10;
    }
    const masked = (buffer[1] & 0x80) !== 0;
    const maskOffset = masked ? 4 : 0;
    if (buffer.length < offset + maskOffset + length) break;
    let payload = buffer.subarray(offset + maskOffset, offset + maskOffset + length);
    if (masked) {
      const mask = buffer.subarray(offset, offset + 4);
      const unmasked = Buffer.alloc(length);
      for (let index = 0; index < length; index += 1) {
        unmasked[index] = payload[index] ^ mask[index % 4];
      }
      payload = unmasked;
    }
    state.buffer = buffer.subarray(offset + maskOffset + length);
    messages.push({ opcode: buffer[0] & 0x0f, payload });
  }
  return messages;
}

function connectWithRouter(transport) {
  const router = createIabRpcRouter({ hello: () => buildIabHelloResult() });
  let socket;
  return new Promise((resolve, reject) => {
    connectIabBridgeSocket(transport, TOKEN, {
      onMessage: (text) => {
        void router(text).then((response) => {
          if (response !== null) socket.send(response);
        });
      },
      onClose: () => {},
    }).then((connected) => {
      socket = connected;
      resolve(connected);
    }, reject);
  });
}

test('iab bridge socket handshake + hello over TCP', async () => {
  const server = createServer();
  const received = new Promise((resolve, reject) => {
    server.on('upgrade', (request, socket) => {
      assert.equal(request.headers.authorization, `Bearer ${TOKEN}`);
      assert.equal(request.url, '/api/v1/browser-bridge/ws');
      const accept = createHash('sha1')
        .update(request.headers['sec-websocket-key'] + WS_GUID)
        .digest('base64');
      socket.write(
        [
          'HTTP/1.1 101 Switching Protocols',
          'Upgrade: websocket',
          'Connection: Upgrade',
          `Sec-WebSocket-Accept: ${accept}`,
          '',
          '',
        ].join('\r\n'),
      );
      socket.write(serverTextFrame(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'hello' })));
      const state = { buffer: Buffer.alloc(0) };
      socket.on('data', (chunk) => {
        for (const frame of readClientFrames(state, chunk)) {
          if (frame.opcode === 0x1) resolve(JSON.parse(frame.payload.toString('utf8')));
        }
      });
      socket.on('error', reject);
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  const client = await connectWithRouter({
    kind: 'tcp',
    wsUrl: `ws://127.0.0.1:${port}/api/v1/browser-bridge/ws`,
  });
  const response = await received;
  assert.equal(response.id, 1);
  assert.equal(response.result.protocolVersion, 1);
  assert.equal(response.result.backend, 'iab');
  assert.ok(Array.isArray(response.result.capabilities));
  client.close();
  server.close();
});

test('iab bridge socket handshake + hello over a unix socket', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'iab-bridge-test-'));
  const socketPath = join(directory, 'bridge.sock');
  try {
    const server = createServer();
    const received = new Promise((resolve, reject) => {
      server.on('upgrade', (request, socket) => {
        if (request.headers.authorization !== `Bearer ${TOKEN}`) {
          socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
          socket.destroy();
          return;
        }
        const accept = createHash('sha1')
          .update(request.headers['sec-websocket-key'] + WS_GUID)
          .digest('base64');
        socket.write(
          [
            'HTTP/1.1 101 Switching Protocols',
            'Upgrade: websocket',
            'Connection: Upgrade',
            `Sec-WebSocket-Accept: ${accept}`,
            '',
            '',
          ].join('\r\n'),
        );
        socket.write(serverTextFrame(JSON.stringify({ jsonrpc: '2.0', id: 9, method: 'ping' })));
        const state = { buffer: Buffer.alloc(0) };
        socket.on('data', (chunk) => {
          for (const frame of readClientFrames(state, chunk)) {
            if (frame.opcode === 0x1) resolve(JSON.parse(frame.payload.toString('utf8')));
          }
        });
        socket.on('error', reject);
      });
    });
    await new Promise((resolve) => server.listen(socketPath, resolve));
    const router = createIabRpcRouter({ ping: () => ({}) });
    let client;
    client = await new Promise((resolve, reject) => {
      connectIabBridgeSocket({ kind: 'unix', socketPath }, TOKEN, {
        onMessage: (text) => {
          void router(text).then((response) => {
            if (response !== null) client.send(response);
          });
        },
        onClose: () => {},
      }).then(resolve, reject);
    });
    const response = await received;
    assert.equal(response.id, 9);
    assert.deepEqual(response.result, {});
    client.close();
    server.close();
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('iab bridge socket rejects a failed handshake', async () => {
  const server = createServer((_request, response) => {
    response.writeHead(401);
    response.end();
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  await assert.rejects(
    connectIabBridgeSocket(
      { kind: 'tcp', wsUrl: `ws://127.0.0.1:${port}/api/v1/browser-bridge/ws` },
      'b'.repeat(64),
      { onMessage: () => {}, onClose: () => {} },
    ),
    /closed during handshake|rejected/,
  );
  server.close();
});
