import { describe, expect, it, vi } from 'vitest';

import { unifiedEventService } from '@/services/unifiedEventService';

describe('unifiedEventService workspace routing', () => {
  it('subscribeWorkspace delegates to workspace topic subscription', () => {
    const subscribeSpy = vi.spyOn(
      unifiedEventService as unknown as {
        subscribe: (topic: string, handler: () => void) => () => void;
      },
      'subscribe'
    );

    const noop = () => {};
    const unsubscribe = unifiedEventService.subscribeWorkspace('ws-123', noop);

    expect(typeof unsubscribe).toBe('function');
    expect(subscribeSpy).toHaveBeenCalledWith('workspace:ws-123', noop);
    subscribeSpy.mockRestore();
  });

  it('dispatches workspace routing_key events to workspace topic handlers', () => {
    const handler = vi.fn();
    const internal = unifiedEventService as unknown as {
      subscriptions: Map<string, Set<(event: unknown) => void>>;
      handleMessage: (message: unknown) => void;
    };
    internal.subscriptions.set('workspace:ws-123', new Set([handler]));

    internal.handleMessage({
      type: 'topology_updated',
      routing_key: 'workspace:ws-123:topology_updated',
      data: { node_id: 'node-1' },
    });

    expect(handler).toHaveBeenCalledTimes(1);
    expect((handler.mock.calls[0] as [Record<string, unknown>])[0].routing_key).toBe(
      'workspace:ws-123:topology_updated'
    );

    internal.subscriptions.clear();
  });

  it('subscribeProject registers a project topic handler', () => {
    const noop = () => {};
    const unsubscribe = unifiedEventService.subscribeProject('proj-123', noop);
    const internal = unifiedEventService as unknown as {
      subscriptions: Map<string, Set<(event: unknown) => void>>;
    };

    expect(typeof unsubscribe).toBe('function');
    expect(internal.subscriptions.has('project:proj-123')).toBe(true);
    unsubscribe();
  });

  it('dispatches project routing_key events to project topic handlers', () => {
    const handler = vi.fn();
    const internal = unifiedEventService as unknown as {
      subscriptions: Map<string, Set<(event: unknown) => void>>;
      handleMessage: (message: unknown) => void;
    };
    internal.subscriptions.set('project:proj-123', new Set([handler]));

    internal.handleMessage({
      type: 'reflection_complete',
      routing_key: 'project:proj-123:reflection_complete',
      data: { applied_verdict_count: 1 },
      sequence_id: '1-0',
    });

    expect(handler).toHaveBeenCalledTimes(1);
    expect((handler.mock.calls[0] as [Record<string, unknown>])[0].routing_key).toBe(
      'project:proj-123:reflection_complete'
    );

    internal.subscriptions.clear();
  });

  it('dispatches conversation_created project events to project topic handlers', () => {
    const handler = vi.fn();
    const internal = unifiedEventService as unknown as {
      subscriptions: Map<string, Set<(event: unknown) => void>>;
      handleMessage: (message: unknown) => void;
    };
    internal.subscriptions.set('project:proj-123', new Set([handler]));

    internal.handleMessage({
      type: 'conversation_created',
      routing_key: 'project:proj-123:conversation_created',
      project_id: 'proj-123',
      data: { conversation_id: 'conv-1', project_id: 'proj-123' },
      sequence_id: '2-0',
    });

    expect(handler).toHaveBeenCalledTimes(1);
    expect((handler.mock.calls[0] as [Record<string, unknown>])[0]).toMatchObject({
      type: 'conversation_created',
      routing_key: 'project:proj-123:conversation_created',
      project_id: 'proj-123',
    });

    internal.subscriptions.clear();
  });
});
