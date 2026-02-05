/**
 * Unified Event Service - Single WebSocket for all event types
 *
 * Provides a unified WebSocket connection for all event domains:
 * - Agent conversation events
 * - Sandbox lifecycle events
 * - System events
 * - HITL (Human-in-the-Loop) events
 *
 * Features:
 * - Single connection for all event types (reduced resource usage)
 * - Topic-based subscriptions with routing keys
 * - Automatic reconnection with exponential backoff
 * - Heartbeat to keep connection alive
 * - Type-safe event routing
 *
 * @packageDocumentation
 */

import { logger } from "../utils/logger";
import { getAuthToken } from "../utils/tokenResolver";

import { createWebSocketUrl } from "./client/urlUtils";

// =============================================================================
// Types
// =============================================================================

/**
 * Topic types supported by the unified event service
 */
export type TopicType = "agent" | "sandbox" | "system" | "lifecycle";

/**
 * WebSocket connection status
 */
export type WebSocketStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

/**
 * Generic event from the unified WebSocket
 */
export interface UnifiedEvent<T = unknown> {
  type: string;
  routing_key?: string;
  conversation_id?: string;
  project_id?: string;
  data?: T;
  event_id?: string;
  seq?: number;
  timestamp?: string;
}

/**
 * Event handler callback type
 */
export type EventHandler<T = unknown> = (event: UnifiedEvent<T>) => void;

/**
 * Server message format
 */
interface ServerMessage {
  type: string;
  routing_key?: string;
  conversation_id?: string;
  project_id?: string;
  data?: unknown;
  event_id?: string;
  seq?: number;
  timestamp?: string;
  action?: string;
}

// =============================================================================
// Unified Event Service
// =============================================================================

/**
 * Generate a unique session ID for this browser tab
 */
function generateSessionId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
}

/**
 * Unified Event Service Implementation
 *
 * Manages a single WebSocket connection for all event types.
 * Supports topic-based subscriptions with automatic routing.
 */
class UnifiedEventServiceImpl {
  private ws: WebSocket | null = null;
  private status: WebSocketStatus = "disconnected";
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private isManualClose = false;

  // Unique session ID for this browser tab
  private sessionId: string = generateSessionId();

  // Heartbeat to keep connection alive
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private readonly HEARTBEAT_INTERVAL_MS = 30000;

  // Topic subscriptions: topic -> Set of handlers
  private subscriptions: Map<string, Set<EventHandler>> = new Map();

  // Status change listeners
  private statusListeners: Set<(status: WebSocketStatus) => void> = new Set();

  // Connection lock to prevent parallel connection attempts
  private connectingPromise: Promise<void> | null = null;

  // Pending subscribe/unsubscribe messages (sent after connection)
  private pendingMessages: Array<Record<string, unknown>> = [];

  /**
   * Get the session ID
   */
  getSessionId(): string {
    return this.sessionId;
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
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  /**
   * Connect to the WebSocket server
   */
  connect(): Promise<void> {
    if (this.connectingPromise) {
      logger.debug(
        "[UnifiedWS] Connection already in progress, returning existing promise"
      );
      return this.connectingPromise;
    }

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      logger.debug("[UnifiedWS] Already connected");
      return Promise.resolve();
    }

    this.isManualClose = false;
    this.setStatus("connecting");
    this.connectingPromise = this.doConnect();
    return this.connectingPromise;
  }

  private doConnect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const token = getAuthToken();
      if (!token) {
        this.setStatus("error");
        this.connectingPromise = null;
        reject(new Error("No authentication token"));
        return;
      }

      const wsUrl = createWebSocketUrl("/agent/ws", {
        token,
        session_id: this.sessionId,
      });

      try {
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
          logger.debug(
            `[UnifiedWS] Connected (session: ${this.sessionId.substring(0, 8)}...)`
          );
          this.setStatus("connected");
          this.reconnectAttempts = 0;
          this.reconnectDelay = 1000;
          this.connectingPromise = null;

          // Start heartbeat
          this.startHeartbeat();

          // Send pending messages
          this.flushPendingMessages();

          // Resubscribe to topics
          this.resubscribeAll();

          resolve();
        };

        this.ws.onmessage = (event) => {
          try {
            const message: ServerMessage = JSON.parse(event.data);
            this.handleMessage(message);
          } catch (err) {
            logger.error("[UnifiedWS] Failed to parse message:", err);
          }
        };

        this.ws.onclose = (event) => {
          logger.debug("[UnifiedWS] Disconnected", event.code, event.reason);
          this.setStatus("disconnected");
          this.stopHeartbeat();

          if (
            !this.isManualClose &&
            this.reconnectAttempts < this.maxReconnectAttempts
          ) {
            this.scheduleReconnect();
          }
        };

        this.ws.onerror = (error) => {
          logger.error("[UnifiedWS] Error:", error);
          this.setStatus("error");
          this.stopHeartbeat();
          this.connectingPromise = null;
          reject(error);
        };
      } catch (err) {
        logger.error("[UnifiedWS] Connection error:", err);
        this.setStatus("error");
        this.connectingPromise = null;
        this.scheduleReconnect();
        reject(err);
      }
    });
  }

  /**
   * Disconnect from the WebSocket server
   */
  disconnect(): void {
    this.isManualClose = true;
    this.stopHeartbeat();

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.setStatus("disconnected");
  }

  /**
   * Register a status change listener
   */
  onStatusChange(listener: (status: WebSocketStatus) => void): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  // ===========================================================================
  // Topic Subscription
  // ===========================================================================

  /**
   * Subscribe to a topic
   *
   * @param topic - Topic string (e.g., "agent:conv-123", "sandbox:proj-456")
   * @param handler - Event handler callback
   * @returns Unsubscribe function
   */
  subscribe(topic: string, handler: EventHandler): () => void {
    // Add to local subscriptions
    if (!this.subscriptions.has(topic)) {
      this.subscriptions.set(topic, new Set());
    }
    this.subscriptions.get(topic)!.add(handler);

    // Send subscribe message to server
    const [topicType] = topic.split(":");
    this.sendSubscribeMessage(topicType, topic);

    logger.debug(`[UnifiedWS] Subscribed to ${topic}`);

    // Return unsubscribe function
    return () => this.unsubscribe(topic, handler);
  }

  /**
   * Unsubscribe from a topic
   */
  unsubscribe(topic: string, handler: EventHandler): void {
    const handlers = this.subscriptions.get(topic);
    if (handlers) {
      handlers.delete(handler);
      if (handlers.size === 0) {
        this.subscriptions.delete(topic);
        // Send unsubscribe message to server
        const [topicType] = topic.split(":");
        this.sendUnsubscribeMessage(topicType, topic);
      }
    }
    logger.debug(`[UnifiedWS] Unsubscribed from ${topic}`);
  }

  /**
   * Subscribe to multiple topics at once
   */
  subscribeMultiple(
    topics: string[],
    handler: EventHandler
  ): () => void {
    const unsubscribeFns = topics.map((topic) => this.subscribe(topic, handler));
    return () => unsubscribeFns.forEach((fn) => fn());
  }

  // ===========================================================================
  // Convenience Methods
  // ===========================================================================

  /**
   * Subscribe to agent conversation events
   */
  subscribeAgent(conversationId: string, handler: EventHandler): () => void {
    return this.subscribe(`agent:${conversationId}`, handler);
  }

  /**
   * Subscribe to sandbox events for a project
   */
  subscribeSandbox(projectId: string, handler: EventHandler): () => void {
    const topic = `sandbox:${projectId}`;

    // Send specific sandbox subscription message
    this.sendOrQueue({
      type: "subscribe_sandbox",
      project_id: projectId,
    });

    // Track locally
    if (!this.subscriptions.has(topic)) {
      this.subscriptions.set(topic, new Set());
    }
    this.subscriptions.get(topic)!.add(handler);

    logger.debug(`[UnifiedWS] Subscribed to sandbox:${projectId}`);

    return () => {
      const handlers = this.subscriptions.get(topic);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          this.subscriptions.delete(topic);
          this.sendOrQueue({
            type: "unsubscribe_sandbox",
            project_id: projectId,
          });
        }
      }
    };
  }

  /**
   * Subscribe to lifecycle state events for a project
   */
  subscribeLifecycle(projectId: string, handler: EventHandler): () => void {
    const topic = `lifecycle:${projectId}`;

    this.sendOrQueue({
      type: "subscribe_lifecycle_state",
      project_id: projectId,
    });

    if (!this.subscriptions.has(topic)) {
      this.subscriptions.set(topic, new Set());
    }
    this.subscriptions.get(topic)!.add(handler);

    return () => {
      const handlers = this.subscriptions.get(topic);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          this.subscriptions.delete(topic);
          this.sendOrQueue({
            type: "unsubscribe_lifecycle_state",
            project_id: projectId,
          });
        }
      }
    };
  }

  // ===========================================================================
  // Message Sending
  // ===========================================================================

  /**
   * Send a message through WebSocket
   */
  send(message: Record<string, unknown>): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  /**
   * Send a message or queue it if not connected
   */
  sendOrQueue(message: Record<string, unknown>): void {
    if (!this.send(message)) {
      this.pendingMessages.push(message);
    }
  }

  // ===========================================================================
  // Internal Methods
  // ===========================================================================

  private handleMessage(message: ServerMessage): void {
    const { type, routing_key, conversation_id, project_id, data } = message;

    // Handle internal messages
    if (type === "connected" || type === "pong" || type === "ack") {
      logger.debug(`[UnifiedWS] ${type}:`, data);
      return;
    }

    // Route based on routing_key or derive topic from message
    let topic: string | undefined;

    if (routing_key) {
      topic = routing_key;
    } else if (conversation_id) {
      topic = `agent:${conversation_id}`;
    } else if (type === "sandbox_event" && project_id) {
      topic = `sandbox:${project_id}`;
    } else if (type === "lifecycle_state_change" && project_id) {
      topic = `lifecycle:${project_id}`;
    } else if (type === "sandbox_state_change" && project_id) {
      topic = `sandbox:${project_id}`;
    }

    if (topic) {
      const handlers = this.subscriptions.get(topic);
      if (handlers && handlers.size > 0) {
        const event: UnifiedEvent = {
          type,
          routing_key,
          conversation_id,
          project_id,
          data,
          event_id: message.event_id,
          seq: message.seq,
          timestamp: message.timestamp,
        };

        handlers.forEach((handler) => {
          try {
            handler(event);
          } catch (err) {
            logger.error(`[UnifiedWS] Handler error for ${topic}:`, err);
          }
        });
      }
    }

    // Also emit to wildcard listeners if any
    const wildcardHandlers = this.subscriptions.get("*");
    if (wildcardHandlers) {
      const event: UnifiedEvent = { type, routing_key, data };
      wildcardHandlers.forEach((handler) => {
        try {
          handler(event);
        } catch (err) {
          logger.error("[UnifiedWS] Wildcard handler error:", err);
        }
      });
    }
  }

  private sendSubscribeMessage(topicType: string, topic: string): void {
    const parts = topic.split(":");
    switch (topicType) {
      case "agent":
        this.sendOrQueue({
          type: "subscribe",
          conversation_id: parts[1],
        });
        break;
      case "sandbox":
        this.sendOrQueue({
          type: "subscribe_sandbox",
          project_id: parts[1],
        });
        break;
      case "lifecycle":
        this.sendOrQueue({
          type: "subscribe_lifecycle_state",
          project_id: parts[1],
        });
        break;
    }
  }

  private sendUnsubscribeMessage(topicType: string, topic: string): void {
    const parts = topic.split(":");
    switch (topicType) {
      case "agent":
        this.sendOrQueue({
          type: "unsubscribe",
          conversation_id: parts[1],
        });
        break;
      case "sandbox":
        this.sendOrQueue({
          type: "unsubscribe_sandbox",
          project_id: parts[1],
        });
        break;
      case "lifecycle":
        this.sendOrQueue({
          type: "unsubscribe_lifecycle_state",
          project_id: parts[1],
        });
        break;
    }
  }

  private flushPendingMessages(): void {
    while (this.pendingMessages.length > 0) {
      const message = this.pendingMessages.shift();
      if (message) {
        this.send(message);
      }
    }
  }

  private resubscribeAll(): void {
    this.subscriptions.forEach((_, topic) => {
      const [topicType] = topic.split(":");
      this.sendSubscribeMessage(topicType, topic);
    });
  }

  private setStatus(status: WebSocketStatus): void {
    this.status = status;
    this.statusListeners.forEach((listener) => {
      try {
        listener(status);
      } catch (err) {
        logger.error("[UnifiedWS] Status listener error:", err);
      }
    });
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      return;
    }

    this.reconnectAttempts++;
    const delay =
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    logger.debug(
      `[UnifiedWS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
    );

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect().catch((err) => {
        logger.error("[UnifiedWS] Reconnect failed:", err);
      });
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatInterval = setInterval(() => {
      if (this.isConnected()) {
        this.send({ type: "heartbeat" });
      }
    }, this.HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  // ===========================================================================
  // Statistics
  // ===========================================================================

  /**
   * Get subscription statistics
   */
  getStats(): { totalTopics: number; topicsByType: Record<string, number> } {
    const topicsByType: Record<string, number> = {
      agent: 0,
      sandbox: 0,
      lifecycle: 0,
      system: 0,
    };

    this.subscriptions.forEach((_, topic) => {
      const [type] = topic.split(":");
      if (type in topicsByType) {
        topicsByType[type]++;
      }
    });

    return {
      totalTopics: this.subscriptions.size,
      topicsByType,
    };
  }
}

// =============================================================================
// Singleton Export
// =============================================================================

/**
 * Global unified event service instance
 */
export const unifiedEventService = new UnifiedEventServiceImpl();

/**
 * Export the class for type usage
 */
export type UnifiedEventService = UnifiedEventServiceImpl;
