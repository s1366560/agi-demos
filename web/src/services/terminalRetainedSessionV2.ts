import {
  getWebOperationAvailabilityV2,
  runWebOperationV2,
  WebOperationCleanupErrorV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';
import { getAuthToken } from '@/utils/tokenResolver';

import { createWebSocketAuthProtocols, createWebSocketUrl } from './client/urlUtils';

export interface TerminalRetainedSessionOptionsV2 {
  readonly sandboxId: string;
  readonly projectId?: string | undefined;
  readonly sessionId?: string | undefined;
  readonly onConnect: (sessionId: string) => void;
  readonly onOutput: (data: string) => void;
  readonly onDisconnect: () => void;
  readonly onError: (error: Error) => void;
  readonly onAdmitted?:
    | ((operation: WebOperationContextV2) => undefined | (() => void | Promise<void>))
    | undefined;
}
function completion() {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  let settled = false;
  const promise = new Promise<void>((yes, no) => {
    resolve = () => {
      settled = true;
      yes();
    };
    reject = (error) => {
      settled = true;
      no(error);
    };
  });
  void promise.catch(() => undefined);
  return {
    promise,
    resolve,
    reject,
    get settled() {
      return settled;
    },
  };
}
const aborted = () => new DOMException('Terminal session retired', 'AbortError');
const isAbort = (error: unknown) => error instanceof DOMException && error.name === 'AbortError';
interface Attempt {
  socket: WebSocket;
  closed: ReturnType<typeof completion>;
  code: number;
  connected: boolean;
}
/** One terminal attachment and its reconnects retain a single admitted generation. */
export class TerminalRetainedSessionV2 {
  private readonly options: TerminalRetainedSessionOptionsV2;
  private readonly owner = getWebOperationAvailabilityV2().owner;
  private readonly controller = new AbortController();
  private active = true;
  private operation: WebOperationContextV2 | undefined;
  private task: Promise<void> | undefined;
  private ready = completion();
  private attempt: Attempt | undefined;
  private token = '';
  private sessionId: string | undefined;
  private retries = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private wakeTimer: (() => void) | undefined;
  private heartbeat: ReturnType<typeof setInterval> | undefined;
  private resourceCleanup: (() => void | Promise<void>) | undefined;
  private cleanupTask: Promise<void> | undefined;
  private readonly cleanupErrors: unknown[] = [];
  private businessError: Error | undefined;
  constructor(options: TerminalRetainedSessionOptionsV2) {
    this.options = Object.freeze({ ...options });
    this.sessionId = options.sessionId;
  }
  connect(): Promise<void> {
    if (!this.active) return Promise.reject(aborted());
    if (this.task) return this.ready.promise;
    this.token = getAuthToken() ?? '';
    this.task = runWebOperationV2(
      async (operation) => {
        this.operation = operation;
        let primary: { error: unknown } | undefined;
        const retire = () => {
          this.retire();
        };
        operation.signal.addEventListener('abort', retire, { once: true });
        try {
          this.check();
          if (!this.token) throw new Error('No auth token available');
          if (!this.options.sandboxId) throw new Error('Terminal sandbox is required');
          const cleanup = this.options.onAdmitted?.(operation);
          if (cleanup) {
            this.resourceCleanup = cleanup;
            if (!this.active) this.cleanupResources();
          }
          this.check();
          while (this.active) {
            this.check();
            const attempt = this.createAttempt();
            await attempt.closed.promise;
            this.clearHeartbeat();
            if (!this.active) break;
            this.notify(this.options.onDisconnect);
            this.check();
            if (attempt.code === 1000 || attempt.code === 1001) break;
            if (this.retries >= 5)
              throw new Error('Unable to reconnect after several attempts. Please retry manually.');
            const delay = Math.min(3000 * 2 ** this.retries++, 30000);
            await this.delay(delay);
          }
          if (this.businessError) throw this.businessError;
        } catch (error) {
          primary = { error };
        }
        if (primary && !isAbort(primary.error) && this.live()) {
          const error =
            primary.error instanceof Error
              ? primary.error
              : new Error('Terminal connection failed');
          this.notify(() => {
            this.options.onError(error);
          });
        }
        if (primary) this.ready.reject(primary.error);
        this.retire();
        const results = await Promise.allSettled([this.attempt?.closed.promise, this.cleanupTask]);
        operation.signal.removeEventListener('abort', retire);
        for (const result of results)
          if (result.status === 'rejected') this.cleanupErrors.push(result.reason);
        if (this.cleanupErrors.length)
          throw new WebOperationCleanupErrorV2(
            [...this.cleanupErrors],
            'Terminal resource cleanup failed'
          );
        if (primary) throw primary.error;
      },
      { signal: this.controller.signal }
    ).catch((error: unknown) => {
      this.ready.reject(error);
      this.retire();
      if (!isAbort(error)) throw error;
    });
    void this.task.catch(() => undefined);
    return this.ready.promise;
  }
  getOperationContext(): WebOperationContextV2 | undefined {
    return this.live() ? this.operation : undefined;
  }
  private check(): void {
    if (
      !this.active ||
      !this.operation ||
      this.owner !== getWebOperationAvailabilityV2().owner ||
      this.operation.owner !== this.owner
    )
      throw aborted();
    this.operation.check();
  }
  private live(): boolean {
    try {
      this.check();
      return true;
    } catch {
      return false;
    }
  }
  private current(attempt: Attempt): boolean {
    return this.attempt === attempt && this.live();
  }
  private notify(callback: () => void): void {
    try {
      callback();
    } catch {
      /* UI callbacks cannot interrupt resource cleanup. */
    }
  }
  private createAttempt(): Attempt {
    this.check();
    const path = this.options.projectId
      ? `/projects/${encodeURIComponent(this.options.projectId)}/sandbox/terminal/proxy/ws`
      : `/terminal/${encodeURIComponent(this.options.sandboxId)}/ws`;
    const socket = new WebSocket(
      createWebSocketUrl(path, this.sessionId ? { session_id: this.sessionId } : undefined),
      createWebSocketAuthProtocols(this.token)
    );
    const attempt: Attempt = { socket, closed: completion(), code: 1000, connected: false };
    this.attempt = attempt;
    socket.onopen = () => {
      if (!this.current(attempt)) this.closeAttempt(attempt);
    };
    socket.onmessage = (event) => {
      if (!this.current(attempt) || typeof event.data !== 'string') return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!parsed || typeof parsed !== 'object') return;
      const message = parsed as Record<string, unknown>;
      if (
        message.type === 'connected' &&
        typeof message.session_id === 'string' &&
        message.session_id.length > 0
      ) {
        if (attempt.connected) return;
        // A resumed attachment must not silently adopt a different backend session.
        if (this.sessionId && message.session_id !== this.sessionId) {
          this.businessError = new Error('Terminal session identity mismatch');
          this.notify(() => {
            this.options.onError(new Error('Terminal session identity mismatch'));
          });
          this.retire();
          return;
        }
        this.sessionId = message.session_id;
        attempt.connected = true;
        this.retries = 0;
        this.businessError = undefined;
        this.notify(() => {
          this.options.onConnect(message.session_id as string);
        });
        if (!this.current(attempt)) return;
        this.ready.resolve();
        this.clearHeartbeat();
        this.heartbeat = setInterval(() => {
          this.send({ type: 'ping' });
        }, 30000);
      } else if (
        message.type === 'output' &&
        typeof message.data === 'string' &&
        attempt.connected
      ) {
        this.notify(() => {
          this.options.onOutput(message.data as string);
        });
      } else if (message.type === 'error' && typeof message.message === 'string') {
        this.businessError = new Error(message.message);
        this.notify(() => {
          this.options.onError(this.businessError!);
        });
      }
    };
    socket.onerror = () => {
      if (this.current(attempt)) {
        this.businessError = new Error('Terminal WebSocket connection error');
        this.notify(() => {
          this.options.onError(this.businessError!);
        });
      }
    };
    socket.onclose = (event) => {
      if (this.attempt !== attempt) return;
      attempt.code = event.code;
      attempt.connected = false;
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      this.clearHeartbeat();
      if (this.ready.settled) this.ready = completion();
      attempt.closed.resolve();
    };
    return attempt;
  }
  private send(message: object): boolean {
    const attempt = this.attempt;
    if (
      !attempt ||
      !this.current(attempt) ||
      !attempt.connected ||
      attempt.socket.readyState !== WebSocket.OPEN
    )
      return false;
    try {
      attempt.socket.send(JSON.stringify(message));
      return true;
    } catch (error) {
      this.businessError = error instanceof Error ? error : new Error('Terminal send failed');
      this.notify(() => {
        this.options.onError(this.businessError!);
      });
      return false;
    }
  }
  sendInput(data: string): boolean {
    return this.send({ type: 'input', data });
  }
  resize(cols: number, rows: number): boolean {
    if (!Number.isInteger(cols) || !Number.isInteger(rows) || cols < 1 || rows < 1) return false;
    return this.send({ type: 'resize', cols, rows });
  }
  private delay(milliseconds: number): Promise<void> {
    return new Promise((resolve) => {
      this.wakeTimer = resolve;
      this.timer = setTimeout(() => {
        this.timer = undefined;
        this.wakeTimer = undefined;
        resolve();
      }, milliseconds);
    });
  }
  private clearHeartbeat(): void {
    if (this.heartbeat !== undefined) {
      clearInterval(this.heartbeat);
      this.heartbeat = undefined;
    }
  }
  private closeAttempt(attempt: Attempt): void {
    if (attempt.socket.readyState === WebSocket.CLOSED) {
      attempt.closed.resolve();
      return;
    }
    if (attempt.socket.readyState === WebSocket.CLOSING) return;
    try {
      attempt.socket.close(1000, 'Terminal session retired');
    } catch (error) {
      this.cleanupErrors.push(error);
    }
  }
  private cleanupResources(): void {
    const cleanup = this.resourceCleanup;
    this.resourceCleanup = undefined;
    if (!cleanup) return;
    try {
      this.cleanupTask = Promise.resolve(cleanup());
    } catch (error) {
      this.cleanupTask = Promise.reject(error);
    }
    void this.cleanupTask.catch(() => undefined);
  }
  private retire(): void {
    if (this.active) {
      this.active = false;
      this.ready.reject(this.businessError ?? aborted());
      this.controller.abort();
      this.cleanupResources();
    }
    this.clearHeartbeat();
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    this.wakeTimer?.();
    this.wakeTimer = undefined;
    if (this.attempt) this.closeAttempt(this.attempt);
  }
  disconnect(): Promise<void> {
    this.retire();
    return this.task ?? Promise.resolve();
  }
}
