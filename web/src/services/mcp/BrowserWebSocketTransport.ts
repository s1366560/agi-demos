/**
 * Browser-compatible WebSocket transport for the MCP SDK Client.
 *
 * Implements the Transport interface using the browser's native WebSocket API.
 * Designed for direct communication between browser MCP clients and sandbox
 * MCP servers via backend WebSocket proxy.
 */

import type { JSONRPCMessage } from '@modelcontextprotocol/sdk/types.js';
import type { Transport, TransportSendOptions } from '@modelcontextprotocol/sdk/shared/transport.js';

export interface BrowserWebSocketTransportOptions {
  /** WebSocket URL to connect to */
  url: string;
  /** Connection timeout in milliseconds (default: 10000) */
  connectTimeout?: number;
  /** Auth token to append as query parameter */
  token?: string;
}

/**
 * MCP Transport implementation using browser's native WebSocket.
 *
 * Usage:
 *   const transport = new BrowserWebSocketTransport({ url: 'ws://...' });
 *   const client = new Client({ name: 'web', version: '1.0.0' });
 *   await client.connect(transport); // handles initialize handshake
 */
export class BrowserWebSocketTransport implements Transport {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly connectTimeout: number;

  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: JSONRPCMessage) => void;
  sessionId?: string;

  constructor(options: BrowserWebSocketTransportOptions) {
    const url = new URL(options.url);
    if (options.token) {
      url.searchParams.set('token', options.token);
    }
    this.url = url.toString();
    this.connectTimeout = options.connectTimeout ?? 10_000;
  }

  async start(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(this.url);
      const timeout = setTimeout(() => {
        ws.close();
        reject(new Error(`WebSocket connection timeout after ${this.connectTimeout}ms`));
      }, this.connectTimeout);

      ws.onopen = () => {
        clearTimeout(timeout);
        this.ws = ws;
        resolve();
      };

      ws.onerror = (event) => {
        clearTimeout(timeout);
        const error = new Error(`WebSocket connection failed: ${this.url}`);
        this.onerror?.(error);
        reject(error);
        // Suppress unhandled event after rejection
        void event;
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data as string) as JSONRPCMessage;
          this.onmessage?.(message);
        } catch (err) {
          this.onerror?.(new Error(`Failed to parse message: ${err}`));
        }
      };

      ws.onclose = () => {
        this.ws = null;
        this.onclose?.();
      };
    });
  }

  async send(message: JSONRPCMessage, _options?: TransportSendOptions): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected');
    }
    this.ws.send(JSON.stringify(message));
  }

  async close(): Promise<void> {
    const ws = this.ws;
    if (ws) {
      this.ws = null;
      ws.close(1000, 'Client closed');
    }
  }
}
