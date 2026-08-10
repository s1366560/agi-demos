export const CLOUD_SOCKET_CONNECTING = 0 as const;
export const CLOUD_SOCKET_OPEN = 1 as const;
export const CLOUD_SOCKET_CLOSING = 2 as const;
export const CLOUD_SOCKET_CLOSED = 3 as const;

export type CloudSocketBridgeReadyState =
  | typeof CLOUD_SOCKET_CONNECTING
  | typeof CLOUD_SOCKET_OPEN
  | typeof CLOUD_SOCKET_CLOSING
  | typeof CLOUD_SOCKET_CLOSED;

export type CloudSocketBridgeRequest = Readonly<{
  kind: 'agent' | 'terminal' | 'voice';
  url: string;
  scope: Readonly<{
    tenant_id: string;
    project_id: string;
    workspace_id: string | null;
    conversation_id: string | null;
  }>;
  terminal?: Readonly<{
    session_id: string;
    resume_token: string | null;
  }>;
}>;

export type CloudSocketBridgeOutboundFrame =
  | Readonly<{ binary: false; text: string }>
  | Readonly<{ binary: true; data: ArrayBuffer }>;

export type CloudSocketBridgeTransportEvent =
  | Readonly<{ socketId: string; type: 'open'; protocol: 'memstack.auth' }>
  | Readonly<{
      socketId: string;
      type: 'message';
      frame: CloudSocketBridgeOutboundFrame;
    }>
  | Readonly<{ socketId: string; type: 'error'; reason: string }>
  | Readonly<{
      socketId: string;
      type: 'close';
      code: number;
      reason: string;
      wasClean: boolean;
    }>;

export type CloudSocketBridgeTransport = Readonly<{
  subscribe(listener: (event: unknown) => void): () => void;
  open(input: Readonly<{ socketId: string; request: CloudSocketBridgeRequest }>): Promise<void>;
  send(
    input: Readonly<{
      socketId: string;
      frame: CloudSocketBridgeOutboundFrame;
    }>
  ): Promise<void>;
  close(input: Readonly<{ socketId: string; code: number; reason: string }>): Promise<void>;
}>;

export type CloudSocketOpenEvent = Readonly<{
  type: 'open';
  target: CloudSocketBridge;
}>;
export type CloudSocketMessageEvent = Readonly<{
  type: 'message';
  target: CloudSocketBridge;
  data: string | ArrayBuffer;
}>;
export type CloudSocketErrorEvent = Readonly<{
  type: 'error';
  target: CloudSocketBridge;
  reason: string;
}>;
export type CloudSocketCloseEvent = Readonly<{
  type: 'close';
  target: CloudSocketBridge;
  code: number;
  reason: string;
  wasClean: boolean;
}>;

type BridgeEventMap = {
  open: CloudSocketOpenEvent;
  message: CloudSocketMessageEvent;
  error: CloudSocketErrorEvent;
  close: CloudSocketCloseEvent;
};

type BridgeEventType = keyof BridgeEventMap;
type BridgeListener<K extends BridgeEventType> = (event: BridgeEventMap[K]) => void;

export type CloudSocketBridgeOptions = Readonly<{
  socketId?: string;
}>;

type DesktopCloudSocketBridge = Readonly<{
  runtime: 'electron';
  core: Readonly<{
    invoke(command: string, args?: unknown): Promise<unknown>;
  }>;
  events: Readonly<{
    onCloudSocketEvent(listener: (event: unknown) => void): () => void;
  }>;
}>;

const SOCKET_ID = /^[A-Za-z0-9_-]{16,128}$/u;
const OPEN_KEYS = new Set(['socketId', 'type', 'protocol']);
const MESSAGE_KEYS = new Set(['socketId', 'type', 'frame']);
const ERROR_KEYS = new Set(['socketId', 'type', 'reason']);
const CLOSE_KEYS = new Set(['socketId', 'type', 'code', 'reason', 'wasClean']);
const TEXT_FRAME_KEYS = new Set(['binary', 'text']);
const BINARY_FRAME_KEYS = new Set(['binary', 'data']);

export function createCloudSocketBridge(
  request: CloudSocketBridgeRequest,
  transport: CloudSocketBridgeTransport,
  options: CloudSocketBridgeOptions = {}
): CloudSocketBridge {
  return new CloudSocketBridge(request, transport, options.socketId ?? createSocketId());
}

export function desktopCloudSocketTransport(): CloudSocketBridgeTransport | null {
  if (typeof window === 'undefined') return null;
  const desktop = (window as unknown as { __MEMSTACK_DESKTOP__?: DesktopCloudSocketBridge })
    .__MEMSTACK_DESKTOP__;
  if (
    desktop?.runtime !== 'electron' ||
    typeof desktop.core?.invoke !== 'function' ||
    typeof desktop.events?.onCloudSocketEvent !== 'function'
  ) {
    return null;
  }
  return Object.freeze({
    subscribe(listener: (event: unknown) => void): () => void {
      return desktop.events.onCloudSocketEvent(listener);
    },
    async open(input): Promise<void> {
      await desktop.core.invoke('cloud_socket_open', input);
    },
    async send(input): Promise<void> {
      await desktop.core.invoke('cloud_socket_send', input);
    },
    async close(input): Promise<void> {
      await desktop.core.invoke('cloud_socket_close', input);
    },
  });
}

export class CloudSocketBridge {
  readonly url: string;
  readonly extensions = '';
  binaryType: 'arraybuffer' = 'arraybuffer';
  protocol = '';
  readyState: CloudSocketBridgeReadyState = CLOUD_SOCKET_CONNECTING;
  bufferedAmount = 0;
  onopen: BridgeListener<'open'> | null = null;
  onmessage: BridgeListener<'message'> | null = null;
  onerror: BridgeListener<'error'> | null = null;
  onclose: BridgeListener<'close'> | null = null;

  readonly #socketId: string;
  readonly #transport: CloudSocketBridgeTransport;
  readonly #listeners: {
    [K in BridgeEventType]: Set<BridgeListener<K>>;
  } = {
    open: new Set(),
    message: new Set(),
    error: new Set(),
    close: new Set(),
  };
  #unsubscribe: (() => void) | null = null;

  constructor(
    request: CloudSocketBridgeRequest,
    transport: CloudSocketBridgeTransport,
    socketId: string
  ) {
    if (!SOCKET_ID.test(socketId)) throw new Error('cloud_socket_bridge_id_invalid');
    this.#socketId = socketId;
    this.#transport = transport;
    this.url = request.url;
    this.#unsubscribe = transport.subscribe((event) => this.#receive(event));
    void transport
      .open(Object.freeze({ socketId, request }))
      .catch(() => this.#failClosed('cloud_socket_bridge_open_failed'));
  }

  addEventListener<K extends BridgeEventType>(type: K, listener: BridgeListener<K>): void {
    (this.#listeners[type] as Set<BridgeListener<K>>).add(listener);
  }

  removeEventListener<K extends BridgeEventType>(type: K, listener: BridgeListener<K>): void {
    (this.#listeners[type] as Set<BridgeListener<K>>).delete(listener);
  }

  send(data: string | ArrayBuffer | ArrayBufferView): void {
    if (this.readyState !== CLOUD_SOCKET_OPEN) {
      throw domException('The cloud socket is not open.', 'InvalidStateError');
    }
    const frame = outboundFrame(data);
    const byteLength = frame.binary
      ? frame.data.byteLength
      : new TextEncoder().encode(frame.text).byteLength;
    this.bufferedAmount += byteLength;
    void this.#transport
      .send(Object.freeze({ socketId: this.#socketId, frame }))
      .then(() => {
        this.bufferedAmount = Math.max(0, this.bufferedAmount - byteLength);
      })
      .catch(() => {
        this.bufferedAmount = Math.max(0, this.bufferedAmount - byteLength);
        this.#failClosed('cloud_socket_bridge_send_failed');
      });
  }

  close(code = 1000, reason = ''): void {
    validateClose(code, reason);
    if (this.readyState === CLOUD_SOCKET_CLOSING || this.readyState === CLOUD_SOCKET_CLOSED) return;
    this.readyState = CLOUD_SOCKET_CLOSING;
    void this.#transport
      .close(Object.freeze({ socketId: this.#socketId, code, reason }))
      .catch(() => this.#failClosed('cloud_socket_bridge_close_failed'));
  }

  #receive(input: unknown): void {
    if (!isRecord(input) || input.socketId !== this.#socketId) return;
    const event = decodeTransportEvent(input);
    if (!event) {
      this.#failClosed('cloud_socket_bridge_event_invalid');
      return;
    }
    if (this.readyState === CLOUD_SOCKET_CLOSED) return;
    if (event.type === 'open') {
      if (this.readyState !== CLOUD_SOCKET_CONNECTING) {
        this.#failClosed('cloud_socket_bridge_event_invalid');
        return;
      }
      this.protocol = event.protocol;
      this.readyState = CLOUD_SOCKET_OPEN;
      this.#dispatch('open', Object.freeze({ type: 'open', target: this }));
      return;
    }
    if (event.type === 'message') {
      if (this.readyState !== CLOUD_SOCKET_OPEN) {
        this.#failClosed('cloud_socket_bridge_event_invalid');
        return;
      }
      const data = event.frame.binary ? event.frame.data.slice(0) : event.frame.text;
      this.#dispatch('message', Object.freeze({ type: 'message', target: this, data }));
      return;
    }
    if (event.type === 'error') {
      this.#dispatch('error', Object.freeze({ type: 'error', target: this, reason: event.reason }));
      return;
    }
    this.#finishClose(event.code, event.reason, event.wasClean);
  }

  #failClosed(reason: string): void {
    if (this.readyState === CLOUD_SOCKET_CLOSED) return;
    const shouldRequestClose = this.readyState !== CLOUD_SOCKET_CLOSING;
    this.readyState = CLOUD_SOCKET_CLOSED;
    this.bufferedAmount = 0;
    this.#dispatch('error', Object.freeze({ type: 'error', target: this, reason }));
    if (shouldRequestClose) {
      void this.#transport
        .close(Object.freeze({ socketId: this.#socketId, code: 1008, reason }))
        .catch(() => undefined);
    }
    this.#unsubscribe?.();
    this.#unsubscribe = null;
    this.#dispatch(
      'close',
      Object.freeze({
        type: 'close',
        target: this,
        code: 1006,
        reason,
        wasClean: false,
      })
    );
  }

  #finishClose(code: number, reason: string, wasClean: boolean): void {
    this.readyState = CLOUD_SOCKET_CLOSED;
    this.bufferedAmount = 0;
    this.#unsubscribe?.();
    this.#unsubscribe = null;
    this.#dispatch('close', Object.freeze({ type: 'close', target: this, code, reason, wasClean }));
  }

  #dispatch<K extends BridgeEventType>(type: K, event: BridgeEventMap[K]): void {
    const propertyListener = this[`on${type}`] as BridgeListener<K> | null;
    if (propertyListener) invokeListener(propertyListener, event);
    for (const listener of [...(this.#listeners[type] as Set<BridgeListener<K>>)]) {
      invokeListener(listener, event);
    }
  }
}

function outboundFrame(
  data: string | ArrayBuffer | ArrayBufferView
): CloudSocketBridgeOutboundFrame {
  if (typeof data === 'string') return Object.freeze({ binary: false, text: data });
  if (data instanceof ArrayBuffer) {
    return Object.freeze({ binary: true, data: data.slice(0) });
  }
  if (ArrayBuffer.isView(data)) {
    const bytes = new Uint8Array(data.byteLength);
    bytes.set(new Uint8Array(data.buffer, data.byteOffset, data.byteLength));
    return Object.freeze({ binary: true, data: bytes.buffer });
  }
  throw domException('Unsupported cloud socket payload.', 'TypeError');
}

function decodeTransportEvent(
  input: Record<string, unknown>
): CloudSocketBridgeTransportEvent | null {
  if (input.type === 'open') {
    return exactEventKeys(input, OPEN_KEYS) && input.protocol === 'memstack.auth'
      ? Object.freeze({
          socketId: input.socketId as string,
          type: 'open',
          protocol: 'memstack.auth',
        })
      : null;
  }
  if (input.type === 'message') {
    const frame = decodeFrame(input.frame);
    return exactEventKeys(input, MESSAGE_KEYS) && frame
      ? Object.freeze({
          socketId: input.socketId as string,
          type: 'message',
          frame,
        })
      : null;
  }
  if (input.type === 'error') {
    return exactEventKeys(input, ERROR_KEYS) && validReason(input.reason)
      ? Object.freeze({
          socketId: input.socketId as string,
          type: 'error',
          reason: input.reason as string,
        })
      : null;
  }
  if (input.type === 'close') {
    return exactEventKeys(input, CLOSE_KEYS) &&
      validCloseEventCode(input.code) &&
      validReason(input.reason) &&
      typeof input.wasClean === 'boolean'
      ? Object.freeze({
          socketId: input.socketId as string,
          type: 'close',
          code: input.code as number,
          reason: input.reason as string,
          wasClean: input.wasClean,
        })
      : null;
  }
  return null;
}

function decodeFrame(input: unknown): CloudSocketBridgeOutboundFrame | null {
  if (!isRecord(input)) return null;
  if (
    input.binary === false &&
    exactObjectKeys(input, TEXT_FRAME_KEYS) &&
    typeof input.text === 'string'
  ) {
    return Object.freeze({ binary: false, text: input.text });
  }
  if (
    input.binary === true &&
    exactObjectKeys(input, BINARY_FRAME_KEYS) &&
    input.data instanceof ArrayBuffer
  ) {
    return Object.freeze({ binary: true, data: input.data.slice(0) });
  }
  return null;
}

function validateClose(code: number, reason: string): void {
  if (code !== 1000 && (code < 3000 || code > 4999)) {
    throw domException('The cloud socket close code is invalid.', 'InvalidAccessError');
  }
  if (new TextEncoder().encode(reason).byteLength > 123) {
    throw domException('The cloud socket close reason is too long.', 'SyntaxError');
  }
}

function validCloseEventCode(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 1000 && Number(value) <= 4999;
}

function validReason(value: unknown): value is string {
  return typeof value === 'string' && new TextEncoder().encode(value).byteLength <= 123;
}

function exactEventKeys(record: Record<string, unknown>, allowed: ReadonlySet<string>): boolean {
  return (
    typeof record.socketId === 'string' &&
    SOCKET_ID.test(record.socketId) &&
    exactObjectKeys(record, allowed)
  );
}

function exactObjectKeys(record: Record<string, unknown>, allowed: ReadonlySet<string>): boolean {
  const keys = Object.keys(record);
  return keys.length === allowed.size && keys.every((key) => allowed.has(key));
}

function createSocketId(): string {
  const id = globalThis.crypto?.randomUUID?.();
  if (!id) throw new Error('cloud_socket_bridge_id_unavailable');
  return id;
}

function invokeListener<K extends BridgeEventType>(
  listener: BridgeListener<K>,
  event: BridgeEventMap[K]
): void {
  try {
    listener(event);
  } catch {
    // Event listener failures do not mutate the native connection lifecycle.
  }
}

function domException(message: string, name: string): DOMException {
  return new DOMException(message, name);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
