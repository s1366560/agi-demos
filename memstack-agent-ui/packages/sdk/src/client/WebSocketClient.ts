/**
 * memstack-agent-ui - WebSocket Client
 *
 * WebSocket client for Agent communication with automatic reconnection,
 * heartbeat, and event routing.
 *
 * @packageDocumentation
 */

import type { EventType } from './types';

/**
 * WebSocket connection status
 */
export type WebSocketStatus =
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'error';

/**
 * WebSocket message interface
 *
 * Represents a message received from the Agent WebSocket server.
 */
export interface WebSocketMessage {
  /** Message type identifier */
  type: string;

  /** Optional conversation ID for routing */
  conversation_id?: string;

  /** Message payload */
  data?: unknown;

  /** Event timestamp (microseconds) */
  event_time_us?: number;

  /** Event counter for ordering */
  event_counter?: number;

  /** ISO timestamp string */
  timestamp?: string;

  /** Action identifier for commands */
  action?: string;
}

/**
 * Event handler callback type
 *
 * Called when an event is received from WebSocket.
 */
export type EventHandler = (event: AgentEvent) => void;

/**
 * Agent event wrapper
 *
 * Wraps event type and data for type-safe routing.
 */
export interface AgentEvent<T = unknown> {
  /** Event type from EventType union */
  type: T;

  /** Event payload data */
  data: T;

  /** Optional conversation ID */
  conversation_id?: string;

  /** Event timestamp */
  timestamp?: number;
}

/**
 * Connection options
 */
export interface WebSocketClientOptions {
  /** WebSocket server URL */
  url: string;

  /** Optional authentication token */
  token?: string;

  /** Optional conversation ID to subscribe to */
  conversationId?: string;

  /** Heartbeat interval in milliseconds (default: 30000) */
  heartbeatInterval?: number;

  /** Maximum reconnection attempts (default: 5) */
  maxReconnectAttempts?: number;

  /** Initial reconnection delay in milliseconds (default: 1000) */
  reconnectDelay?: number;

  /** Callback when connection status changes */
  onStatusChange?: (status: WebSocketStatus) => void;

  /** Callback when connection error occurs */
  onError?: (error: Error) => void;
}

/**
 * WebSocket client implementation
 *
 * Manages WebSocket connection lifecycle with:
 * - Automatic reconnection with exponential backoff
 * - Heartbeat to keep connection alive
 * - Event routing to registered handlers
 * - Multi-conversation support via session IDs
 */
export class WebSocketClient {
  private ws: WebSocket | null = null;
  private status: WebSocketStatus = 'disconnected';
  private reconnectAttempts = 0;
  private maxReconnectAttempts: number;
  private reconnectDelay: number;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private isManualClose = false;

  /** Unique session ID for multi-tab support */
  public readonly sessionId: string;

  /** Heartbeat interval */
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private readonly HEARTBEAT_INTERVAL_MS = 30000; // 30 seconds

  /** Event handlers by type */
  private handlers: Map<EventType, Set<EventHandler>> = new Map();

  /** Event handlers for all events */
  private anyHandlers: Set<EventHandler> = new Set();

  /** Status change listeners */
  private statusListeners: Set<(status: WebSocketStatus) => void> = new Set();

  /** Options */
  private options: Required<WebSocketClientOptions, 'url'>;

  constructor(options: WebSocketClientOptions) {
    this.options = options;
    this.sessionId = this.generateSessionId();
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 5;
    this.reconnectDelay = options.reconnectDelay ?? 1000;
  }

  /**
   * Generate a unique session ID
   */
  private generateSessionId(): string {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    // Fallback for older browsers
    return `${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
  }

  /**
   * Get current connection status
   */
  getStatus(): WebSocketStatus {
    return this.status;
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.status === 'connected';
  }

  /**
   * Connect to WebSocket server
   */
  connect(): Promise<void> {
    // Return existing connection attempt if in progress
    if (this.reconnectTimeout) {
      return new Promise((resolve) => {
        // Will resolve when current connection completes
        const checkConnection = () => {
          if (this.status === 'connected' || this.status === 'error') {
            resolve();
          } else if (this.status !== 'connecting') {
            resolve(); // Connection attempt completed
          } else {
            setTimeout(checkConnection, 100);
          }
        };
        checkConnection();
      });
    }

    // Already connected
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return Promise.resolve();
    }

    this.isManualClose = false;
    this.setStatus('connecting');

    return new Promise((resolve, reject) => {
      try {
        const ws = new WebSocket(this.buildWebSocketUrl());

        ws.onopen = () => {
          this.setStatus('connected');
          this.reconnectAttempts = 0;
          this.reconnectDelay = 1000;
          resolve();

          // Start heartbeat
          this.startHeartbeat();

          // Resubscribe to previous handlers
          this.resubscribe();
        };

        ws.onmessage = (event) => {
          try {
            const message: WebSocketMessage = JSON.parse(event.data);
            this.handleMessage(message);
          } catch (err) {
            console.error('[WebSocketClient] Failed to parse message:', err);
          }
        };

        ws.onclose = (event) => {
          this.setStatus('disconnected');
          this.stopHeartbeat();

          if (!this.isManualClose && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.scheduleReconnect();
          } else {
            this.reconnectTimeout = null;
          }
        };

        ws.onerror = (error) => {
          this.setStatus('error');
          this.stopHeartbeat();
          this.reconnectTimeout = null;
          reject(error);
        };

        this.ws = ws;
      } catch (err) {
        this.setStatus('error');
        this.stopHeartbeat();
        this.reconnectTimeout = null;
        reject(err);
      }
    });
  }

  /**
   * Build WebSocket URL with query parameters
   */
  private buildWebSocketUrl(): string {
    const url = new URL(this.options.url);

    // Add token if provided
    if (this.options.token) {
      url.searchParams.set('token', this.options.token);
    }

    // Add session_id for multi-tab support
    url.searchParams.set('session_id', this.sessionId);

    return url.toString();
  }

  /**
   * Disconnect from WebSocket server
   *
   * Manually closes WebSocket connection and stops automatic reconnection.
   */
  disconnect(): void {
    this.isManualClose = true;

    // Stop heartbeat
    this.stopHeartbeat();

    // Clear reconnect timeout
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    // Close WebSocket
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.setStatus('disconnected');
  }

  /**
   * Set connection status
   */
  private setStatus(status: WebSocketStatus): void {
    if (this.status !== status) {
      this.status = status;
      this.statusListeners.forEach((listener) => {
        try {
          listener(status);
        } catch (err) {
          console.error('[WebSocketClient] Status listener error:', err);
        }
      });
    }
  }

  /**
   * Schedule reconnection attempt
   */
  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      return; // Already scheduled
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    this.reconnectTimeout = setTimeout(() => {
      this.connect().catch((err) => {
        console.error('[WebSocketClient] Reconnect failed:', err);
      });
    }, delay);
  }

  /**
   * Resubscribe to all event handlers
   *
   * Called after reconnection to restore subscriptions.
   */
  private resubscribe(): void {
    for (const [eventType, handlers] of this.handlers) {
      for (const handler of handlers) {
        // Re-subscribe to conversation-specific events
        if (this.options.conversationId) {
          this.send({
            type: 'subscribe',
            conversation_id: this.options.conversationId,
          });
        }
        }
      }
    }
  }

  /**
   * Start heartbeat to keep connection alive
   */
  private startHeartbeat(): void {
    this.stopHeartbeat();

    this.heartbeatInterval = setInterval(() => {
      if (this.isConnected()) {
        this.send({ type: 'ping' });
      }
    }, this.HEARTBEAT_INTERVAL_MS);
  }

  /**
   * Stop heartbeat
   */
  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  /**
   * Send a message through WebSocket
   *
   * @param message - Message object to send
   * @returns true if message was sent successfully, false otherwise
   */
  send(message: Omit<WebSocketMessage, 'type'>): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  /**
   * Handle incoming WebSocket message
   *
   * Routes incoming messages to appropriate handlers based on event type.
   */
  private handleMessage(message: WebSocketMessage): void {
    const { type, conversation_id, data, timestamp } = message;

    // Create typed event
    const event: AgentEvent = {
      type,
      data,
      conversation_id,
      timestamp: timestamp || Date.now(),
    };

    // Route to type-specific handlers
    if (type && this.handlers.has(type as EventType)) {
      const handlers = this.handlers.get(type as EventType);
      handlers?.forEach((handler) => {
        try {
          handler(event);
        } catch (err) {
          console.error(`[WebSocketClient] Handler error for ${type}:`, err);
        }
      });
    }

    // Route to global handlers
    this.anyHandlers.forEach((handler) => {
      try {
        handler(event);
      } catch (err) {
        console.error('[WebSocketClient] Any handler error:', err);
      }
    });
  }

  /**
   * Register a status change listener
   *
   * @param listener - Callback function invoked with new status
   * @returns Unsubscribe function that removes the listener
   */
  onStatusChange(listener: (status: WebSocketStatus) => void): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  /**
   * Subscribe to specific event type
   *
   * @param eventType - Event type to subscribe to
   * @param handler - Callback function for events
   * @returns Unsubscribe function
   */
  on<T extends EventType>(
    eventType: T,
    handler: (event: AgentEvent<Record<string, unknown>>) => void
  ): () => void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set());
    }
    this.handlers.get(eventType)!.add(handler);

    return () => this.handlers.get(eventType)?.delete(handler);
  }

  /**
   * Subscribe to all events
   *
   * @param handler - Callback function for all events
   * @returns Unsubscribe function
   */
  onAny(handler: EventHandler): () => void {
    this.anyHandlers.add(handler);
    return () => this.anyHandlers.delete(handler);
  }
}
