import { runWebOperationV2, type WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';
import { getAuthToken } from '@/utils/tokenResolver';
import { createWebSocketAuthProtocols, createWebSocketUrl } from './client/urlUtils';
import { attachWatchdog, type Watchdog } from './client/wsWatchdog';
import type { WebSocketStatus } from './unifiedEventService';

interface ConnectionCallbacks {
  owner: object;
  beforeOpen: Promise<unknown>;
  sessionId: string;
  status(status: WebSocketStatus): void;
  opened(): void;
  message(event: MessageEvent): void;
  retired(): void;
}

/** One admitted owner retains every socket attempt until the last actual close. */
export class UnifiedEventConnectionV2 {
  ready!: Promise<void>;
  readonly done: Promise<void>;
  private readonly controller = new AbortController();
  private resolveReady!: () => void;
  private rejectReady!: (error: unknown) => void;
  private resolveClosed!: () => void;
  private operation?: WebOperationContextV2;
  private socket: WebSocket | null = null;
  private token = '';
  private stopping = false;
  private closeFailure: { error: unknown } | undefined;
  private attempts = 0;
  private reconnect: ReturnType<typeof setTimeout> | undefined;
  private heartbeat: ReturnType<typeof setInterval> | undefined;
  private watchdog: Watchdog | undefined;

  constructor(private readonly callbacks: ConnectionCallbacks) {
    this.resetReady();
    this.done = runWebOperationV2(
      async (operation) => {
        this.operation = operation;
        operation.check();
        if (operation.owner !== callbacks.owner) throw new Error('unified_event_owner_changed');
        this.token = getAuthToken() ?? '';
        if (!this.token) throw new Error('No authentication token');
        const closed = new Promise<void>((resolve) => {
          this.resolveClosed = resolve;
        });
        const abort = () => this.retire();
        operation.signal.addEventListener('abort', abort, { once: true });
        try {
          await callbacks.beforeOpen;
          operation.check();
          this.open();
          await closed;
          if (this.closeFailure) throw this.closeFailure.error;
        } finally {
          operation.signal.removeEventListener('abort', abort);
          this.clearTimers();
          this.token = '';
        }
      },
      { signal: this.controller.signal }
    ).catch((error) => {
      this.rejectReady(error);
      throw error;
    });
    void this.done.catch(() => undefined);
    void this.done.finally(() => callbacks.retired()).catch(() => undefined);
  }

  private resetReady(): void {
    this.ready = new Promise((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });
    void this.ready.catch(() => undefined);
  }

  isConnected(): boolean {
    return this.live() && this.socket?.readyState === WebSocket.OPEN;
  }
  send(message: Record<string, unknown>): boolean {
    if (!this.isConnected()) return false;
    this.socket!.send(JSON.stringify(message));
    return true;
  }
  stop(): Promise<void> {
    this.controller.abort();
    this.retire();
    return this.done.catch((error) => {
      if (!(error instanceof DOMException && error.name === 'AbortError')) throw error;
    });
  }
  private live(): boolean {
    if (this.stopping || !this.operation) return false;
    try {
      this.operation.check();
      return true;
    } catch {
      return false;
    }
  }
  private clearTimers(): void {
    if (this.reconnect !== undefined) clearTimeout(this.reconnect);
    if (this.heartbeat !== undefined) clearInterval(this.heartbeat);
    this.reconnect = undefined;
    this.heartbeat = undefined;
    this.watchdog?.stop();
    this.watchdog = undefined;
  }
  private retire(): void {
    if (this.stopping) return;
    this.stopping = true;
    this.clearTimers();
    this.rejectReady(new DOMException('Unified event connection cancelled', 'AbortError'));
    this.callbacks.retired();
    if (!this.socket || this.socket.readyState === WebSocket.CLOSED) {
      this.resolveClosed?.();
    } else {
      // onclose settles the retained operation; close() invocation alone is insufficient.
      this.closeSocket(this.socket);
    }
  }
  private closeSocket(socket: WebSocket): void {
    try {
      socket.close();
    } catch (error) {
      this.closeFailure ??= { error };
    }
  }

  private open(): void {
    if (!this.live()) {
      this.retire();
      return;
    }
    this.callbacks.status('connecting');
    if (!this.live()) {
      this.retire();
      return;
    }
    let socket: WebSocket;
    try {
      socket = new WebSocket(
        createWebSocketUrl('/agent/ws', { session_id: this.callbacks.sessionId }),
        createWebSocketAuthProtocols(this.token)
      );
    } catch (error) {
      this.rejectReady(error);
      this.callbacks.status('error');
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    this.watchdog = attachWatchdog(socket, { staleAfterMs: 90_000, label: 'UnifiedWS' });
    let opened = false;
    socket.onopen = () => {
      if (!this.live() || this.socket !== socket) {
        this.closeSocket(socket);
        return;
      }
      opened = true;
      this.attempts = 0;
      this.callbacks.status('connected');
      if (!this.live()) {
        this.retire();
        return;
      }
      this.heartbeat = setInterval(() => this.send({ type: 'heartbeat' }), 30_000);
      this.callbacks.opened();
      this.resolveReady();
    };
    socket.onmessage = (event) => {
      if (!this.live() || this.socket !== socket) return;
      this.watchdog?.notifyMessage();
      this.callbacks.message(event);
    };
    socket.onerror = () => {
      if (this.socket !== socket || this.stopping) return;
      this.callbacks.status('error');
      this.rejectReady(new Error('WebSocket error'));
      this.closeSocket(socket);
    };
    socket.onclose = (event) => {
      if (this.socket !== socket) return;
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      this.socket = null;
      this.clearTimers();
      if (!opened)
        this.rejectReady(
          new Error(`WebSocket closed before connection opened: ${String(event.code)}`)
        );
      if (this.stopping || !this.live()) {
        this.retire();
        this.resolveClosed();
        return;
      }
      this.callbacks.status('disconnected');
      this.scheduleReconnect();
    };
  }
  private scheduleReconnect(): void {
    if (!this.live()) {
      this.retire();
      return;
    }
    if (this.attempts >= 5) {
      this.retire();
      return;
    }
    this.resetReady();
    const delay = 1000 * 2 ** this.attempts++;
    this.reconnect = setTimeout(() => {
      this.reconnect = undefined;
      // Reconnect inside the admitted context, never through public connect().
      this.open();
    }, delay);
  }
}
