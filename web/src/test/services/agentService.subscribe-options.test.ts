import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { agentService } from '@/services/agentService';

import type { AgentStreamHandler, SandboxStateData } from '@/types/agent';

describe('agentService subscribe recovery options', () => {
  const service = agentService as any;

  beforeEach(() => {
    if (service.idleDisconnectTimeout) {
      clearTimeout(service.idleDisconnectTimeout);
      service.idleDisconnectTimeout = null;
    }
    service.subscriptions = new Set<string>();
    service.handlers = new Map<string, AgentStreamHandler>();
    service.subscriptionOptions = new Map<string, Record<string, unknown>>();
    service.statusSubscriber = null;
    service.lifecycleStateSubscriber = null;
    service.sandboxStateSubscriber = null;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
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

  it('disconnects after the last realtime subscription is removed', () => {
    vi.useFakeTimers();
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    const disconnectSpy = vi.spyOn(agentService, 'disconnect').mockImplementation(() => {});
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    service.subscriptions.add('conv-idle');

    agentService.unsubscribe('conv-idle');

    expect(sendSpy).toHaveBeenCalledWith({
      type: 'unsubscribe',
      conversation_id: 'conv-idle',
    });
    expect(disconnectSpy).not.toHaveBeenCalled();

    vi.advanceTimersByTime(4999);
    expect(disconnectSpy).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(disconnectSpy).toHaveBeenCalledTimes(1);
  });

  it('keeps the connection open when a new subscription arrives during the idle grace window', () => {
    vi.useFakeTimers();
    vi.spyOn(service, 'send').mockReturnValue(true);
    const disconnectSpy = vi.spyOn(agentService, 'disconnect').mockImplementation(() => {});
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    service.subscriptions.add('conv-old');

    agentService.unsubscribe('conv-old');
    agentService.subscribe('conv-new', {} as AgentStreamHandler);

    vi.advanceTimersByTime(5000);

    expect(disconnectSpy).not.toHaveBeenCalled();
    expect(service.subscriptions.has('conv-new')).toBe(true);
  });

  it('does not resend lifecycle subscribe for the same project and tenant', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    const firstCallback = vi.fn();
    const secondCallback = vi.fn();

    agentService.subscribeLifecycleState('proj-1', 'tenant-1', firstCallback);
    agentService.subscribeLifecycleState('proj-1', 'tenant-1', secondCallback);

    expect(sendSpy).toHaveBeenCalledTimes(1);
    expect(sendSpy).toHaveBeenCalledWith({
      type: 'subscribe_lifecycle_state',
      project_id: 'proj-1',
      tenant_id: 'tenant-1',
    });
    expect(service.lifecycleStateSubscriber.callback).toBe(secondCallback);
  });

  it('unsubscribes the previous lifecycle key before subscribing to a new one', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    const callback = vi.fn();

    agentService.subscribeLifecycleState('proj-1', 'tenant-1', callback);
    agentService.subscribeLifecycleState('proj-2', 'tenant-2', callback);

    expect(sendSpy).toHaveBeenNthCalledWith(1, {
      type: 'subscribe_lifecycle_state',
      project_id: 'proj-1',
      tenant_id: 'tenant-1',
    });
    expect(sendSpy).toHaveBeenNthCalledWith(2, {
      type: 'unsubscribe_lifecycle_state',
      project_id: 'proj-1',
      tenant_id: 'tenant-1',
    });
    expect(sendSpy).toHaveBeenNthCalledWith(3, {
      type: 'subscribe_lifecycle_state',
      project_id: 'proj-2',
      tenant_id: 'tenant-2',
    });
  });

  it('ignores stale lifecycle unsubscribe requests after the subscription changes', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    service.lifecycleStateSubscriber = {
      projectId: 'proj-new',
      tenantId: 'tenant-new',
      callback: vi.fn(),
    };

    agentService.unsubscribeLifecycleState({
      projectId: 'proj-old',
      tenantId: 'tenant-old',
    });

    expect(sendSpy).not.toHaveBeenCalled();
    expect(service.lifecycleStateSubscriber).toEqual(
      expect.objectContaining({
        projectId: 'proj-new',
        tenantId: 'tenant-new',
      })
    );
  });

  it('does not resend sandbox subscribe for the same project and tenant', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    const firstCallback = vi.fn();
    const secondCallback = vi.fn();

    agentService.subscribeSandboxState('proj-1', 'tenant-1', firstCallback);
    agentService.subscribeSandboxState('proj-1', 'tenant-1', secondCallback);

    expect(sendSpy).toHaveBeenCalledTimes(1);
    expect(sendSpy).toHaveBeenCalledWith({
      type: 'subscribe_sandbox',
      project_id: 'proj-1',
      tenant_id: 'tenant-1',
    });
    expect(service.sandboxStateSubscriber.callback).toBe(secondCallback);
  });

  it('includes tenant scope when unsubscribing sandbox state', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    service.sandboxStateSubscriber = {
      projectId: 'proj-1',
      tenantId: 'tenant-1',
      callback: (_state: SandboxStateData) => undefined,
    };

    agentService.unsubscribeSandboxState();

    expect(sendSpy).toHaveBeenCalledWith({
      type: 'unsubscribe_sandbox',
      project_id: 'proj-1',
      tenant_id: 'tenant-1',
    });
    expect(service.sandboxStateSubscriber).toBeNull();
  });

  it('ignores stale sandbox unsubscribe requests after the subscription changes', () => {
    const sendSpy = vi.spyOn(service, 'send').mockReturnValue(true);
    vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    service.sandboxStateSubscriber = {
      projectId: 'proj-new',
      tenantId: 'tenant-new',
      callback: vi.fn(),
    };

    agentService.unsubscribeSandboxState({
      projectId: 'proj-old',
      tenantId: 'tenant-old',
    });

    expect(sendSpy).not.toHaveBeenCalled();
    expect(service.sandboxStateSubscriber).toEqual(
      expect.objectContaining({
        projectId: 'proj-new',
        tenantId: 'tenant-new',
      })
    );
  });
});
