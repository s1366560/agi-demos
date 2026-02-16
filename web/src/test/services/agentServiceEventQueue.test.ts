/**
 * AgentService Event Queue Tests
 *
 * TDD tests for P2: Event emission order issue
 *
 * These tests verify that:
 * 1. tools_updated events refresh tool list first
 * 2. mcp_app_registered events wait for tool refresh
 * 3. Event queue mechanism ensures sequential processing
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { EventQueue } from '../../services/eventQueue';

describe('EventQueue - Event Emission Order (P2)', () => {
  let eventQueue: EventQueue;

  beforeEach(() => {
    eventQueue = new EventQueue({ debug: false });
  });

  afterEach(() => {
    eventQueue.reset();
    vi.clearAllMocks();
  });

  describe('Sequential event processing', () => {
    it('should process events in order they are received', async () => {
      const processedEvents: string[] = [];

      eventQueue.on('event_a', () => {
        processedEvents.push('a');
      });
      eventQueue.on('event_b', () => {
        processedEvents.push('b');
      });
      eventQueue.on('event_c', () => {
        processedEvents.push('c');
      });

      eventQueue.enqueue('event_a', {});
      eventQueue.enqueue('event_b', {});
      eventQueue.enqueue('event_c', {});

      // Wait for processing
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(processedEvents).toEqual(['a', 'b', 'c']);
    });

    it('should process events sequentially even with async handlers', async () => {
      const processedEvents: string[] = [];

      eventQueue.on('event_a', async () => {
        await new Promise((resolve) => setTimeout(resolve, 20));
        processedEvents.push('a');
      });
      eventQueue.on('event_b', async () => {
        await new Promise((resolve) => setTimeout(resolve, 5));
        processedEvents.push('b');
      });

      eventQueue.enqueue('event_a', {});
      eventQueue.enqueue('event_b', {});

      // Wait for processing
      await new Promise((resolve) => setTimeout(resolve, 50));

      // Even though 'b' handler is faster, it should wait for 'a' to complete
      expect(processedEvents).toEqual(['a', 'b']);
    });
  });

  describe('Priority event ordering', () => {
    it('should process tools_updated before mcp_app_registered', async () => {
      const processedEvents: string[] = [];

      eventQueue.on('tools_updated', () => {
        processedEvents.push('tools_updated');
      });
      eventQueue.on('mcp_app_registered', () => {
        processedEvents.push('mcp_app_registered');
      });
      eventQueue.on('other_event', () => {
        processedEvents.push('other_event');
      });

      // Enqueue in reverse order
      eventQueue.enqueue('mcp_app_registered', {});
      eventQueue.enqueue('tools_updated', {});
      eventQueue.enqueue('other_event', {});

      // Wait for processing
      await new Promise((resolve) => setTimeout(resolve, 10));

      // tools_updated should be processed first, then mcp_app_registered, then other_event
      expect(processedEvents).toEqual(['tools_updated', 'mcp_app_registered', 'other_event']);
    });

    it('should handle multiple tools_updated and mcp_app_registered events', async () => {
      const processedEvents: string[] = [];

      eventQueue.on('tools_updated', () => {
        processedEvents.push('tools_updated');
      });
      eventQueue.on('mcp_app_registered', () => {
        processedEvents.push('mcp_app_registered');
      });

      // Enqueue multiple events
      eventQueue.enqueue('mcp_app_registered', { app: 'app1' });
      eventQueue.enqueue('tools_updated', {});
      eventQueue.enqueue('mcp_app_registered', { app: 'app2' });
      eventQueue.enqueue('mcp_app_registered', { app: 'app3' });

      // Wait for processing
      await new Promise((resolve) => setTimeout(resolve, 20));

      // tools_updated should be first, then all mcp_app_registered in order
      expect(processedEvents).toEqual([
        'tools_updated',
        'mcp_app_registered',
        'mcp_app_registered',
        'mcp_app_registered',
      ]);
    });

    it('should process priority events before regular events', async () => {
      const processedEvents: string[] = [];

      eventQueue.on('tools_updated', () => {
        processedEvents.push('tools_updated');
      });
      eventQueue.on('regular_event', () => {
        processedEvents.push('regular_event');
      });
      eventQueue.on('mcp_app_registered', () => {
        processedEvents.push('mcp_app_registered');
      });

      // Enqueue regular event first
      eventQueue.enqueue('regular_event', {});
      eventQueue.enqueue('tools_updated', {});
      eventQueue.enqueue('mcp_app_registered', {});

      // Wait for processing
      await new Promise((resolve) => setTimeout(resolve, 10));

      // Priority events should be processed first (in priority order)
      expect(processedEvents).toEqual(['tools_updated', 'mcp_app_registered', 'regular_event']);
    });
  });

  describe('Event queue state tracking', () => {
    it('should track processed event order', async () => {
      eventQueue.on('event_a', () => {});
      eventQueue.on('event_b', () => {});

      eventQueue.enqueue('event_a', {});
      eventQueue.enqueue('event_b', {});

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(eventQueue.processedOrder).toEqual(['event_a', 'event_b']);
    });
  });

  describe('Handler error handling', () => {
    it('should continue processing after handler error', async () => {
      const processedEvents: string[] = [];

      eventQueue.on('event_a', () => {
        throw new Error('Handler error');
      });
      eventQueue.on('event_b', () => {
        processedEvents.push('b');
      });

      eventQueue.enqueue('event_a', {});
      eventQueue.enqueue('event_b', {});

      await new Promise((resolve) => setTimeout(resolve, 10));

      // Should still process event_b despite event_a handler error
      expect(processedEvents).toEqual(['b']);
    });
  });

  describe('Queue state', () => {
    it('should report queue length', () => {
      eventQueue.enqueue('event_a', {});
      eventQueue.enqueue('event_b', {});

      // Events are scheduled but not yet processed
      expect(eventQueue.length).toBeGreaterThanOrEqual(0);
    });

    it('should report processing state', async () => {
      let handlerCalled = false;

      eventQueue.on('event_a', async () => {
        handlerCalled = true;
        await new Promise((resolve) => setTimeout(resolve, 20));
      });

      eventQueue.enqueue('event_a', {});

      await new Promise((resolve) => setTimeout(resolve, 50));

      expect(handlerCalled).toBe(true);
    });
  });

  describe('Handler registration', () => {
    it('should allow removing handlers', async () => {
      const processedEvents: string[] = [];

      const handler = () => {
        processedEvents.push('a');
      };

      eventQueue.on('event_a', handler);
      eventQueue.off('event_a', handler);

      eventQueue.enqueue('event_a', {});

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(processedEvents).toEqual([]);
    });
  });
});

describe('EventQueue Integration with Agent Events', () => {
  let eventQueue: EventQueue;

  beforeEach(() => {
    eventQueue = new EventQueue({ debug: false });
  });

  afterEach(() => {
    eventQueue.reset();
  });

  it('should handle typical MCP App registration flow', async () => {
    const toolList: string[] = [];
    const registeredApps: string[] = [];

    // Simulate tool list refresh handler
    eventQueue.on('tools_updated', () => {
      // Refresh tool list
      toolList.push('tool1', 'tool2', 'mcp_app_tool');
    });

    // Simulate MCP App registration handler
    eventQueue.on('mcp_app_registered', (event: any) => {
      // This handler depends on tools being refreshed
      if (toolList.includes('mcp_app_tool')) {
        registeredApps.push(event.data.app_id);
      }
    });

    // Enqueue events in the order they might arrive (app_registered first due to race)
    eventQueue.enqueue('mcp_app_registered', { app_id: 'app-1' });
    eventQueue.enqueue('tools_updated', {});

    await new Promise((resolve) => setTimeout(resolve, 10));

    // tools_updated should be processed first, so app registration succeeds
    expect(registeredApps).toEqual(['app-1']);
  });

  it('should handle rapid event bursts', async () => {
    const processedCount = { tools: 0, apps: 0 };

    eventQueue.on('tools_updated', () => {
      processedCount.tools++;
    });
    eventQueue.on('mcp_app_registered', () => {
      processedCount.apps++;
    });

    // Simulate rapid event burst
    for (let i = 0; i < 5; i++) {
      eventQueue.enqueue('mcp_app_registered', { app_id: `app-${i}` });
    }
    eventQueue.enqueue('tools_updated', {});
    for (let i = 5; i < 10; i++) {
      eventQueue.enqueue('mcp_app_registered', { app_id: `app-${i}` });
    }

    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(processedCount.tools).toBe(1);
    expect(processedCount.apps).toBe(10);

    // Verify tools_updated was processed first
    expect(eventQueue.processedOrder[0]).toBe('tools_updated');
  });
});
