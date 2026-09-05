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

import { logger } from '../utils/logger';
import { getWebOperationAvailabilityV2 } from '@/plugins/webOperationAdmissionV2';
import { UnifiedEventConnectionV2 } from './unifiedEventConnectionV2';

// =============================================================================
// Types
// =============================================================================

/**
 * Topic types supported by the unified event service
 */
export type TopicType = 'agent' | 'sandbox' | 'workspace' | 'project' | 'system' | 'lifecycle';

/**
 * WebSocket connection status
 */
export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

/**
 * Generic event from the unified WebSocket
 */
export interface UnifiedEvent<T = unknown> {
  type: string;
  routing_key?: string | undefined;
  conversation_id?: string | undefined;
  project_id?: string | undefined;
  sequence_id?: string | undefined;
  data?: T | undefined;
  event_id?: string | undefined;
  event_time_us?: number | undefined;
  event_counter?: number | undefined;
  timestamp?: string | undefined;
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
  routing_key?: string | undefined;
  conversation_id?: string | undefined;
  project_id?: string | undefined;
  sequence_id?: string | undefined;
  data?: unknown;
  event_id?: string | undefined;
  event_time_us?: number | undefined;
  event_counter?: number | undefined;
  timestamp?: string | undefined;
  action?: string | undefined;
  workspace_id?: string | undefined;
}

const CONTROL_EVENT_TYPES = new Set<string>(['connected', 'pong', 'ack']);
const IDLE_DISCONNECT_DELAY_MS = 5000;
const TOPIC_UNSUBSCRIBE_GRACE_MS = 250;

// =============================================================================
// Unified Event Service
// =============================================================================

/**
 * Generate a unique session ID for this browser tab
 */
function generateSessionId(): string {
  // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- retain fallback for older runtimes.
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${String(Date.now())}-${Math.random().toString(36).substring(2, 15)}`;
}

/**
 * Unified Event Service Implementation
 *
 * Manages a single WebSocket connection for all event types.
 * Supports topic-based subscriptions with automatic routing.
 */
class UnifiedEventServiceImpl {
  private connection: UnifiedEventConnectionV2 | null = null;
  private owner: object | null = null;
  private readonly retained = new Set<Promise<void>>();
  private retiring: Promise<void> | null = null;
  private status: WebSocketStatus = 'disconnected';
  private sessionId: string = generateSessionId();
  private subscriptionMessages = new Map<string, Record<string, unknown>>();

  // Topic subscriptions: topic -> Set of handlers
  private subscriptions: Map<string, Set<EventHandler>> = new Map();

  // Status change listeners
  private statusListeners: Set<(status: WebSocketStatus) => void> = new Set();

  // Connection lock to prevent parallel connection attempts

  // Pending subscribe/unsubscribe messages (sent after connection)
  private pendingMessages: Array<Record<string, unknown>> = [];
  private idleDisconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private pendingTopicUnsubscribes: Map<string, ReturnType<typeof setTimeout>> = new Map();

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
    return this.connection?.isConnected() ?? false;
  }

  private synchronizeOwner(): boolean {
    const availability = getWebOperationAvailabilityV2();
    if (!availability.available) {
      void this.disconnect().catch((error) => logger.error('[UnifiedWS] Retirement failed', error));
      return false;
    }
    if (this.owner !== availability.owner) {
      void this.disconnect().catch((error) => logger.error('[UnifiedWS] Retirement failed', error));
      this.owner = availability.owner;
    }
    return true;
  }

  connect(): Promise<void> {
    this.cancelIdleDisconnect();
    if (!this.synchronizeOwner())
      return Promise.reject(new Error('web_operation_generation_unavailable'));
    if (this.connection)
      return this.connection.isConnected() ? Promise.resolve() : this.connection.ready;
    const connection = new UnifiedEventConnectionV2({
      owner: this.owner!,
      beforeOpen: Promise.all([...this.retained]),
      sessionId: this.sessionId,
      status: (status) => {
        if (this.connection === connection) this.setStatus(status);
      },
      opened: () => {
        if (this.connection === connection) {
          this.flushPendingMessages();
          this.resubscribeAll();
        }
      },
      message: (event) => {
        if (this.connection !== connection) return;
        try {
          if (typeof event.data !== 'string') throw new Error('Expected text WebSocket message');
          this.handleMessage(JSON.parse(event.data) as ServerMessage);
        } catch (error) {
          logger.error('[UnifiedWS] Failed to parse message:', error);
        }
      },
      retired: () => {
        if (this.connection === connection) this.clearOwnerState();
      },
    });
    this.connection = connection;
    this.retiring = null;
    const drained = connection.done.catch((error) => {
      if (!(error instanceof DOMException && error.name === 'AbortError')) throw error;
    });
    this.retained.add(drained);
    void drained
      .finally(() => this.retained.delete(drained))
      .catch((error) => logger.error('[UnifiedWS] Connection failed', error));
    return connection.ready;
  }

  private clearOwnerState(): void {
    this.connection = null;
    this.owner = null;
    this.cancelIdleDisconnect();
    this.cancelAllPendingTopicUnsubscribes();
    this.subscriptions = new Map();
    this.subscriptionMessages.clear();
    this.pendingMessages = [];
    this.setStatus('disconnected');
  }

  disconnect(): Promise<void> {
    if (!this.connection && this.retiring) return this.retiring;
    const connection = this.connection;
    this.clearOwnerState();
    if (connection)
      void connection.stop().catch((error) => logger.error('[UnifiedWS] Close failed', error));
    this.retiring = Promise.all([...this.retained]).then(() => undefined);
    return this.retiring;
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
    if (!this.synchronizeOwner()) return () => undefined;
    this.cancelIdleDisconnect();
    const hadPendingUnsubscribe = this.cancelPendingTopicUnsubscribe(topic);
    const hadTopic = this.subscriptions.has(topic);

    // Add to local subscriptions
    if (!this.subscriptions.has(topic)) {
      this.subscriptions.set(topic, new Set());
    }
    const topicHandlers = this.subscriptions.get(topic);
    if (topicHandlers) {
      topicHandlers.add(handler);
    }

    this.ensureConnected();

    if (!hadTopic && !hadPendingUnsubscribe) {
      const topicType = topic.split(':')[0] ?? '';
      this.sendSubscribeMessage(topicType, topic);
    }

    logger.debug(`[UnifiedWS] Handler registered for ${topic}`);

    // Return unsubscribe function
    return () => {
      if (this.subscriptions.get(topic) === topicHandlers) this.unsubscribe(topic, handler);
    };
  }

  /**
   * Unsubscribe from a topic
   */
  unsubscribe(topic: string, handler: EventHandler): void {
    const handlers = this.subscriptions.get(topic);
    if (handlers) {
      handlers.delete(handler);
      if (handlers.size === 0) {
        this.scheduleTopicUnsubscribe(topic);
      }
    }
    logger.debug(`[UnifiedWS] Handler removed from ${topic}`);
  }

  /**
   * Subscribe to multiple topics at once
   */
  subscribeMultiple(topics: string[], handler: EventHandler): () => void {
    const unsubscribeFns = topics.map((topic) => this.subscribe(topic, handler));
    return () => {
      unsubscribeFns.forEach((fn) => {
        fn();
      });
    };
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
    return this.subscribe(`sandbox:${projectId}`, handler);
  }

  /**
   * Subscribe to workspace-scoped realtime events.
   */
  subscribeWorkspace(workspaceId: string, handler: EventHandler): () => void {
    return this.subscribe(`workspace:${workspaceId}`, handler);
  }

  /**
   * Subscribe to project-scoped domain events.
   */
  subscribeProject(projectId: string, handler: EventHandler, fromSequence?: string): () => void {
    if (!this.synchronizeOwner()) return () => undefined;
    if (fromSequence)
      this.subscriptionMessages.set(`project:${projectId}`, {
        type: 'subscribe_project_events',
        project_id: projectId,
        from_sequence: fromSequence,
      });
    return this.subscribe(`project:${projectId}`, handler);
  }

  subscribeLifecycle(projectId: string, handler: EventHandler): () => void {
    return this.subscribe(`lifecycle:${projectId}`, handler);
  }

  // ===========================================================================
  // Message Sending
  // ===========================================================================

  /**
   * Send a message through WebSocket
   */
  send(message: Record<string, unknown>): boolean {
    return this.connection?.send(message) ?? false;
  }

  sendOrQueue(message: Record<string, unknown>): void {
    if (!this.synchronizeOwner()) return;
    if (!this.send(message)) this.pendingMessages.push(message);
  }

  // ===========================================================================
  // Internal Methods
  // ===========================================================================

  private handleMessage(message: ServerMessage): void {
    const owner = this.owner;
    const { type, routing_key, conversation_id, project_id, data } = message;

    // Subscribe-then-resync: the bridge subscribes to Redis streams with "$"
    // (new entries only), so events published between the initial REST fetch
    // and the live subscription are lost. The subscribe ack marks the stream
    // as live; surface it to topic handlers so consumers can refetch the
    // authoritative state and reconcile the gap.
    if (
      type === 'ack' &&
      message.action === 'subscribe_workspace' &&
      typeof message.workspace_id === 'string'
    ) {
      this.dispatchToTopic(
        `workspace:${message.workspace_id}`,
        {
          type: 'workspace_subscribed',
          data: { workspace_id: message.workspace_id },
        },
        owner
      );
    }

    // Handle internal messages
    if (CONTROL_EVENT_TYPES.has(type)) {
      return;
    }

    // Route based on routing_key or derive topic from message
    let topic: string | undefined;

    if (routing_key) {
      topic = routing_key;
    } else if (conversation_id) {
      topic = `agent:${conversation_id}`;
    } else if (type === 'sandbox_event' && project_id) {
      topic = `sandbox:${project_id}`;
    } else if (type === 'lifecycle_state_change' && project_id) {
      topic = `lifecycle:${project_id}`;
    } else if (type === 'sandbox_state_change' && project_id) {
      topic = `sandbox:${project_id}`;
    } else if (type === 'reflection_complete' && project_id) {
      topic = `project:${project_id}`;
    }

    if (topic) {
      const event: UnifiedEvent = {
        type,
        routing_key,
        conversation_id,
        project_id,
        sequence_id: message.sequence_id,
        data,
        event_id: message.event_id,
        event_time_us: message.event_time_us,
        event_counter: message.event_counter,
        timestamp: message.timestamp,
      };

      this.dispatchToTopic(topic, event, owner);
      if (routing_key?.startsWith('workspace:')) {
        const workspaceTopic = routing_key.split(':').slice(0, 2).join(':');
        if (workspaceTopic !== topic) this.dispatchToTopic(workspaceTopic, event, owner);
      }
      if (routing_key?.startsWith('project:')) {
        const projectTopic = routing_key.split(':').slice(0, 2).join(':');
        if (projectTopic !== topic) this.dispatchToTopic(projectTopic, event, owner);
      }
    }

    // Also emit to wildcard listeners if any
    const wildcardHandlers = this.subscriptions.get('*');
    if (wildcardHandlers) {
      const event: UnifiedEvent = { type, routing_key, data };
      wildcardHandlers.forEach((handler) => {
        try {
          if (
            this.owner !== owner ||
            !getWebOperationAvailabilityV2().available ||
            getWebOperationAvailabilityV2().owner !== owner
          )
            return;
          handler(event);
        } catch (err) {
          logger.error('[UnifiedWS] Wildcard handler error:', err);
        }
      });
    }
  }

  private dispatchToTopic(topic: string, event: UnifiedEvent, owner: object | null): void {
    const handlers = this.subscriptions.get(topic);
    if (!handlers || handlers.size === 0) {
      return;
    }
    handlers.forEach((handler) => {
      try {
        if (
          this.owner !== owner ||
          !getWebOperationAvailabilityV2().available ||
          getWebOperationAvailabilityV2().owner !== owner
        )
          return;
        handler(event);
      } catch (err) {
        logger.error(`[UnifiedWS] Handler error for ${topic}:`, err);
      }
    });
  }

  private sendSubscribeMessage(topicType: string, topic: string): void {
    const replay = this.subscriptionMessages.get(topic);
    if (replay) {
      this.send(replay);
      return;
    }
    const parts = topic.split(':');
    let sent = false;
    switch (topicType) {
      case 'agent':
        sent = this.send({
          type: 'subscribe',
          conversation_id: parts[1],
        });
        break;
      case 'sandbox':
        sent = this.send({
          type: 'subscribe_sandbox',
          project_id: parts[1],
        });
        break;
      case 'workspace':
        sent = this.send({
          type: 'subscribe_workspace',
          workspace_id: parts[1],
        });
        break;
      case 'project':
        sent = this.send({
          type: 'subscribe_project_events',
          project_id: parts[1],
        });
        break;
      case 'lifecycle':
        sent = this.send({
          type: 'subscribe_lifecycle_state',
          project_id: parts[1],
        });
        break;
    }
    if (sent) {
      logger.debug(`[UnifiedWS] Subscribed to ${topic}`);
    }
  }

  private sendUnsubscribeMessage(topicType: string, topic: string): void {
    const parts = topic.split(':');
    let sent = false;
    switch (topicType) {
      case 'agent':
        sent = this.send({
          type: 'unsubscribe',
          conversation_id: parts[1],
        });
        break;
      case 'sandbox':
        sent = this.send({
          type: 'unsubscribe_sandbox',
          project_id: parts[1],
        });
        break;
      case 'workspace':
        sent = this.send({
          type: 'unsubscribe_workspace',
          workspace_id: parts[1],
        });
        break;
      case 'project':
        sent = this.send({
          type: 'unsubscribe_project_events',
          project_id: parts[1],
        });
        break;
      case 'lifecycle':
        sent = this.send({
          type: 'unsubscribe_lifecycle_state',
          project_id: parts[1],
        });
        break;
    }
    if (sent) {
      logger.debug(`[UnifiedWS] Unsubscribed from ${topic}`);
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

  private ensureConnected(): void {
    if (this.connection) {
      return;
    }
    void this.connect().catch((err: unknown) => {
      logger.error('[UnifiedWS] Auto-connect failed:', err);
    });
  }

  private resubscribeAll(): void {
    this.subscriptions.forEach((handlers, topic) => {
      if (handlers.size === 0) {
        return;
      }
      const topicType = topic.split(':')[0] ?? '';
      this.sendSubscribeMessage(topicType, topic);
    });
  }

  private setStatus(status: WebSocketStatus): void {
    this.status = status;
    this.statusListeners.forEach((listener) => {
      try {
        listener(status);
      } catch (err) {
        logger.error('[UnifiedWS] Status listener error:', err);
      }
    });
  }

  private cancelIdleDisconnect(): void {
    if (!this.idleDisconnectTimeout) {
      return;
    }
    clearTimeout(this.idleDisconnectTimeout);
    this.idleDisconnectTimeout = null;
  }

  private cancelPendingTopicUnsubscribe(topic: string): boolean {
    const timeout = this.pendingTopicUnsubscribes.get(topic);
    if (!timeout) {
      return false;
    }
    clearTimeout(timeout);
    this.pendingTopicUnsubscribes.delete(topic);
    return true;
  }

  private cancelAllPendingTopicUnsubscribes(): void {
    this.pendingTopicUnsubscribes.forEach((timeout) => {
      clearTimeout(timeout);
    });
    this.pendingTopicUnsubscribes.clear();
  }

  private scheduleTopicUnsubscribe(topic: string): void {
    if (this.pendingTopicUnsubscribes.has(topic)) {
      return;
    }

    const owner = this.owner;
    const timeout = setTimeout(() => {
      if (this.owner !== owner) return;
      this.pendingTopicUnsubscribes.delete(topic);
      const handlers = this.subscriptions.get(topic);
      if (handlers && handlers.size > 0) {
        return;
      }

      this.subscriptions.delete(topic);
      this.subscriptionMessages.delete(topic);
      const topicType = topic.split(':')[0] ?? '';
      this.sendUnsubscribeMessage(topicType, topic);
      this.scheduleIdleDisconnectIfUnused();
    }, TOPIC_UNSUBSCRIBE_GRACE_MS);

    this.pendingTopicUnsubscribes.set(topic, timeout);
  }

  private scheduleIdleDisconnectIfUnused(): void {
    if (
      this.subscriptions.size > 0 ||
      this.pendingMessages.length > 0 ||
      this.idleDisconnectTimeout ||
      !this.isConnected()
    ) {
      return;
    }

    const owner = this.owner;
    this.idleDisconnectTimeout = setTimeout(() => {
      if (this.owner !== owner) return;
      this.idleDisconnectTimeout = null;
      if (this.subscriptions.size === 0 && this.pendingMessages.length === 0) {
        void this.disconnect().catch((error) =>
          logger.error('[UnifiedWS] Idle retirement failed', error)
        );
      }
    }, IDLE_DISCONNECT_DELAY_MS);
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
      workspace: 0,
      project: 0,
      lifecycle: 0,
      system: 0,
    };

    this.subscriptions.forEach((_, topic) => {
      const handlers = this.subscriptions.get(topic);
      if (!handlers || handlers.size === 0) {
        return;
      }
      const [type] = topic.split(':');
      if (type && type in topicsByType) {
        const key = type;
        topicsByType[key] = (topicsByType[key] ?? 0) + 1;
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

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    void unifiedEventService
      .disconnect()
      .catch((error) => logger.error('[UnifiedWS] HMR retirement failed', error));
  });
}

/**
 * Export the class for type usage
 */
export type UnifiedEventService = UnifiedEventServiceImpl;
