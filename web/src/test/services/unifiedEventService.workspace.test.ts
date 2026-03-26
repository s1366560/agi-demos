import { describe, expect, it, vi } from 'vitest';

import { unifiedEventService } from '@/services/unifiedEventService';

describe('unifiedEventService workspace routing', () => {
  it('subscribeWorkspace delegates to workspace topic subscription', () => {
    const subscribeSpy = vi.spyOn(
      unifiedEventService as unknown as { subscribe: Function },
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
});
