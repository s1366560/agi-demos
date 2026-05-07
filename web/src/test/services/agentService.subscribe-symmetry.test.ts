import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { agentService } from '@/services/agentService';

import type { AgentStreamHandler, SubscribeOptions } from '@/types/agent';

/**
 * Defect #7 regression lock — the WebSocket subscriptions Set and the
 * subscriptionOptions Map are independently mutated; if subscribe / unsubscribe
 * ever drift, reconnect will try to resubscribe to a conversation we no longer
 * track (or skip one we do). These tests assert that the two structures stay
 * in lockstep across many subscribe / unsubscribe cycles.
 */
describe('agentService subscription symmetry', () => {
  const service = agentService as unknown as {
    subscriptions: Set<string>;
    subscriptionOptions: Map<string, SubscribeOptions>;
    handlers: Map<string, AgentStreamHandler>;
    send: (msg: unknown) => boolean;
  };

  beforeEach(() => {
    service.subscriptions = new Set();
    service.subscriptionOptions = new Map();
    service.handlers = new Map();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('subscribe + unsubscribe leaves both structures empty', () => {
    vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);

    const handler = {} as AgentStreamHandler;
    agentService.subscribe('conv-1', handler);
    agentService.unsubscribe('conv-1');

    expect(service.subscriptions.size).toBe(0);
    expect(service.subscriptionOptions.size).toBe(0);
    expect(service.handlers.size).toBe(0);
  });

  it('100x subscribe/unsubscribe cycles never drift', () => {
    vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);

    const handler = {} as AgentStreamHandler;
    for (let i = 0; i < 100; i += 1) {
      const id = `conv-${i}`;
      agentService.subscribe(id, handler, { from_counter: i });
      agentService.unsubscribe(id);
    }

    expect(service.subscriptions.size).toBe(0);
    expect(service.subscriptionOptions.size).toBe(0);
    expect(service.handlers.size).toBe(0);
  });

  it('interleaved subscribes and unsubscribes for many ids stay symmetric', () => {
    vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);

    const handler = {} as AgentStreamHandler;
    const ids = Array.from({ length: 50 }, (_, i) => `conv-${i}`);

    ids.forEach((id) => agentService.subscribe(id, handler));
    expect(service.subscriptions.size).toBe(50);
    expect(service.subscriptionOptions.size).toBe(50);
    expect(service.handlers.size).toBe(50);

    // Unsubscribe in reverse to amplify any ordering bugs
    [...ids].reverse().forEach((id) => agentService.unsubscribe(id));
    expect(service.subscriptions.size).toBe(0);
    expect(service.subscriptionOptions.size).toBe(0);
    expect(service.handlers.size).toBe(0);
  });

  it('unsubscribing an unknown id is a no-op and does not corrupt state', () => {
    vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);

    const handler = {} as AgentStreamHandler;
    agentService.subscribe('conv-real', handler);
    agentService.unsubscribe('conv-ghost');

    expect(service.subscriptions.has('conv-real')).toBe(true);
    expect(service.subscriptionOptions.has('conv-real')).toBe(true);
    expect(service.subscriptions.size).toBe(1);
    expect(service.subscriptionOptions.size).toBe(1);
  });
});
