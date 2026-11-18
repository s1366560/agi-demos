import { describe, expect, it, vi } from 'vitest';

import { agentService } from '@/services/agentService';
import { restApi } from '@/services/agent/restApi';

const { post } = vi.hoisted(() => ({ post: vi.fn().mockResolvedValue({}) }));
vi.mock('@/services/client/httpClient', () => ({ httpClient: { post } }));

describe('permission approval provenance transport', () => {
  it('sends mode only on automatic grants over WebSocket', async () => {
    const connected = vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    const send = vi
      .spyOn(agentService as unknown as { send: (value: unknown) => boolean }, 'send')
      .mockImplementation((value: unknown) => {
        const payload = value as { request_id: string; approval_mode?: string };
        if (payload.approval_mode)
          queueMicrotask(() =>
            (agentService as unknown as { handleMessage: (value: unknown) => void }).handleMessage({
              type: 'permission_response_ack',
              request_id: payload.request_id,
              success: true,
            })
          );
        return true;
      });
    try {
      await agentService.respondToPermission('auto', true, 'full_access');
      expect(send).toHaveBeenLastCalledWith({
        type: 'permission_respond',
        request_id: 'auto',
        granted: true,
        approval_mode: 'full_access',
      });
      await agentService.respondToPermission('manual', true);
      expect(send).toHaveBeenLastCalledWith({
        type: 'permission_respond',
        request_id: 'manual',
        granted: true,
      });
      await agentService.respondToPermission('denied', false, 'full_access');
      expect(send).toHaveBeenLastCalledWith({
        type: 'permission_respond',
        request_id: 'denied',
        granted: false,
      });
    } finally {
      connected.mockRestore();
      send.mockRestore();
    }
  });
  it('rejects automatic sends on a negative server acknowledgment or missing acknowledgment', async () => {
    vi.useFakeTimers();
    const connected = vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
    const transport = agentService as unknown as {
      send: (value: unknown) => boolean;
      handleMessage: (value: unknown) => void;
    };
    const send = vi.spyOn(transport, 'send').mockReturnValue(true);
    try {
      const rejected = agentService.respondToPermission('rejected', true, 'full_access');
      const rejection = expect(rejected).rejects.toThrow('Permission approval was rejected');
      transport.handleMessage({
        type: 'permission_response_ack',
        request_id: 'rejected',
        success: false,
      });
      await rejection;
      const timeout = agentService.respondToPermission('lost', true, 'full_access');
      const timedOut = expect(timeout).rejects.toThrow('Timed out');
      await vi.advanceTimersByTimeAsync(15000);
      await timedOut;
    } finally {
      connected.mockRestore();
      send.mockRestore();
      vi.useRealTimers();
    }
  });

  it('uses the same outer mode and explicit once scope in HTTP fallback', async () => {
    const connected = vi.spyOn(agentService, 'isConnected').mockReturnValue(false);
    try {
      await agentService.respondToPermission('auto', true, 'auto_edit');
      expect(post).toHaveBeenLastCalledWith('/agent/hitl/respond', {
        request_id: 'auto',
        hitl_type: 'permission',
        approval_mode: 'auto_edit',
        response_data: { granted: true, action: 'allow', scope: 'once' },
      });
      await restApi.respondToPermissionHttp('manual', true);
      expect(post).toHaveBeenLastCalledWith('/agent/hitl/respond', {
        request_id: 'manual',
        hitl_type: 'permission',
        response_data: { granted: true, action: 'allow', scope: 'once' },
      });
      await restApi.respondToPermissionHttp('deny', false, 'full_access');
      expect(post).toHaveBeenLastCalledWith('/agent/hitl/respond', {
        request_id: 'deny',
        hitl_type: 'permission',
        response_data: { granted: false, action: 'deny', scope: 'once' },
      });
    } finally {
      connected.mockRestore();
    }
  });
});
