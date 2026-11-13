import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { McpError, ErrorCode } from '@modelcontextprotocol/sdk/types.js';

import { createWebSocketUrl } from '@/services/client/urlUtils';
import { projectSandboxService } from '@/services/projectSandboxService';

import {
  getWebOperationAvailabilityV2,
  runWebOperationV2,
  WebOperationCleanupErrorV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';

import { BrowserWebSocketTransport } from './BrowserWebSocketTransport';

export interface MCPAppSessionSnapshotV2 {
  client: Client | null;
  operation: WebOperationContextV2 | null;
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  error: string | null;
  isInGracePeriod: boolean;
  canFallback: boolean;
  retired: boolean;
}
export interface MCPAppSessionOptionsV2 {
  projectId: string;
  appId?: string | undefined;
  serverName?: string | undefined;
  toolName?: string | undefined;
  resourceUri?: string | undefined;
  enabled: boolean;
  maxAttempts: number;
  initialDelayMs: number;
  maxDelayMs: number;
  gracePeriodMs: number;
  changed: (snapshot: MCPAppSessionSnapshotV2) => void;
  onAdmitted?:
    | ((operation: WebOperationContextV2) => undefined | (() => void | Promise<void>))
    | undefined;
}
export const emptyMCPSnapshotV2: MCPAppSessionSnapshotV2 = Object.freeze({
  client: null,
  operation: null,
  status: 'disconnected',
  error: null,
  isInGracePeriod: false,
  canFallback: false,
  retired: true,
});
function completion() {
  let settled = false;
  let resolve!: () => void;
  let reject!: (e: unknown) => void;
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
const cancelled = () => new DOMException('MCP App session retired', 'AbortError');
const isAbort = (error: unknown) => error instanceof DOMException && error.name === 'AbortError';
interface Attempt {
  client: Client;
  transport: BrowserWebSocketTransport;
  closed: ReturnType<typeof completion>;
  handshake?: Promise<void>;
}
export class MCPAppRetainedSessionV2 {
  private readonly owner = getWebOperationAvailabilityV2().owner;
  private readonly controller = new AbortController();
  private readonly options: Readonly<MCPAppSessionOptionsV2>;
  private active = true;
  private operation: WebOperationContextV2 | undefined;
  private attempt: Attempt | undefined;
  private readonly stopped = completion();
  private connected = completion();
  private wake: (() => void) | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private grace: ReturnType<typeof setTimeout> | undefined;
  private handshakeTimer: ReturnType<typeof setTimeout> | undefined;
  private retryRequested = false;
  private cleanup: (() => void | Promise<void>) | undefined;
  private cleanupTask: Promise<void> | undefined;
  private readonly cleanupErrors: unknown[] = [];
  private snapshot: MCPAppSessionSnapshotV2 = emptyMCPSnapshotV2;
  readonly done: Promise<void>;
  constructor(options: MCPAppSessionOptionsV2) {
    this.options = Object.freeze({ ...options });
    this.done = runWebOperationV2(
      async (operation) => {
        this.operation = operation;
        const abort = () => {
          this.retire();
        };
        operation.signal.addEventListener('abort', abort, { once: true });
        let primary: { error: unknown } | undefined;
        try {
          this.check();
          if (!options.projectId) throw new Error('MCP App project is required');
          const cleanup = options.onAdmitted?.(operation);
          if (cleanup) {
            this.cleanup = cleanup;
            if (!this.active) this.cleanupResources();
          }
          this.check();
          this.publish({
            operation,
            retired: false,
            status: options.enabled ? 'connecting' : 'disconnected',
            canFallback: !options.enabled,
          });
          if (options.enabled) await this.runConnections();
          else await this.stopped.promise;
        } catch (error) {
          primary = { error };
          if (this.live() && !isAbort(error))
            this.publish({
              status: 'error',
              error: error instanceof Error ? error.message : 'MCP connection failed',
              canFallback: false,
            });
        }
        this.retire();
        await this.drainAttempt();
        if (this.cleanupTask) {
          try {
            await this.cleanupTask;
          } catch (error) {
            this.cleanupErrors.push(error);
          }
        }
        operation.signal.removeEventListener('abort', abort);
        if (this.cleanupErrors.length)
          throw new WebOperationCleanupErrorV2([...this.cleanupErrors], 'MCP App cleanup failed');
        if (primary) throw primary.error;
      },
      { signal: this.controller.signal }
    ).catch((error: unknown) => {
      this.connected.reject(error);
      this.retire();
      if (!isAbort(error)) throw error;
    });
    void this.done.catch(() => undefined);
  }
  private check(): void {
    if (
      !this.active ||
      !this.operation ||
      this.operation.owner !== this.owner ||
      getWebOperationAvailabilityV2().owner !== this.owner
    )
      throw cancelled();
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
  private publish(patch: Partial<MCPAppSessionSnapshotV2>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    try {
      this.options.changed(this.snapshot);
    } catch {
      /* UI cannot prevent cleanup. */
    }
  }
  private async runConnections(): Promise<void> {
    let failures = 0;
    while (this.active) {
      this.check();
      if (this.retryRequested) failures = 0;
      this.retryRequested = false;
      let failed: unknown;
      try {
        this.publish({ status: 'connecting', canFallback: false });
        this.check();
        const operation = this.operation!;
        await projectSandboxService.ensureProxyAuthCookie(this.options.projectId, {
          operation,
          signal: operation.signal,
        });
        this.check();
        const requests = new AbortController();
        const transport = new BrowserWebSocketTransport({
          url: createWebSocketUrl(
            `/projects/${encodeURIComponent(this.options.projectId)}/sandbox/mcp/proxy`
          ),
          operation,
          onRetire: () => {
            requests.abort(new McpError(ErrorCode.ConnectionClosed, 'Connection closed'));
          },
        });
        const client = new Client({ name: 'memstack-web', version: '1.0.0' }, { capabilities: {} });
        const request = client.request.bind(client);
        const guardedRequest: Client['request'] = (params, schema, options) => {
          operation.check();
          const signal = options?.signal
            ? AbortSignal.any([requests.signal, options.signal])
            : requests.signal;
          signal.throwIfAborted();
          return request(params, schema, { ...options, signal });
        };
        client.request = guardedRequest;
        const close = client.close.bind(client);
        client.close = () => {
          const closed = close();
          void closed.catch(() => undefined);
          return closed;
        };
        const attempt: Attempt = { client, transport, closed: completion() };
        this.attempt = attempt;
        transport.onclose = () => {
          attempt.closed.resolve();
        };
        attempt.handshake = client.connect(transport);
        const timeout = new Promise<never>((_, reject) => {
          this.handshakeTimer = setTimeout(() => {
            reject(new Error('MCP connect timeout'));
          }, 20000);
        });
        await Promise.race([attempt.handshake, timeout]);
        this.clearHandshake();
        this.check();
        this.clearGrace();
        failures = 0;
        this.publish({
          client,
          status: 'connected',
          error: null,
          isInGracePeriod: false,
          canFallback: false,
        });
        this.check();
        this.connected.resolve();
        await attempt.closed.promise;
        this.check();
        if (this.connected.settled) this.connected = completion();
        this.publish({ client: null, isInGracePeriod: true });
        this.check();
        this.grace = setTimeout(() => {
          if (this.live()) this.publish({ status: 'disconnected', isInGracePeriod: false });
        }, this.options.gracePeriodMs);
      } catch (error) {
        failed = error;
      }
      this.clearHandshake();
      await this.drainAttempt();
      this.check();
      if (this.cleanupErrors.length)
        throw new WebOperationCleanupErrorV2([...this.cleanupErrors], 'MCP App cleanup failed');
      if (this.retryRequested) {
        failures = 0;
        continue;
      }
      if (failures >= this.options.maxAttempts) {
        this.clearGrace();
        const message =
          failed instanceof Error ? failed.message : 'Connection lost and reconnection failed';
        this.connected.reject(failed ?? new Error(message));
        this.publish({
          client: null,
          status: 'error',
          error: message,
          isInGracePeriod: false,
          canFallback: true,
        });
        this.check();
        await this.wait();
        this.check();
        failures = 0;
        continue;
      }
      this.publish({ client: null, error: failed instanceof Error ? failed.message : null });
      this.check();
      await this.wait(
        Math.min(this.options.initialDelayMs * 2 ** failures++, this.options.maxDelayMs)
      );
    }
  }
  private async drainAttempt(): Promise<void> {
    const attempt = this.attempt;
    if (!attempt) return;
    const results = await Promise.allSettled([
      attempt.client.close(),
      attempt.transport.close(),
      attempt.handshake,
    ]);
    for (const result of results)
      if (result.status === 'rejected' && result.reason instanceof WebOperationCleanupErrorV2)
        this.cleanupErrors.push(result.reason);
    if (this.attempt === attempt) this.attempt = undefined;
  }
  private wait(delay?: number): Promise<void> {
    return new Promise((resolve) => {
      this.wake = resolve;
      if (delay !== undefined)
        this.timer = setTimeout(() => {
          this.timer = undefined;
          this.wake = undefined;
          resolve();
        }, delay);
    });
  }
  private clearGrace(): void {
    if (this.grace !== undefined) {
      clearTimeout(this.grace);
      this.grace = undefined;
    }
  }
  private clearHandshake(): void {
    if (this.handshakeTimer !== undefined) {
      clearTimeout(this.handshakeTimer);
      this.handshakeTimer = undefined;
    }
  }
  private cleanupResources(): void {
    const cleanup = this.cleanup;
    this.cleanup = undefined;
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
      this.connected.reject(cancelled());
      this.controller.abort();
      this.cleanupResources();
      this.publish({ ...emptyMCPSnapshotV2 });
      this.stopped.resolve();
    }
    this.clearGrace();
    this.clearHandshake();
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    this.wake?.();
    this.wake = undefined;
    if (this.attempt) void this.attempt.transport.close().catch(() => undefined);
  }
  assertFallback(): WebOperationContextV2 {
    this.check();
    if (!this.snapshot.canFallback) throw new Error('MCP HTTP fallback unavailable');
    return this.operation!;
  }
  reconnect(): Promise<void> {
    try {
      this.check();
    } catch (error) {
      return Promise.reject(error);
    }
    this.connected = completion();
    this.retryRequested = true;
    if (this.attempt) void this.attempt.transport.close().catch(() => undefined);
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    this.wake?.();
    this.wake = undefined;
    return this.connected.promise;
  }
  disconnect(): Promise<void> {
    this.retire();
    return this.done;
  }
}
