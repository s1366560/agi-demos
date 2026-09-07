import {
  getWebOperationAvailabilityV2,
  runWebOperationV2,
  WebOperationCleanupErrorV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';
import { getAuthToken } from '@/utils/tokenResolver';

import { buildDesktopWebSocketProtocols } from './sandboxWebSocketUtils';

export interface KasmAttemptContextV2 {
  readonly signal: AbortSignal;
  check(): void;
  runChild<T>(work: (operation: WebOperationContextV2) => Promise<T>): Promise<T>;
  connected(): void;
  disconnected(reason?: string): void;
  fail(error: Error): void;
}
export interface KasmRetainedSessionOptionsV2 {
  projectId: string;
  sandboxId: string;
  wsUrl: string;
  createAttempt(
    socket: WebSocket,
    operation: WebOperationContextV2,
    attempt: KasmAttemptContextV2
  ): { dispose(): void | Promise<void> };
  onStateChange(state: 'connecting' | 'connected' | 'disconnected' | 'error'): void;
  onError?: ((error: Error) => void) | undefined;
  onDisconnect?: ((reason?: string) => void) | undefined;
  onAdmitted?:
    | ((operation: WebOperationContextV2) => undefined | (() => void | Promise<void>))
    | undefined;
}
function completion() {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<void>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  void promise.catch(() => undefined);
  return { promise, resolve, reject };
}
const retired = () => new DOMException('Kasm session retired', 'AbortError');
const isAbort = (error: unknown) => error instanceof DOMException && error.name === 'AbortError';
interface Attempt {
  socket: WebSocket;
  controller: AbortController;
  active: boolean;
  closed: ReturnType<typeof completion>;
  children: Set<Promise<unknown>>;
  resource?: { dispose(): void | Promise<void> } | undefined;
  cleanup?: Promise<void> | undefined;
  removeListeners(): void;
  reason?: string | undefined;
}

/** One admitted desktop attachment retains its generation through every physical socket close. */
export class KasmRetainedSessionV2 {
  private readonly options: Readonly<KasmRetainedSessionOptionsV2>;
  private readonly owner = getWebOperationAvailabilityV2().owner;
  private readonly controller = new AbortController();
  private readonly ready = completion();
  private active = true;
  private operation: WebOperationContextV2 | undefined;
  private task: Promise<void> | undefined;
  private attempt: Attempt | undefined;
  private token = '';
  private retries = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private wake: (() => void) | undefined;
  private cleanup: (() => void | Promise<void>) | undefined;
  private cleanupTask: Promise<void> | undefined;
  private readonly failures: unknown[] = [];

  constructor(options: KasmRetainedSessionOptionsV2) {
    this.options = Object.freeze({ ...options });
  }
  get done(): Promise<void> {
    return this.task ?? Promise.resolve();
  }
  connect(): Promise<void> {
    if (!this.active) return Promise.reject(retired());
    if (this.task) return this.ready.promise;
    this.token = getAuthToken() ?? '';
    this.task = runWebOperationV2(
      async (operation) => {
        this.operation = operation;
        const abort = () => this.retire();
        operation.signal.addEventListener('abort', abort, { once: true });
        let primary: { error: unknown } | undefined;
        try {
          this.check();
          if (!this.options.projectId || !this.options.sandboxId)
            throw new Error('Desktop project and sandbox are required');
          if (!this.token) throw new Error('No auth token available');
          this.cleanup = this.options.onAdmitted?.(operation) ?? undefined;
          if (!this.active) this.disposeResources();
          this.check();
          while (this.active) {
            this.publish('connecting');
            this.check();
            const attempt = this.createAttempt(operation);
            await this.drainAttempt(attempt);
            this.check();
            if (this.failures.length) throw this.cleanupError();
            if (this.retries >= 10)
              throw new Error(attempt.reason ?? 'Desktop connection lost after max retries');
            await this.delay(Math.min(1000 * 1.5 ** this.retries++, 15000));
          }
        } catch (error) {
          primary = { error };
          this.ready.reject(error);
          if (this.live() && !isAbort(error)) {
            this.publish('error');
            const failure = error instanceof Error ? error : new Error('Desktop connection failed');
            this.notify(() => this.options.onError?.(failure));
            this.notify(() => this.options.onDisconnect?.(failure.message));
          }
        }
        this.retire();
        if (this.attempt) await this.drainAttempt(this.attempt);
        if (this.cleanupTask) await this.cleanupTask;
        operation.signal.removeEventListener('abort', abort);
        if (this.failures.length) throw this.cleanupError();
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
  private check(): void {
    if (
      !this.active ||
      !this.operation ||
      this.operation.owner !== this.owner ||
      getWebOperationAvailabilityV2().owner !== this.owner
    )
      throw retired();
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
  private notify(callback: () => void): void {
    if (!this.live()) return;
    try {
      callback();
    } catch {
      /* A view cannot prevent resource retirement. */
    }
  }
  private publish(state: Parameters<KasmRetainedSessionOptionsV2['onStateChange']>[0]): void {
    this.notify(() => this.options.onStateChange(state));
  }
  private createAttempt(operation: WebOperationContextV2): Attempt {
    this.check();
    const socket = new WebSocket(this.options.wsUrl, buildDesktopWebSocketProtocols(this.token));
    const attempt: Attempt = {
      socket,
      controller: new AbortController(),
      active: true,
      closed: completion(),
      children: new Set(),
      removeListeners: () => undefined,
    };
    this.attempt = attempt;
    const check = () => {
      this.check();
      if (!attempt.active || this.attempt !== attempt) throw retired();
    };
    const closed = () => {
      attempt.closed.resolve();
      this.retireAttempt(attempt);
    };
    const error = () => {
      if (!attempt.active) return;
      attempt.reason = 'Desktop WebSocket connection failed';
      this.retireAttempt(attempt);
    };
    const opened = () => {
      if (!attempt.active || !this.live()) this.retireAttempt(attempt);
    };
    socket.addEventListener('close', closed, { once: true });
    socket.addEventListener('error', error);
    socket.addEventListener('open', opened);
    attempt.removeListeners = () => {
      socket.removeEventListener('close', closed);
      socket.removeEventListener('error', error);
      socket.removeEventListener('open', opened);
    };
    const send = socket.send.bind(socket);
    socket.send = (data) => {
      check();
      send(data);
    };
    const context: KasmAttemptContextV2 = {
      signal: attempt.controller.signal,
      check,
      runChild: (work) => {
        check();
        const task = runWebOperationV2(work, {
          parent: operation,
          signal: attempt.controller.signal,
        });
        attempt.children.add(task);
        void task
          .catch((failure: unknown) => {
            if (failure instanceof WebOperationCleanupErrorV2) this.failures.push(failure);
          })
          .finally(() => {
            attempt.children.delete(task);
          });
        return task;
      },
      connected: () => {
        check();
        this.retries = 0;
        this.publish('connected');
        check();
        this.ready.resolve();
      },
      disconnected: (reason) => {
        check();
        attempt.reason = reason;
        this.retireAttempt(attempt);
      },
      fail: (failure) => {
        check();
        attempt.reason = failure.message;
        this.retireAttempt(attempt);
      },
    };
    attempt.resource = this.options.createAttempt(socket, operation, context);
    if (!attempt.active) this.disposeAttempt(attempt);
    return attempt;
  }
  private disposeAttempt(attempt: Attempt): void {
    const resource = attempt.resource;
    attempt.resource = undefined;
    if (!resource) return;
    try {
      attempt.cleanup = Promise.resolve(resource.dispose()).catch((error: unknown) => {
        this.failures.push(error);
      });
    } catch (error) {
      this.failures.push(error);
    }
  }
  private retireAttempt(attempt: Attempt): void {
    attempt.active = false;
    attempt.controller.abort(retired());
    this.disposeAttempt(attempt);
    const socket = attempt.socket;
    if (socket.readyState === WebSocket.CLOSED) {
      attempt.closed.resolve();
      return;
    }
    if (socket.readyState === WebSocket.CLOSING) return;
    try {
      socket.close();
    } catch (error) {
      this.failures.push(error);
    }
  }
  private async drainAttempt(attempt: Attempt): Promise<void> {
    await attempt.closed.promise;
    this.retireAttempt(attempt);
    if (attempt.cleanup) await attempt.cleanup;
    while (attempt.children.size) await Promise.allSettled([...attempt.children]);
    attempt.removeListeners();
    if (this.attempt === attempt) this.attempt = undefined;
  }
  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => {
      this.wake = resolve;
      this.timer = setTimeout(() => {
        this.timer = undefined;
        this.wake = undefined;
        resolve();
      }, ms);
    });
  }
  private disposeResources(): void {
    const cleanup = this.cleanup;
    this.cleanup = undefined;
    if (!cleanup) return;
    try {
      this.cleanupTask = Promise.resolve(cleanup()).catch((error: unknown) => {
        this.failures.push(error);
      });
    } catch (error) {
      this.failures.push(error);
    }
  }
  private retire(): void {
    if (this.active) {
      this.active = false;
      this.ready.reject(retired());
      this.controller.abort(retired());
      this.disposeResources();
    }
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
    this.wake?.();
    this.wake = undefined;
    if (this.attempt) this.retireAttempt(this.attempt);
  }
  private cleanupError(): WebOperationCleanupErrorV2 {
    return new WebOperationCleanupErrorV2([...this.failures], 'Kasm resource cleanup failed');
  }
  disconnect(): Promise<void> {
    this.retire();
    return this.done;
  }
}
