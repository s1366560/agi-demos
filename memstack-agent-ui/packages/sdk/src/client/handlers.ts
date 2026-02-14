/**
 * memstack-agent-ui - Event Handlers
 *
 * Event routing system for WebSocket events.
 * Maps event types to handlers and supports wildcard subscriptions.
 *
 * @packageDocumentation
 */

import type { EventType, EventHandler, AgentEvent } from './types';

/**
 * Event router for agent events
 *
 * Manages event type to handler mappings and supports both
 * specific event subscriptions and wildcard (all events) subscriptions.
 */
export class EventRouter {
  private handlers: Map<EventType, Set<EventHandler>>;
  private anyHandlers: Set<EventHandler>;

  constructor() {
    this.handlers = new Map();
    this.anyHandlers = new Set();
  }

  /**
   * Subscribe to a specific event type
   *
   * @param eventType - Event type to subscribe to
   * @param handler - Callback function for events
   * @returns Unsubscribe function that removes the handler
   *
   * @example
   * ```typescript
   * const unsubscribe = eventRouter.on('message', (event) => {
   *   console.log('Message:', event.data);
   * });
   *
   * // Later, to unsubscribe
   * unsubscribe();
   * ```
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
   * @returns Unsubscribe function that removes the handler
   *
   * @example
   * ```typescript
   * const unsubscribe = eventRouter.onAny((event) => {
   *   console.log('Event:', event.type, event.data);
   * });
   *
   * // Later, to unsubscribe
   * unsubscribe();
   * ```
   */
  onAny(handler: EventHandler): () => void {
    this.anyHandlers.add(handler);
    return () => this.anyHandlers.delete(handler);
  }

  /**
   * Route an event to all registered handlers
   *
   * @param event - Event to route
   *
   * Routes the event to:
   * 1. All handlers registered for this specific event type
   * 2. All "any" handlers registered for wildcard subscription
   */
  route(event: AgentEvent<Record<string, unknown>>): void {
    const { type } = event;

    // Route to type-specific handlers
    if (this.handlers.has(type)) {
      const handlers = this.handlers.get(type)!;
      handlers.forEach((handler) => {
        try {
          handler(event);
        } catch (err) {
          console.error(`[EventRouter] Handler error for ${type}:`, err);
        }
      });
    }

    // Route to wildcard handlers
    this.anyHandlers.forEach((handler) => {
      try {
        handler(event);
      } catch (err) {
        console.error('[EventRouter] Any handler error:', err);
      }
    });
  }

  /**
   * Remove all handlers for an event type
   *
   * @param eventType - Event type to clear handlers for
   */
  clear(eventType: EventType): void {
    this.handlers.delete(eventType);
  }

  /**
   * Remove all handlers
   */
  clearAll(): void {
    this.handlers.clear();
    this.anyHandlers.clear();
  }

  /**
   * Get count of handlers for an event type
   *
   * @param eventType - Event type to query
   * @returns Number of handlers registered
   */
  handlerCount(eventType: EventType): number {
    return this.handlers.get(eventType)?.size ?? 0;
  }

  /**
   * Get total handler count
   *
   * @returns Total number of handlers across all event types
   */
  get totalHandlerCount(): number {
    let count = this.anyHandlers.size;
    for (const handlers of this.handlers.values()) {
      count += handlers.size;
    }
    return count;
  }
}
