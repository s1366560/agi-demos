/**
 * Event Bus Client
 *
 * WebSocket client for subscribing to events from the unified event bus.
 * Supports pattern-based subscriptions, automatic reconnection, and heartbeats.
 */

import { isEventEnvelope } from '../types/generated/eventEnvelope';

import type { EventEnvelope } from '../types/generated/eventEnvelope';

// =============================================================================
// Types
// =============================================================================

/**
 * Event handler callback
 */
export type EventHandler = (envelope: EventEnvelope) => void;

/**
 * Error handler callback
 */
export type ErrorHandler = (error: Error) => void;

/**
 * Connection state
 */
export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

/**
 * Event bus client options
 */
export interface EventBusClientOptions {
  /** WebSocket URL (default: ws://localhost:8000/api/v1/events/ws) */
  url?: string | undefined;

  /** Enable automatic reconnection (default: true) */
  autoReconnect?: boolean | undefined;

  /** Maximum reconnect attempts (default: 5) */
  maxReconnectAttempts?: number | undefined;

  /** Base reconnect delay in ms (default: 1000) */
  reconnectDelay?: number | undefined;

  /** Maximum reconnect delay in ms (default: 30000) */
  maxReconnectDelay?: number | undefined;

  /** Heartbeat interval in ms (default: 30000) */
  heartbeatInterval?: number | undefined;

  /** Connection timeout in ms (default: 10000) */
  connectionTimeout?: number | undefined;
}

/**
 * Subscription options
 */
export interface SubscriptionOptions {
  /** Only receive events matching this correlation ID */
  correlationId?: string | undefined;
}

/**
 * Unsubscribe function
 */
export type Unsubscribe = () => void;

// =============================================================================
// Default Configuration
// =============================================================================

const DEFAULT_OPTIONS: {
  url: string;
  autoReconnect: boolean;
  maxReconnectAttempts: number;
  reconnectDelay: number;
  maxReconnectDelay: number;
  heartbeatInterval: number;
  connectionTimeout: number;
} = {
  url: `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/v1/events/ws`,
  autoReconnect: true,
  maxReconnectAttempts: 5,
  reconnectDelay: 1000,
  maxReconnectDelay: 30000,
  heartbeatInterval: 30000,
  connectionTimeout: 10000,
};

// =============================================================================
// Event Bus Client
// =============================================================================

export class EventBusClient {
  private ws: WebSocket | null = null;
  private options: typeof DEFAULT_OPTIONS;
  private subscriptions: Map<string, Set<EventHandler>> = new Map();
  private errorHandlers: Set<ErrorHandler> = new Set();
  private state: ConnectionState = 'disconnected';
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private connectionTimer: ReturnType<typeof setTimeout> | null = null;
  private messageQueue: string[] = [];

  // State change listeners
  private stateListeners: Set<(state: ConnectionState) => void> = new Set();

  constructor(options: EventBusClientOptions = {}) {
    this.options = {
      url: options.url ?? DEFAULT_OPTIONS.url,
      autoReconnect: options.autoReconnect ?? DEFAULT_OPTIONS.autoReconnect,
      maxReconnectAttempts: options.maxReconnectAttempts ?? DEFAULT_OPTIONS.maxReconnectAttempts,
      reconnectDelay: options.reconnectDelay ?? DEFAULT_OPTIONS.reconnectDelay,
      maxReconnectDelay: options.maxReconnectDelay ?? DEFAULT_OPTIONS.maxReconnectDelay,
      heartbeatInterval: options.heartbeatInterval ?? DEFAULT_OPTIONS.heartbeatInterval,
      connectionTimeout: options.connectionTimeout ?? DEFAULT_OPTIONS.connectionTimeout,
    };
  }

  // ===========================================================================
  // Connection Management
  // ===========================================================================

  /**
   * Connect to the event bus
   */
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.state === 'connected') {
        resolve();
        return;
      }

      if (this.state === 'connecting') {
        // Wait for existing connection attempt
        const checkConnection = setInterval(() => {
          if (this.state === 'connected') {
            clearInterval(checkConnection);
            resolve();
          } else if (this.state === 'disconnected') {
            clearInterval(checkConnection);
            reject(new Error('Connection failed'));
          }
        }, 100);
        return;
      }

      this.setState('connecting');

      try {
        this.ws = new WebSocket(this.options.url);

        // Set connection timeout
        this.connectionTimer = setTimeout(() => {
          if (this.state === 'connecting') {
            this.ws?.close();
            this.setState('disconnected');
            reject(new Error('Connection timeout'));
          }
        }, this.options.connectionTimeout);

        this.ws.onopen = () => {
          this.clearConnectionTimer();
          this.setState('connected');
          this.reconnectAttempts = 0;
          this.startHeartbeat();
          this.flushMessageQueue();
          resolve();
        };

        this.ws.onclose = (event) => {
          this.clearHeartbeat();
          this.clearConnectionTimer();

          if (this.state === 'connecting') {
            this.setState('disconnected');
            reject(new Error(`Connection closed: ${event.code}`));
            return;
          }

          this.setState('disconnected');

          if (this.options.autoReconnect && !event.wasClean) {
            this.scheduleReconnect();
          }
        };

        this.ws.onerror = () => {
          const error = new Error('WebSocket error');
          this.notifyError(error);
        };

        this.ws.onmessage = (event) => {
          this.handleMessage(event.data);
        };
      } catch (_err) {
        this.setState('disconnected');
        reject(_err);
      }
    });
  }

  /**
   * Disconnect from the event bus
   */
  disconnect(): void {
    this.clearReconnectTimer();
    this.clearHeartbeat();
    this.clearConnectionTimer();

    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }

    this.setState('disconnected');
  }

  /**
   * Get current connection state
   */
  getState(): ConnectionState {
    return this.state;
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.state === 'connected' && this.ws?.readyState === WebSocket.OPEN;
  }

  // ===========================================================================
  // Subscriptions
  // ===========================================================================

  /**
   * Subscribe to events matching a pattern
   *
   * Pattern examples:
   * - "agent.conv-123.*" - All events for conversation conv-123
   * - "hitl.*" - All HITL events
   * - "sandbox.sb-456.*" - All sandbox events for sb-456
   * - "*" - All events
   *
   * @param pattern - Event pattern to subscribe to
   * @param handler - Callback for matching events
   * @param options - Subscription options
   * @returns Unsubscribe function
   */
  subscribe(pattern: string, handler: EventHandler, options?: SubscriptionOptions): Unsubscribe {
    // Add to local subscriptions
    const handlers = this.subscriptions.get(pattern) || new Set();
    handlers.add(handler);
    this.subscriptions.set(pattern, handlers);

    // Send subscribe message to server
    this.sendMessage({
      type: 'subscribe',
      pattern,
      correlation_id: options?.correlationId,
    });

    // Return unsubscribe function
    return () => {
      const handlers = this.subscriptions.get(pattern);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          this.subscriptions.delete(pattern);
          // Send unsubscribe message to server
          this.sendMessage({
            type: 'unsubscribe',
            pattern,
          });
        }
      }
    };
  }

  /**
   * Subscribe to connection state changes
   */
  onStateChange(listener: (state: ConnectionState) => void): Unsubscribe {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  }

  /**
   * Add an error handler
   */
  onError(handler: ErrorHandler): Unsubscribe {
    this.errorHandlers.add(handler);
    return () => this.errorHandlers.delete(handler);
  }

  // ===========================================================================
  // Internal Methods
  // ===========================================================================

  private setState(state: ConnectionState): void {
    if (this.state !== state) {
      this.state = state;
      this.stateListeners.forEach((listener) => { listener(state); });
    }
  }

  private handleMessage(data: string): void {
    try {
      const message = JSON.parse(data);

      // Handle heartbeat response
      if (message.type === 'pong') {
        return;
      }

      // Handle event
      if (message.type === 'event' && message.envelope) {
        const envelope = message.envelope;
        if (isEventEnvelope(envelope)) {
          this.dispatchEvent(message.pattern, envelope);
        }
      }

      // Handle error from server
      if (message.type === 'error') {
        this.notifyError(new Error(message.message || 'Server error'));
      }
    } catch (err) {
      console.error('Failed to parse event bus message:', err);
    }
  }

  private dispatchEvent(pattern: string, envelope: EventEnvelope): void {
    // Check all subscriptions for matching patterns
    for (const [subPattern, handlers] of this.subscriptions) {
      if (this.matchesPattern(pattern, subPattern)) {
        handlers.forEach((handler) => {
          try {
            handler(envelope);
          } catch (_err) {
            console.error('Event handler error:', _err);
          }
        });
      }
    }
  }

  private matchesPattern(eventPattern: string, subscriptionPattern: string): boolean {
    // Exact match
    if (eventPattern === subscriptionPattern) return true;

    // Wildcard match
    if (subscriptionPattern === '*') return true;

    // Pattern matching with wildcards
    const eventParts = eventPattern.split('.');
    const subParts = subscriptionPattern.split('.');

    for (let i = 0; i < subParts.length; i++) {
      if (subParts[i] === '*') {
        // If this is the last part and it's *, match everything
        if (i === subParts.length - 1) return true;
        continue;
      }

      if (i >= eventParts.length) return false;
      if (subParts[i] !== eventParts[i]) return false;
    }

    return eventParts.length === subParts.length;
  }

  private sendMessage(message: Record<string, unknown>): void {
    const data = JSON.stringify(message);

    if (this.isConnected()) {
      this.ws!.send(data);
    } else {
      // Queue message for later
      this.messageQueue.push(data);
    }
  }

  private flushMessageQueue(): void {
    while (this.messageQueue.length > 0 && this.isConnected()) {
      const message = this.messageQueue.shift()!;
      this.ws!.send(message);
    }
  }

  private notifyError(error: Error): void {
    this.errorHandlers.forEach((handler) => {
      try {
        handler(error);
      } catch (_err) {
        console.error('Error handler threw:', _err);
      }
    });
  }

  // ===========================================================================
  // Reconnection
  // ===========================================================================

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
      console.error('Max reconnect attempts reached');
      return;
    }

    this.setState('reconnecting');
    this.reconnectAttempts++;

    // Calculate delay with exponential backoff
    const delay = Math.min(
      this.options.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
      this.options.maxReconnectDelay
    );

    this.reconnectTimer = setTimeout(async () => {
      try {
        await this.connect();
        // Re-subscribe to all patterns
        for (const pattern of this.subscriptions.keys()) {
          this.sendMessage({ type: 'subscribe', pattern });
        }
      } catch (_err) {
        // Will trigger another reconnect via onclose
      }
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  // ===========================================================================
  // Heartbeat
  // ===========================================================================

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (this.isConnected()) {
        this.sendMessage({ type: 'ping' });
      }
    }, this.options.heartbeatInterval);
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private clearConnectionTimer(): void {
    if (this.connectionTimer) {
      clearTimeout(this.connectionTimer);
      this.connectionTimer = null;
    }
  }
}

// =============================================================================
// Singleton Instance
// =============================================================================

let defaultClient: EventBusClient | null = null;

/**
 * Get the default event bus client
 */
export function getEventBusClient(): EventBusClient {
  if (!defaultClient) {
    defaultClient = new EventBusClient();
  }
  return defaultClient;
}

/**
 * Set a custom default client
 */
export function setEventBusClient(client: EventBusClient): void {
  defaultClient = client;
}

export default EventBusClient;
