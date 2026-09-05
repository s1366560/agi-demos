import { JSONRPCMessageSchema, type JSONRPCMessage } from '@modelcontextprotocol/sdk/types.js';

import {
  WebOperationCleanupErrorV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';

import type {
  Transport,
  TransportSendOptions,
} from '@modelcontextprotocol/sdk/shared/transport.js';

export interface BrowserWebSocketTransportOptions {
  url: string;
  operation: WebOperationContextV2;
  onRetire?: (() => void) | undefined;
  connectTimeout?: number | undefined;
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
const cancelled = () => new DOMException('MCP transport retired', 'AbortError');
/** Logical retirement settles SDK RPCs immediately; physical close retains the parent operation. */
export class BrowserWebSocketTransport implements Transport {
  private ws: WebSocket | null = null;
  private readonly options: Readonly<BrowserWebSocketTransportOptions>;
  private started = false;
  private retired = false;
  private notified = false;
  private readonly opened = completion();
  private readonly closed = completion();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly cleanupErrors: unknown[] = [];
  private closing: Promise<void> | undefined;
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: JSONRPCMessage) => void;
  sessionId?: string;
  constructor(options: BrowserWebSocketTransportOptions) {
    this.options = Object.freeze({ ...options });
  }
  private check(): void {
    if (this.retired) throw cancelled();
    this.options.operation.check();
  }
  private live(): boolean {
    try {
      this.check();
      return true;
    } catch {
      return false;
    }
  }
  private readonly onAbort = () => {
    void this.close().catch(() => undefined);
  };
  start(): Promise<void> {
    if (this.started) return Promise.reject(new Error('MCP transport already started'));
    this.started = true;
    this.options.operation.signal.addEventListener('abort', this.onAbort, { once: true });
    try {
      this.check();
      const ws = new WebSocket(this.options.url);
      this.ws = ws;
      this.timer = setTimeout(() => {
        const error = new Error(
          `WebSocket connection timeout after ${String(this.options.connectTimeout ?? 10000)}ms`
        );
        this.opened.reject(error);
        void this.close().catch(() => undefined);
      }, this.options.connectTimeout ?? 10000);
      ws.onopen = () => {
        if (!this.live()) {
          this.closeSocket();
          return;
        }
        this.clearTimer();
        this.opened.resolve();
      };
      ws.onerror = () => {
        if (!this.live()) return;
        const error = new Error('MCP WebSocket connection failed');
        this.opened.reject(error);
        this.onerror?.(error);
      };
      ws.onmessage = (event) => {
        if (!this.live() || typeof event.data !== 'string') return;
        try {
          const message = JSONRPCMessageSchema.parse(JSON.parse(event.data));
          this.onmessage?.(message);
        } catch (error) {
          this.onerror?.(error instanceof Error ? error : new Error('Invalid MCP message'));
        }
      };
      ws.onclose = () => {
        this.ws = null;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        this.retire();
        this.closed.resolve();
      };
    } catch (error) {
      this.opened.reject(error);
      this.retire();
      if (!this.ws) this.closed.resolve();
    }
    return this.opened.promise;
  }
  send(message: JSONRPCMessage, _options?: TransportSendOptions): Promise<void> {
    try {
      this.check();
      if (this.ws?.readyState !== WebSocket.OPEN) throw new Error('MCP WebSocket not connected');
      this.ws.send(JSON.stringify(message));
      return Promise.resolve();
    } catch (error) {
      return Promise.reject(error);
    }
  }
  private clearTimer(): void {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
  }
  private retire(): void {
    const first = !this.retired;
    this.retired = true;
    if (first) {
      try {
        this.options.onRetire?.();
      } catch (error) {
        this.cleanupErrors.push(error);
      }
    }
    this.clearTimer();
    this.opened.reject(cancelled());
    this.options.operation.signal.removeEventListener('abort', this.onAbort);
    if (!this.notified) {
      this.notified = true;
      try {
        this.onclose?.();
      } catch (error) {
        this.cleanupErrors.push(error);
      }
    }
  }
  private closeSocket(): void {
    const ws = this.ws;
    if (!ws) {
      this.closed.resolve();
      return;
    }
    if (ws.readyState === WebSocket.CLOSED) {
      this.closed.resolve();
      return;
    }
    if (ws.readyState === WebSocket.CLOSING) return;
    try {
      ws.close(1000, 'MCP client retired');
    } catch (error) {
      this.cleanupErrors.push(error);
    }
  }
  close(): Promise<void> {
    this.retire();
    this.closeSocket();
    this.closing ??= this.closed.promise.then(() => {
      if (this.cleanupErrors.length)
        throw new WebOperationCleanupErrorV2([...this.cleanupErrors], 'MCP socket cleanup failed');
    });
    void this.closing.catch(() => undefined);
    return this.closing;
  }
}
