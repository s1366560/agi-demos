/**
 * Browser-bridge WebSocket client for the iab backend.
 *
 * Connects to the sidecar's bridge endpoint either over TCP
 * (`ws://127.0.0.1:<port>/api/v1/browser-bridge/ws`) or — preferred — over
 * the unix socket the registry advertises. The desktop ships no `ws`
 * dependency and Node's global `WebSocket` cannot dial unix sockets, so the
 * opening handshake is done on a raw `net.Socket` and frames flow through
 * the pure codec in `wsFraming.ts`.
 */

import { createHash, randomBytes } from 'node:crypto';
import { connect as connectSocket, type Socket } from 'node:net';

import {
  WS_OPCODE_BINARY,
  WS_OPCODE_CLOSE,
  WS_OPCODE_PING,
  WS_OPCODE_TEXT,
  WsFrameParser,
  WsMessageReassembler,
  WsProtocolError,
  encodeWsClose,
  encodeWsPong,
  encodeWsText,
} from './wsFraming';

const WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
const HANDSHAKE_TIMEOUT_MS = 10_000;
const MAX_HANDSHAKE_BYTES = 16 * 1024;
const BRIDGE_WS_PATH = '/api/v1/browser-bridge/ws';

export type IabBridgeTransport =
  | Readonly<{ kind: 'unix'; socketPath: string }>
  | Readonly<{ kind: 'tcp'; wsUrl: string }>;

export type IabBridgeSocketHandlers = {
  /** Complete inbound text message. */
  onMessage: (text: string) => void;
  /** Terminal event (error, close frame, or EOF); fires exactly once. */
  onClose: (reason: string) => void;
};

export type IabBridgeSocket = {
  send: (text: string) => void;
  close: () => void;
};

function expectedAcceptKey(key: string): string {
  return createHash('sha1')
    .update(key + WS_GUID)
    .digest('base64');
}

/**
 * Open the bridge socket and authenticate with the registry bearer token.
 * Resolves once the 101 handshake completes; rejects on any handshake or
 * transport failure.
 */
export function connectIabBridgeSocket(
  transport: IabBridgeTransport,
  token: string,
  handlers: IabBridgeSocketHandlers,
): Promise<IabBridgeSocket> {
  return new Promise((resolve, reject) => {
    const key = randomBytes(16).toString('base64');
    const parser = new WsFrameParser();
    const reassembler = new WsMessageReassembler();
    let handshakeBuffer: Buffer = Buffer.alloc(0);
    let settled = false;
    let closed = false;
    // True once the handshake completed and the socket was handed to the
    // caller via resolve(); gates whether onClose may fire (see finishClose).
    let handedOff = false;

    const tcpTarget =
      transport.kind === 'tcp'
        ? (() => {
            const url = new URL(transport.wsUrl);
            return { host: url.hostname, port: Number(url.port || 80), hostHeader: url.host, path: url.pathname || BRIDGE_WS_PATH };
          })()
        : null;
    const hostHeader = tcpTarget?.hostHeader ?? 'localhost';
    const requestPath = tcpTarget?.path ?? BRIDGE_WS_PATH;

    const socket: Socket =
      transport.kind === 'unix'
        ? connectSocket({ path: transport.socketPath })
        : connectSocket({ host: tcpTarget!.host, port: tcpTarget!.port });

    const finishClose = (reason: string): void => {
      if (closed) return;
      closed = true;
      try {
        socket.destroy();
      } catch {
        // Socket teardown must not throw past the close path.
      }
      // onClose fires only for a connection that actually completed the
      // handshake: a pre-handshake failure already surfaced through the
      // promise rejection, and reporting it again through onClose ran while
      // the caller's `await connect…` binding was still uninitialized (TDZ
      // ReferenceError inside the 'close' emit — uncaught, and Electron's
      // default handler shows a modal dialog that parks the main process).
      if (handedOff) handlers.onClose(reason);
    };

    const handshakeTimer = setTimeout(() => {
      if (!settled) {
        settled = true;
        socket.destroy();
        reject(new Error('browser bridge handshake timed out'));
      }
    }, HANDSHAKE_TIMEOUT_MS);

    socket.once('error', (error) => {
      if (!settled) {
        settled = true;
        clearTimeout(handshakeTimer);
        // Tear the errored socket down explicitly: do not rely on the
        // implicit close that follows 'error', so no half-open handle can
        // linger in the loop.
        socket.destroy();
        reject(new Error(`browser bridge connect failed: ${error.message}`));
        return;
      }
      finishClose(`browser bridge socket error: ${error.message}`);
    });

    socket.on('data', (chunk: Buffer) => {
      if (!settled) {
        handshakeBuffer =
          handshakeBuffer.length === 0 ? chunk : Buffer.concat([handshakeBuffer, chunk]);
        if (handshakeBuffer.length > MAX_HANDSHAKE_BYTES) {
          settled = true;
          clearTimeout(handshakeTimer);
          socket.destroy();
          reject(new Error('browser bridge handshake response is too large'));
          return;
        }
        const terminator = handshakeBuffer.indexOf('\r\n\r\n');
        if (terminator === -1) return;
        const headerText = handshakeBuffer.subarray(0, terminator).toString('latin1');
        const rest = Buffer.from(handshakeBuffer.subarray(terminator + 4));
        handshakeBuffer = Buffer.alloc(0);
        const lines = headerText.split('\r\n');
        const statusLine = lines[0] ?? '';
        if (!/^HTTP\/1\.[01] 101\b/u.test(statusLine)) {
          settled = true;
          clearTimeout(handshakeTimer);
          socket.destroy();
          reject(
            new Error(
              `browser bridge handshake was rejected (${statusLine || 'no status line'})`,
            ),
          );
          return;
        }
        const headers = new Map<string, string>();
        for (const line of lines.slice(1)) {
          const separator = line.indexOf(':');
          if (separator === -1) continue;
          headers.set(line.slice(0, separator).trim().toLowerCase(), line.slice(separator + 1).trim());
        }
        if (headers.get('sec-websocket-accept') !== expectedAcceptKey(key)) {
          settled = true;
          clearTimeout(handshakeTimer);
          socket.destroy();
          reject(new Error('browser bridge handshake accept key is invalid'));
          return;
        }
        settled = true;
        clearTimeout(handshakeTimer);
        handedOff = true;
        resolve({
          send(text: string): void {
            if (closed) return;
            socket.write(encodeWsText(text));
          },
          close(): void {
            if (closed) return;
            try {
              socket.write(encodeWsClose());
            } catch {
              // Closing over a broken pipe still ends in finishClose below.
            }
            finishClose('browser bridge socket closed by client');
          },
        });
        if (rest.length > 0) socket.emit('data', rest);
        return;
      }
      let frames;
      try {
        frames = parser.feed(chunk);
        for (const frame of frames) {
          const message = reassembler.accept(frame);
          if (!message) continue;
          if (message.opcode === WS_OPCODE_TEXT || message.opcode === WS_OPCODE_BINARY) {
            handlers.onMessage(message.payload.toString('utf8'));
          } else if (message.opcode === WS_OPCODE_PING) {
            socket.write(encodeWsPong(message.payload));
          } else if (message.opcode === WS_OPCODE_CLOSE) {
            finishClose('browser bridge sent a close frame');
            return;
          }
          // Pong frames need no action (they prove liveness to the server).
        }
      } catch (error) {
        if (error instanceof WsProtocolError) {
          finishClose(`browser bridge protocol error: ${error.message}`);
          return;
        }
        // Never rethrow out of an event callback: an uncaught exception in
        // the main process triggers Electron's modal error dialog, which
        // parks the whole process. Treat unknown frame errors as fatal for
        // the connection instead.
        finishClose(
          `browser bridge frame error: ${error instanceof Error ? error.message : String(error)}`,
        );
        return;
      }
    });

    socket.once('close', () => {
      if (!settled) {
        settled = true;
        clearTimeout(handshakeTimer);
        reject(new Error('browser bridge connection closed during handshake'));
        return;
      }
      finishClose('browser bridge connection closed');
    });

    socket.once('connect', () => {
      socket.write(
        [
          `GET ${requestPath} HTTP/1.1`,
          `Host: ${hostHeader}`,
          'Upgrade: websocket',
          'Connection: Upgrade',
          `Sec-WebSocket-Key: ${key}`,
          'Sec-WebSocket-Version: 13',
          `Authorization: Bearer ${token}`,
          '',
          '',
        ].join('\r\n'),
      );
    });
  });
}
