/**
 * Minimal RFC 6455 WebSocket framing for the iab bridge client.
 *
 * The desktop ships no `ws` dependency and Node's global `WebSocket` cannot
 * dial a unix socket, so the bridge socket layer (`bridgeSocket.ts`) does the
 * HTTP upgrade itself and pumps frames through this codec. Client frames are
 * masked per the RFC; inbound frames are reassembled across continuations.
 * Pure module operating on Buffers, unit-tested from the compiled dist.
 */

export const WS_OPCODE_CONTINUATION = 0x0;
export const WS_OPCODE_TEXT = 0x1;
export const WS_OPCODE_BINARY = 0x2;
export const WS_OPCODE_CLOSE = 0x8;
export const WS_OPCODE_PING = 0x9;
export const WS_OPCODE_PONG = 0xa;

/** Largest single inbound message the bridge may send (generous for CDP). */
export const WS_MAX_MESSAGE_BYTES = 64 * 1024 * 1024;

export class WsProtocolError extends Error {}

export type WsFrame = Readonly<{
  fin: boolean;
  opcode: number;
  payload: Buffer;
}>;

/**
 * Incremental inbound frame parser. Feed bytes as they arrive; complete
 * frames come back from each call. Throws `WsProtocolError` on malformed
 * input (server frames must be unmasked, control frames ≤125 bytes and
 * unfragmented).
 */
export class WsFrameParser {
  #buffer: Buffer = Buffer.alloc(0);

  feed(chunk: Buffer): WsFrame[] {
    this.#buffer = this.#buffer.length === 0 ? chunk : Buffer.concat([this.#buffer, chunk]);
    const frames: WsFrame[] = [];
    while (true) {
      const frame = this.#tryParseFrame();
      if (!frame) break;
      frames.push(frame);
    }
    return frames;
  }

  #tryParseFrame(): WsFrame | null {
    const buffer = this.#buffer;
    if (buffer.length < 2) return null;
    const first = buffer[0]!;
    const second = buffer[1]!;
    const fin = (first & 0x80) !== 0;
    const opcode = first & 0x0f;
    const masked = (second & 0x80) !== 0;
    let length = second & 0x7f;
    let offset = 2;
    if (length === 126) {
      if (buffer.length < offset + 2) return null;
      length = buffer.readUInt16BE(offset);
      offset += 2;
    } else if (length === 127) {
      if (buffer.length < offset + 8) return null;
      const bigLength = buffer.readBigUInt64BE(offset);
      if (bigLength > BigInt(Number.MAX_SAFE_INTEGER)) {
        throw new WsProtocolError('websocket frame is too large');
      }
      length = Number(bigLength);
      offset += 8;
    }
    if (masked) {
      throw new WsProtocolError('server websocket frames must not be masked');
    }
    if (opcode >= 0x8 && (!fin || length > 125)) {
      throw new WsProtocolError('websocket control frame is invalid');
    }
    if (buffer.length < offset + length) return null;
    const payload = Buffer.from(buffer.subarray(offset, offset + length));
    this.#buffer = Buffer.from(buffer.subarray(offset + length));
    return Object.freeze({ fin, opcode, payload });
  }
}

/**
 * Reassembles inbound frames into whole messages. Control frames are passed
 * through immediately; fragmented data messages are concatenated until the
 * final continuation.
 */
export class WsMessageReassembler {
  #messageOpcode: number | null = null;
  #chunks: Buffer[] = [];
  #bytes = 0;

  /**
   * Consume one frame; returns a complete message `{opcode, payload}` for
   * text/binary completions, a control frame as-is for ping/pong/close, or
   * null when more fragments are needed.
   */
  accept(frame: WsFrame): WsFrame | null {
    if (frame.opcode >= 0x8) {
      return frame;
    }
    if (frame.opcode === WS_OPCODE_CONTINUATION) {
      if (this.#messageOpcode === null) {
        throw new WsProtocolError('unexpected websocket continuation frame');
      }
    } else {
      if (this.#messageOpcode !== null) {
        throw new WsProtocolError('websocket message interleaved before completion');
      }
      if (frame.fin) return frame;
      this.#messageOpcode = frame.opcode;
    }
    this.#chunks.push(frame.payload);
    this.#bytes += frame.payload.length;
    if (this.#bytes > WS_MAX_MESSAGE_BYTES) {
      throw new WsProtocolError('websocket message exceeds the size limit');
    }
    if (!frame.fin) return null;
    const opcode = this.#messageOpcode ?? frame.opcode;
    const payload =
      this.#chunks.length === 1 ? this.#chunks[0]! : Buffer.concat(this.#chunks);
    this.#messageOpcode = null;
    this.#chunks = [];
    this.#bytes = 0;
    return Object.freeze({ fin: true, opcode, payload });
  }
}

function writeMask(): Buffer {
  const mask = Buffer.alloc(4);
  for (let index = 0; index < 4; index += 1) {
    mask[index] = Math.floor(Math.random() * 256);
  }
  return mask;
}

/** Encode one outbound frame. Client frames are always masked (RFC 6455 §5). */
export function encodeWsFrame(opcode: number, payload: Buffer): Buffer {
  const mask = writeMask();
  const length = payload.length;
  let header: Buffer;
  if (length < 126) {
    header = Buffer.alloc(2);
    header[1] = 0x80 | length;
  } else if (length < 65536) {
    header = Buffer.alloc(4);
    header[1] = 0x80 | 126;
    header.writeUInt16BE(length, 2);
  } else {
    header = Buffer.alloc(10);
    header[1] = 0x80 | 127;
    header.writeBigUInt64BE(BigInt(length), 2);
  }
  header[0] = 0x80 | opcode;
  const masked = Buffer.alloc(length);
  for (let index = 0; index < length; index += 1) {
    masked[index] = payload[index]! ^ mask[index % 4]!;
  }
  return Buffer.concat([header, mask, masked]);
}

export function encodeWsText(message: string): Buffer {
  return encodeWsFrame(WS_OPCODE_TEXT, Buffer.from(message, 'utf8'));
}

export function encodeWsPong(payload: Buffer): Buffer {
  return encodeWsFrame(WS_OPCODE_PONG, payload);
}

export function encodeWsClose(): Buffer {
  return encodeWsFrame(WS_OPCODE_CLOSE, Buffer.alloc(0));
}
