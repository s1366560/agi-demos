import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { agentService } from '@/services/agentService';

import type { AgentStreamHandler } from '@/types/agent';

describe('agentService subscribe recovery options', () => {
  const service = agentService as any;

  beforeEach(() => {
    service.subscriptions = new Set<string>();
    service.handlers = new Map<string, AgentStreamHandler>();
    service.subscriptionOptions = new Map<string, Record<string, unknown>>();
    service.statusSubscriber = null;
    service.lifecycleStateSubscriber = null;
    service.sandboxStateSubscriber = null;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('sends subscribe payload with recovery cursor', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);

    agentService.subscribe('conv-1', {} as AgentStreamHandler, {
      message_id: 'msg-1',
      from_time_us: 123,
      from_counter: 4,
    });

    expect(sendSpy).toHaveBeenCalledWith({
      type: 'subscribe',
      conversation_id: 'conv-1',
      message_id: 'msg-1',
      from_time_us: 123,
      from_counter: 4,
    });
    expect(service.subscriptionOptions.get('conv-1')).toEqual({
      message_id: 'msg-1',
      from_time_us: 123,
      from_counter: 4,
    });
  });

  it('resubscribe reuses stored recovery cursor', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    service.subscriptions.add('conv-2');
    service.subscriptionOptions.set('conv-2', {
      message_id: 'msg-2',
      from_time_us: 200,
      from_counter: 8,
    });

    service.resubscribe();

    expect(sendSpy).toHaveBeenCalledWith({
      type: 'subscribe',
      conversation_id: 'conv-2',
      message_id: 'msg-2',
      from_time_us: 200,
      from_counter: 8,
    });
  });

  it('unsubscribe clears stored recovery cursor', () => {
    vi.spyOn(agentService, 'isConnected').mockReturnValue(false);
    service.subscriptions.add('conv-3');
    service.subscriptionOptions.set('conv-3', { message_id: 'msg-3' });

    agentService.unsubscribe('conv-3');

    expect(service.subscriptionOptions.has('conv-3')).toBe(false);
  });

  it('resends subscribe when options change for existing subscription', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);

    service.subscriptions.add('conv-4');
    service.subscriptionOptions.set('conv-4', {
      message_id: 'msg-old',
      from_time_us: 10,
      from_counter: 1,
    });

    agentService.subscribe('conv-4', {} as AgentStreamHandler, {
      message_id: 'msg-new',
      from_time_us: 20,
      from_counter: 2,
    });

    expect(sendSpy).toHaveBeenCalledWith({
      type: 'subscribe',
      conversation_id: 'conv-4',
      message_id: 'msg-new',
      from_time_us: 20,
      from_counter: 2,
    });
  });

  it('replaces a stale cursor when resubscribing with only a running message id', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);

    service.subscriptions.add('conv-5');
    service.subscriptionOptions.set('conv-5', {
      from_time_us: 999,
      from_counter: 9,
    });

    agentService.subscribe('conv-5', {} as AgentStreamHandler, {
      message_id: 'msg-running',
    });

    expect(sendSpy).toHaveBeenCalledWith({
      type: 'subscribe',
      conversation_id: 'conv-5',
      message_id: 'msg-running',
    });
    expect(service.subscriptionOptions.get('conv-5')).toEqual({
      message_id: 'msg-running',
    });
  });
});
