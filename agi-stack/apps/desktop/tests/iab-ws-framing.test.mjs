import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  WS_OPCODE_CLOSE,
  WS_OPCODE_PING,
  WS_OPCODE_TEXT,
  WsFrameParser,
  WsMessageReassembler,
  WsProtocolError,
  encodeWsFrame,
  encodeWsText,
} = require('/tmp/agistack-desktop-test-dist/electron/main/iab/wsFraming.js');

function unmaskServerStyle(frame) {
  // Test helper: decode a client frame the way a server would (unmask it).
  const second = frame[1];
  const masked = (second & 0x80) !== 0;
  let length = second & 0x7f;
  let offset = 2;
  if (length === 126) {
    length = frame.readUInt16BE(2);
    offset = 4;
  } else if (length === 127) {
    length = Number(frame.readBigUInt64BE(2));
    offset = 10;
  }
  if (!masked) return { opcode: frame[0] & 0x0f, payload: frame.subarray(offset, offset + length) };
  const mask = frame.subarray(offset, offset + 4);
  const payload = Buffer.alloc(length);
  for (let index = 0; index < length; index += 1) {
    payload[index] = frame[offset + 4 + index] ^ mask[index % 4];
  }
  return { opcode: frame[0] & 0x0f, payload };
}

function serverFrame(opcode, payload, fin = true) {
  const body = Buffer.from(payload);
  let header;
  if (body.length < 126) {
    header = Buffer.from([(fin ? 0x80 : 0) | opcode, body.length]);
  } else if (body.length < 65536) {
    header = Buffer.alloc(4);
    header[0] = (fin ? 0x80 : 0) | opcode;
    header[1] = 126;
    header.writeUInt16BE(body.length, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = (fin ? 0x80 : 0) | opcode;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(body.length), 2);
  }
  return Buffer.concat([header, body]);
}

test('outbound frames are masked and round-trip', () => {
  const encoded = encodeWsText('{"jsonrpc":"2.0","id":1,"result":{}}');
  const decoded = unmaskServerStyle(encoded);
  assert.equal(decoded.opcode, WS_OPCODE_TEXT);
  assert.equal(decoded.payload.toString('utf8'), '{"jsonrpc":"2.0","id":1,"result":{}}');

  const large = encodeWsFrame(WS_OPCODE_TEXT, Buffer.alloc(70_000, 0x61));
  const largeDecoded = unmaskServerStyle(large);
  assert.equal(largeDecoded.payload.length, 70_000);
  assert.equal(largeDecoded.payload.every((byte) => byte === 0x61), true);
});

test('inbound parser handles chunk-split and coalesced frames', () => {
  const parser = new WsFrameParser();
  const frame = serverFrame(WS_OPCODE_TEXT, 'hello');
  const first = parser.feed(frame.subarray(0, 3));
  assert.equal(first.length, 0);
  const second = parser.feed(frame.subarray(3));
  assert.equal(second.length, 1);
  assert.equal(second[0].payload.toString('utf8'), 'hello');

  const two = parser.feed(
    Buffer.concat([serverFrame(WS_OPCODE_TEXT, 'a'), serverFrame(WS_OPCODE_PING, 'b')]),
  );
  assert.equal(two.length, 2);
  assert.equal(two[1].opcode, WS_OPCODE_PING);
});

test('inbound parser rejects masked server frames and bad control frames', () => {
  const parser = new WsFrameParser();
  const masked = encodeWsText('client-style'); // masked: illegal from a server
  assert.throws(() => parser.feed(masked), WsProtocolError);

  const fragmentedPing = Buffer.from([WS_OPCODE_PING, 0]); // fin=0 control frame
  assert.throws(() => new WsFrameParser().feed(fragmentedPing), WsProtocolError);
});

test('reassembler joins fragmented messages and passes control frames through', () => {
  const reassembler = new WsMessageReassembler();
  const parser = new WsFrameParser();
  const wire = Buffer.concat([
    serverFrame(WS_OPCODE_TEXT, 'hel', false),
    serverFrame(0x0, 'lo ', false),
    serverFrame(0x0, 'world', true),
  ]);
  const frames = parser.feed(wire);
  assert.equal(frames.length, 3);
  assert.equal(reassembler.accept(frames[0]), null);
  assert.equal(reassembler.accept(frames[1]), null);
  const complete = reassembler.accept(frames[2]);
  assert.equal(complete.opcode, WS_OPCODE_TEXT);
  assert.equal(complete.payload.toString('utf8'), 'hello world');

  const ping = parser.feed(serverFrame(WS_OPCODE_PING, 'x'))[0];
  const control = reassembler.accept(ping);
  assert.equal(control.opcode, WS_OPCODE_PING);

  const stray = parser.feed(serverFrame(WS_OPCODE_CLOSE, ''))[0];
  assert.equal(reassembler.accept(stray).opcode, WS_OPCODE_CLOSE);
});
