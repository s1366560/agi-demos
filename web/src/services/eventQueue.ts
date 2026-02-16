/**
 * Event Queue Utility for Sequential Event Processing
 *
 * Provides priority-based event queue for handling agent events
 * in the correct order. Ensures that tools_updated events are
 * processed before mcp_app_registered events to prevent race
 * conditions where app registration tries to use stale tool lists.
 *
 * @module services/eventQueue
 */

/**
 * Queued event with metadata
 */
interface QueuedEvent {
  type: string;
  data: unknown;
  timestamp: number;
  conversationId?: string;
}

/**
 * Event handler function type
 */
type EventHandler = (event: { type: string; data: unknown; conversationId?: string }) => void | Promise<void>;

/**
 * Configuration for the event queue
 */
export interface EventQueueConfig {
  /** Events that should be processed with priority (in order of priority) */
  priorityEvents?: string[];
  /** Whether to enable debug logging */
  debug?: boolean;
}

/**
 * Default priority events - tools_updated must be processed before mcp_app_registered
 * to ensure the tool list is refreshed before app registration handlers run.
 */
const DEFAULT_PRIORITY_EVENTS = ['tools_updated', 'mcp_app_registered'];

/**
 * Event queue for sequential event processing with priority ordering.
 *
 * Features:
 * - Sequential processing: Events are processed one at a time
 * - Priority ordering: Priority events are processed before non-priority events
 * - Microtask scheduling: Uses Promise.resolve() for non-blocking scheduling
 * - Error handling: Continues processing even if a handler throws
 *
 * @example
 * ```typescript
 * const queue = new EventQueue();
 *
 * queue.on('tools_updated', (event) => {
 *   console.log('Refreshing tools...');
 * });
 *
 * queue.on('mcp_app_registered', (event) => {
 *   console.log('App registered:', event.data);
 * });
 *
 * // Events are automatically prioritized
 * queue.enqueue('mcp_app_registered', { app_id: 'app-1' });
 * queue.enqueue('tools_updated', { tools: [...] });
 * // tools_updated will be processed first despite being enqueued second
 * ```
 */
export class EventQueue {
  private queue: QueuedEvent[] = [];
  private processing = false;
  private handlers: Map<string, EventHandler[]> = new Map();
  private priorityEvents: string[];
  private processScheduled = false;
  private debug: boolean;

  // Track processing order for diagnostics
  public processedOrder: string[] = [];

  constructor(config?: EventQueueConfig) {
    this.priorityEvents = config?.priorityEvents ?? DEFAULT_PRIORITY_EVENTS;
    this.debug = config?.debug ?? false;
  }

  /**
   * Register a handler for an event type
   *
   * Multiple handlers can be registered for the same event type.
   * Handlers are called in the order they were registered.
   */
  on(eventType: string, handler: EventHandler): void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, []);
    }
    this.handlers.get(eventType)!.push(handler);
  }

  /**
   * Remove a handler for an event type
   */
  off(eventType: string, handler: EventHandler): void {
    const handlers = this.handlers.get(eventType);
    if (handlers) {
      const index = handlers.indexOf(handler);
      if (index > -1) {
        handlers.splice(index, 1);
      }
    }
  }

  /**
   * Enqueue an event for processing
   *
   * Priority events are inserted at the front of the queue in priority order.
   * Non-priority events are added to the end of the queue.
   */
  enqueue(type: string, data: unknown, conversationId?: string): void {
    const event: QueuedEvent = {
      type,
      data,
      timestamp: Date.now(),
      conversationId,
    };

    // Insert priority events at the correct position based on priority
    if (this.isPriorityEvent(type)) {
      const priority = this.getEventPriority(type);
      let insertIndex = this.queue.length; // Default to end

      // Find the position to insert (maintain priority order)
      for (let i = 0; i < this.queue.length; i++) {
        const eventPriority = this.getEventPriority(this.queue[i].type);
        if (priority < eventPriority) {
          // Insert before events with lower priority (higher number)
          insertIndex = i;
          break;
        }
      }
      this.queue.splice(insertIndex, 0, event);

      if (this.debug) {
        console.log(`[EventQueue] Inserted priority event "${type}" at index ${insertIndex}`);
      }
    } else {
      // Non-priority events go to the end
      this.queue.push(event);
    }

    // Schedule processing on next microtask to allow all events to be queued first
    this.scheduleProcessing();
  }

  /**
   * Check if event type is a priority event
   */
  private isPriorityEvent(type: string): boolean {
    return this.priorityEvents.includes(type);
  }

  /**
   * Get priority level for event type (lower = higher priority)
   */
  private getEventPriority(type: string): number {
    const index = this.priorityEvents.indexOf(type);
    return index === -1 ? 999 : index;
  }

  /**
   * Schedule processing on next microtask
   *
   * This ensures all events are added to the queue before processing begins,
   * allowing priority ordering to work correctly even when events arrive
   * in quick succession.
   */
  private scheduleProcessing(): void {
    if (this.processScheduled) {
      return;
    }
    this.processScheduled = true;
    // Use Promise.resolve().then() for microtask scheduling
    Promise.resolve().then(() => {
      this.processScheduled = false;
      this.processQueue();
    });
  }

  /**
   * Process events in queue sequentially
   */
  private async processQueue(): Promise<void> {
    if (this.processing || this.queue.length === 0) {
      return;
    }

    this.processing = true;

    while (this.queue.length > 0) {
      const event = this.queue.shift()!;

      // Track processed order for diagnostics
      this.processedOrder.push(event.type);

      if (this.debug) {
        console.log(`[EventQueue] Processing event "${event.type}"`, {
          conversationId: event.conversationId,
          queueRemaining: this.queue.length,
        });
      }

      // Call handlers
      const handlers = this.handlers.get(event.type) || [];
      for (const handler of handlers) {
        try {
          await handler({
            type: event.type,
            data: event.data,
            conversationId: event.conversationId,
          });
        } catch (err) {
          console.error(`[EventQueue] Error in handler for ${event.type}:`, err);
        }
      }
    }

    this.processing = false;
  }

  /**
   * Clear the queue and reset state
   */
  reset(): void {
    this.queue = [];
    this.processing = false;
    this.processScheduled = false;
    this.processedOrder = [];
  }

  /**
   * Get the number of events waiting in the queue
   */
  get length(): number {
    return this.queue.length;
  }

  /**
   * Check if the queue is currently processing events
   */
  get isProcessing(): boolean {
    return this.processing;
  }
}

/**
 * Global event queue instance for agent events
 *
 * This queue ensures that agent events are processed in the correct order:
 * 1. tools_updated - Refresh tool list first
 * 2. mcp_app_registered - Register apps after tools are refreshed
 * 3. Other events - Processed in FIFO order
 */
export const agentEventQueue = new EventQueue({
  priorityEvents: DEFAULT_PRIORITY_EVENTS,
  debug: import.meta.env.DEV,
});
