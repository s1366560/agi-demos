import {
  CloudSocketExecutionRegistry,
  assertCloudSocketFrame,
  type AuthorizedCloudSocket,
  type CloudSocketCloseDirective,
  type CloudSocketExecutionLease,
  type CloudSocketFrame,
  type VaultBoundCloudSocketInput,
} from './cloudSocketPolicy';
import type { ComputerUseCloudDeviceHooks } from './computerUseCloudDeviceBridge';

type CloudSocketBrokerFrame =
  | Readonly<{ binary: false; text: string }>
  | Readonly<{ binary: true; data: ArrayBuffer }>;

export type CloudSocketBrokerEvent =
  | Readonly<{ socketId: string; type: 'open'; protocol: 'memstack.auth' }>
  | Readonly<{
      socketId: string;
      type: 'message';
      frame: CloudSocketBrokerFrame;
    }>
  | Readonly<{ socketId: string; type: 'error'; reason: string }>
  | Readonly<{
      socketId: string;
      type: 'close';
      code: number;
      reason: string;
      wasClean: boolean;
    }>;

export type CloudSocketLike = {
  protocol: string;
  readyState: number;
  bufferedAmount: number;
  binaryType: string;
  onopen: (() => void) | null;
  onmessage: ((event: Readonly<{ data: unknown }>) => void) | null;
  onerror: (() => void) | null;
  onclose: ((event: Readonly<{ code: number; reason: string; wasClean: boolean }>) => void) | null;
  send(data: string | ArrayBuffer): void;
  close(code?: number, reason?: string): void;
};

export type DesktopCloudSocketBrokerDependencies = Readonly<{
  computerUse?: ComputerUseCloudDeviceHooks;
  authorize(input: unknown): Promise<AuthorizedCloudSocket>;
  createSocket(url: string, protocols: readonly string[]): CloudSocketLike;
  emit(ownerId: number, event: CloudSocketBrokerEvent): void;
  perOwnerLimit?: number;
  globalLimit?: number;
}>;

type ActiveBrokerSocket = {
  ownerId: number;
  socketId: string;
  policy: AuthorizedCloudSocket;
  socket: CloudSocketLike;
  lease: CloudSocketExecutionLease;
  receiveQueue: Promise<void>;
  heartbeatTimer?: ReturnType<typeof setInterval>;
  lastInboundAt: number;
  finalized: boolean;
};

const SOCKET_ID = /^[A-Za-z0-9_-]{16,128}$/u;
const OPEN_KEYS = new Set(['socketId', 'request']);
const SEND_KEYS = new Set(['socketId', 'frame']);
const CLOSE_KEYS = new Set(['socketId', 'code', 'reason']);
const TEXT_FRAME_KEYS = new Set(['binary', 'text']);
const BINARY_FRAME_KEYS = new Set(['binary', 'data']);
const SOCKET_OPEN = 1;
const AGENT_HEARTBEAT_INTERVAL_MS = 20_000;
const AGENT_RESPONSE_TIMEOUT_MS = 60_000;

export class DesktopCloudSocketBroker {
  readonly #authorize: DesktopCloudSocketBrokerDependencies['authorize'];
  readonly #createSocket: DesktopCloudSocketBrokerDependencies['createSocket'];
  readonly #emit: DesktopCloudSocketBrokerDependencies['emit'];
  readonly #registry: CloudSocketExecutionRegistry;
  readonly #computerUse?: ComputerUseCloudDeviceHooks;
  readonly #connections = new Map<string, ActiveBrokerSocket>();

  constructor(dependencies: DesktopCloudSocketBrokerDependencies) {
    this.#authorize = dependencies.authorize;
    this.#createSocket = dependencies.createSocket;
    this.#emit = dependencies.emit;
    this.#registry = new CloudSocketExecutionRegistry({
      perOwnerLimit: dependencies.perOwnerLimit ?? 8,
      globalLimit: dependencies.globalLimit ?? 32,
    });
    this.#computerUse = dependencies.computerUse;
  }

  get activeCount(): number {
    return this.#registry.activeCount;
  }

  async open(ownerId: number, input: unknown): Promise<void> {
    const request = parseOpenInput(input);
    const policy = await this.#authorize(request.request);
    let connection: ActiveBrokerSocket | null = null;
    let pendingDirective: CloudSocketCloseDirective | null = null;
    const lease = this.#registry.begin(ownerId, request.socketId, policy, (directive) => {
      if (connection) {
        this.#closeFromRegistry(connection, directive);
      } else {
        pendingDirective = directive;
      }
    });
    let socket: CloudSocketLike;
    try {
      socket = this.#createSocket(policy.url, policy.protocols);
    } catch {
      lease.release();
      throw new Error('cloud socket connection failed');
    }
    connection = {
      ownerId,
      socketId: request.socketId,
      policy,
      socket,
      lease,
      receiveQueue: Promise.resolve(),
      lastInboundAt: Date.now(),
      finalized: false,
    };
    this.#connections.set(request.socketId, connection);
    socket.binaryType = 'arraybuffer';
    socket.onopen = () => this.#handleOpen(connection as ActiveBrokerSocket);
    socket.onmessage = (event) => this.#handleMessage(connection as ActiveBrokerSocket, event.data);
    socket.onerror = () => this.#handleTransportError(connection as ActiveBrokerSocket);
    socket.onclose = (event) => this.#handleRemoteClose(connection as ActiveBrokerSocket, event);
    if (pendingDirective) this.#closeFromRegistry(connection, pendingDirective);
  }

  async send(ownerId: number, input: unknown): Promise<void> {
    return this.#sendFrame(ownerId, input, false);
  }
  async #sendFrame(ownerId: number, input: unknown, device: boolean): Promise<void> {
    const request = parseSendInput(input);
    if (!device && !request.frame.binary) {
      let message: unknown;
      try {
        message = JSON.parse(request.frame.text);
      } catch {
        message = null;
      }
      if (
        message !== null &&
        typeof message === 'object' &&
        !Array.isArray(message) &&
        ['computer_use_device', 'computer_use_result', 'computer_use_media', 'computer_use_control_state'].includes(
          (message as Record<string, unknown>).type as string
        )
      )
        throw new Error('cua_cloud_renderer_frame_forbidden');
    }
    const connection = this.#owned(ownerId, request.socketId);
    if (!connection || connection.socket.readyState !== SOCKET_OPEN) {
      throw new Error('cloud socket is unavailable');
    }
    const frame = policyFrame(request.frame);
    assertNoBinaryCredentialReflection(connection.policy, request.frame);
    const reservation = this.#registry.reserveFrame(
      ownerId,
      request.socketId,
      'client_to_server',
      frame
    );
    try {
      connection.socket.send(
        request.frame.binary ? request.frame.data.slice(0) : request.frame.text
      );
      if (connection.socket.bufferedAmount > connection.policy.limits.max_aggregate_bytes) {
        this.#registry.close(
          ownerId,
          request.socketId,
          1009,
          'cloud socket aggregate is too large'
        );
        throw new Error('cloud socket aggregate is too large');
      }
      this.#registry.touch(ownerId, request.socketId);
    } catch (error) {
      if (this.#connections.get(request.socketId) === connection) {
        this.#registry.close(ownerId, request.socketId, 1011, 'cloud socket transport failed');
      }
      throw error instanceof Error ? error : new Error('cloud socket transport failed');
    } finally {
      reservation.release();
    }
  }

  async close(ownerId: number, input: unknown): Promise<void> {
    const request = parseCloseInput(input);
    if (!this.#registry.close(ownerId, request.socketId, request.code, request.reason)) {
      throw new Error('cloud socket is unavailable');
    }
  }

  cancelOwner(ownerId: number): number {
    return this.#registry.cancelOwner(ownerId);
  }

  cancelAll(): number {
    return this.#registry.cancelAll();
  }

  #owned(ownerId: number, socketId: string): ActiveBrokerSocket | null {
    const connection = this.#connections.get(socketId);
    return connection?.ownerId === ownerId && !connection.finalized ? connection : null;
  }

  #handleOpen(connection: ActiveBrokerSocket): void {
    if (connection.finalized || this.#connections.get(connection.socketId) !== connection) return;
    if (connection.socket.protocol !== 'memstack.auth') {
      this.#registry.close(
        connection.ownerId,
        connection.socketId,
        1008,
        'cloud socket protocol negotiation failed'
      );
      return;
    }
    if (!this.#registry.markConnected(connection.ownerId, connection.socketId)) return;
    this.#startAgentKeepalive(connection);
    const opened = () =>
      this.#safeEmit(connection.ownerId, {
        socketId: connection.socketId,
        type: 'open',
        protocol: 'memstack.auth',
      });
    if (connection.policy.kind === 'agent' && this.#computerUse) {
      const computerUse = this.#computerUse;
      // A server may send its connected frame before native device discovery finishes.
      // Serialize initialization and Open with inbound delivery so the renderer sees Open first.
      connection.receiveQueue = connection.receiveQueue.then(async () => {
        if (connection.finalized) return;
        try {
          await computerUse.opened(connection.socketId, connection.policy.scope, (value) =>
            this.#sendDeviceFrame(connection, value)
          );
        } catch {
          // Ordinary cloud chat remains available when this optional device cannot register.
        }
        if (!connection.finalized) opened();
      });
    } else {
      opened();
    }
  }

  #handleMessage(connection: ActiveBrokerSocket, data: unknown): void {
    if (connection.finalized || this.#connections.get(connection.socketId) !== connection) return;
    let reservation;
    try {
      // Charge bytes before queueing, including while native registration is pending.
      reservation = this.#registry.reserveFrame(
        connection.ownerId,
        connection.socketId,
        'server_to_client',
        inboundPolicyFrame(data)
      );
    } catch {
      this.#registry.close(
        connection.ownerId,
        connection.socketId,
        1008,
        'cloud socket policy violation'
      );
      return;
    }
    connection.receiveQueue = connection.receiveQueue
      .then(() => {
        if (connection.finalized) return;
        const parsed = inboundFrame(data);
        if (parsed instanceof Promise) {
          return parsed.then((frame) => this.#emitInboundFrame(connection, frame));
        }
        this.#emitInboundFrame(connection, parsed);
      })
      .catch(() => {
        if (this.#connections.get(connection.socketId) === connection) {
          this.#registry.close(
            connection.ownerId,
            connection.socketId,
            1008,
            'cloud socket policy violation'
          );
        }
      })
      .finally(() => reservation.release());
  }

  #emitInboundFrame(connection: ActiveBrokerSocket, frame: CloudSocketBrokerFrame): void {
    if (connection.finalized) return;
    assertNoBinaryCredentialReflection(connection.policy, frame);
    connection.lastInboundAt = Date.now();
    if (
      !frame.binary &&
      connection.policy.kind === 'agent' &&
      this.#computerUse?.receive(
        connection.socketId,
        connection.policy.scope,
        frame.text,
        (value) => this.#sendDeviceFrame(connection, value)
      )
    ) {
      this.#registry.touch(connection.ownerId, connection.socketId);
      return;
    }
    this.#safeEmit(connection.ownerId, {
      socketId: connection.socketId,
      type: 'message',
      frame,
    });
    this.#registry.touch(connection.ownerId, connection.socketId);
  }

  #handleTransportError(connection: ActiveBrokerSocket): void {
    if (connection.finalized || this.#connections.get(connection.socketId) !== connection) return;
    this.#safeEmit(connection.ownerId, {
      socketId: connection.socketId,
      type: 'error',
      reason: 'cloud_socket_transport_error',
    });
    this.#registry.close(
      connection.ownerId,
      connection.socketId,
      1011,
      'cloud socket transport failed'
    );
  }

  #startAgentKeepalive(connection: ActiveBrokerSocket): void {
    if (connection.policy.kind !== 'agent') return;
    connection.lastInboundAt = Date.now();
    // Native device waits outlive renderer painting and background timer throttling.
    // Only valid incoming frames prove liveness; our own heartbeats cannot renew it.
    connection.heartbeatTimer = setInterval(() => {
      if (connection.finalized) return;
      if (Date.now() - connection.lastInboundAt >= AGENT_RESPONSE_TIMEOUT_MS) {
        this.#registry.close(
          connection.ownerId,
          connection.socketId,
          4001,
          'cloud socket response timed out'
        );
        return;
      }
      void this.#sendFrame(connection.ownerId, {
        socketId: connection.socketId,
        frame: { binary: false, text: '{"type":"heartbeat"}' },
      }, false).catch(() => this.#handleTransportError(connection));
    }, AGENT_HEARTBEAT_INTERVAL_MS);
    connection.heartbeatTimer.unref?.();
  }

  #handleRemoteClose(
    connection: ActiveBrokerSocket,
    event: Readonly<{ code: number; reason: string; wasClean: boolean }>
  ): void {
    if (connection.finalized || this.#connections.get(connection.socketId) !== connection) return;
    this.#registry.complete(connection.ownerId, connection.socketId);
    const code = validRemoteCloseCode(event.code) ? event.code : 1006;
    this.#finalize(connection, code, '', event.wasClean === true && code === 1000);
  }

  #closeFromRegistry(connection: ActiveBrokerSocket, directive: CloudSocketCloseDirective): void {
    if (connection.finalized) return;
    const reason = sanitizedDirectiveReason(directive);
    if (directive.code !== 1000 && directive.code !== 1001) {
      this.#safeEmit(connection.ownerId, {
        socketId: connection.socketId,
        type: 'error',
        reason,
      });
    }
    try {
      connection.socket.close(directive.code, reason);
    } catch {
      // The sanitized close event below remains authoritative for renderer cleanup.
    }
    this.#finalize(connection, directive.code, reason, directive.code === 1000);
  }

  #finalize(connection: ActiveBrokerSocket, code: number, reason: string, wasClean: boolean): void {
    if (connection.finalized) return;
    connection.finalized = true;
    if (connection.heartbeatTimer) clearInterval(connection.heartbeatTimer);
    if (connection.policy.kind === 'agent')
      this.#computerUse?.closed(connection.socketId, connection.policy.scope);
    this.#connections.delete(connection.socketId);
    connection.socket.onopen = null;
    connection.socket.onmessage = null;
    connection.socket.onerror = null;
    connection.socket.onclose = null;
    connection.lease.release();
    this.#safeEmit(connection.ownerId, {
      socketId: connection.socketId,
      type: 'close',
      code,
      reason,
      wasClean,
    });
  }

  async #sendDeviceFrame(
    connection: ActiveBrokerSocket,
    value: Record<string, unknown>
  ): Promise<void> {
    while (
      !connection.finalized &&
      connection.socket.bufferedAmount > connection.policy.limits.max_aggregate_bytes / 2
    ) {
      await new Promise<void>((resolve) => setTimeout(resolve, 20));
    }
    if (connection.finalized) throw new Error('cua_cloud_connection_closed');
    await this.#sendFrame(
      connection.ownerId,
      {
        socketId: connection.socketId,
        frame: { binary: false, text: JSON.stringify(value) },
      },
      true
    );
  }

  #safeEmit(ownerId: number, event: CloudSocketBrokerEvent): void {
    try {
      this.#emit(ownerId, event);
    } catch {
      this.#registry.cancelOwner(ownerId);
    }
  }
}

function parseOpenInput(
  input: unknown
): Readonly<{ socketId: string; request: VaultBoundCloudSocketInput }> {
  const record = exactRecord(input, OPEN_KEYS, 'cloud socket open input is invalid');
  return Object.freeze({
    socketId: validSocketId(record.socketId),
    request: record.request as VaultBoundCloudSocketInput,
  });
}

function parseSendInput(
  input: unknown
): Readonly<{ socketId: string; frame: CloudSocketBrokerFrame }> {
  const record = exactRecord(input, SEND_KEYS, 'cloud socket send input is invalid');
  return Object.freeze({
    socketId: validSocketId(record.socketId),
    frame: parseFrame(record.frame),
  });
}

function parseCloseInput(
  input: unknown
): Readonly<{ socketId: string; code: number; reason: string }> {
  const record = exactRecord(input, CLOSE_KEYS, 'cloud socket close input is invalid');
  if (
    !Number.isSafeInteger(record.code) ||
    (record.code !== 1000 && (Number(record.code) < 3000 || Number(record.code) > 4999))
  ) {
    throw new Error('cloud socket close code is invalid');
  }
  if (
    typeof record.reason !== 'string' ||
    new TextEncoder().encode(record.reason).byteLength > 123
  ) {
    throw new Error('cloud socket close reason is invalid');
  }
  return Object.freeze({
    socketId: validSocketId(record.socketId),
    code: Number(record.code),
    reason: record.reason,
  });
}

function parseFrame(input: unknown): CloudSocketBrokerFrame {
  const record = asRecord(input, 'cloud socket frame is invalid');
  if (
    record.binary === false &&
    exactKeys(record, TEXT_FRAME_KEYS) &&
    typeof record.text === 'string'
  ) {
    return Object.freeze({ binary: false, text: record.text });
  }
  if (
    record.binary === true &&
    exactKeys(record, BINARY_FRAME_KEYS) &&
    record.data instanceof ArrayBuffer
  ) {
    return Object.freeze({ binary: true, data: record.data.slice(0) });
  }
  throw new Error('cloud socket frame is invalid');
}

function inboundFrame(input: unknown): CloudSocketBrokerFrame | Promise<CloudSocketBrokerFrame> {
  if (typeof input === 'string') return Object.freeze({ binary: false, text: input });
  if (input instanceof ArrayBuffer) {
    return Object.freeze({ binary: true, data: input.slice(0) });
  }
  if (ArrayBuffer.isView(input)) {
    const bytes = new Uint8Array(input.byteLength);
    bytes.set(new Uint8Array(input.buffer, input.byteOffset, input.byteLength));
    return Object.freeze({ binary: true, data: bytes.buffer });
  }
  if (input instanceof Blob) {
    return input
      .arrayBuffer()
      .then((data) => Object.freeze({ binary: true, data }) as CloudSocketBrokerFrame);
  }
  throw new Error('cloud socket frame is invalid');
}

function inboundPolicyFrame(input: unknown): CloudSocketFrame {
  if (typeof input === 'string')
    return {
      binary: false,
      byteLength: new TextEncoder().encode(input).byteLength,
      text: input,
    };
  if (input instanceof ArrayBuffer || ArrayBuffer.isView(input))
    return { binary: true, byteLength: input.byteLength };
  if (input instanceof Blob) return { binary: true, byteLength: input.size };
  throw new Error('cloud socket frame is invalid');
}

function policyFrame(frame: CloudSocketBrokerFrame): CloudSocketFrame {
  if (frame.binary) return Object.freeze({ binary: true, byteLength: frame.data.byteLength });
  return Object.freeze({
    binary: false,
    byteLength: new TextEncoder().encode(frame.text).byteLength,
    text: frame.text,
  });
}

function assertNoBinaryCredentialReflection(
  policy: AuthorizedCloudSocket,
  frame: CloudSocketBrokerFrame
): void {
  if (!frame.binary) {
    assertCloudSocketFrame(policy, 'server_to_client', policyFrame(frame));
    return;
  }
  const credential = policy.protocols[1];
  if (credential && Buffer.from(frame.data).includes(Buffer.from(credential, 'utf8'))) {
    throw new Error('cloud socket frame contains protected credential');
  }
}

function sanitizedDirectiveReason(directive: CloudSocketCloseDirective): string {
  if (directive.code === 1000) return '';
  if (directive.code === 1001) return 'cloud_socket_cancelled';
  if (directive.code === 1009) return 'cloud_socket_message_too_large';
  if (directive.code === 4000) return 'cloud_socket_connect_timeout';
  if (directive.code === 4001) return 'cloud_socket_idle_timeout';
  if (directive.code === 1011) return 'cloud_socket_transport_error';
  return 'cloud_socket_policy_violation';
}

function validRemoteCloseCode(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 1000 && Number(value) <= 4999;
}

function validSocketId(value: unknown): string {
  if (typeof value !== 'string' || !SOCKET_ID.test(value)) {
    throw new Error('cloud socket id is invalid');
  }
  return value;
}

function exactRecord(
  input: unknown,
  allowed: ReadonlySet<string>,
  message: string
): Record<string, unknown> {
  const record = asRecord(input, message);
  if (!exactKeys(record, allowed)) throw new Error(message);
  return record;
}

function asRecord(input: unknown, message: string): Record<string, unknown> {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) {
    throw new Error(message);
  }
  return input as Record<string, unknown>;
}

function exactKeys(record: Record<string, unknown>, allowed: ReadonlySet<string>): boolean {
  const keys = Object.keys(record);
  return keys.length === allowed.size && keys.every((key) => allowed.has(key));
}
