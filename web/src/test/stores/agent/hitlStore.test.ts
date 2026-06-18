import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useAgentHITLStore } from '../../../stores/agent/hitlStore';

vi.mock('../../../services/agentService', () => ({
  agentService: {
    getPendingHITLRequests: vi.fn(),
  },
}));

vi.mock('../../../utils/logger', () => ({
  logger: {
    debug: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

describe('agent HITL store', () => {
  beforeEach(() => {
    useAgentHITLStore.setState({
      pendingClarification: null,
      pendingDecision: null,
      pendingEnvVarRequest: null,
      pendingPermission: null,
      doomLoopDetected: null,
      costTracking: null,
      suggestions: [],
      pinnedEventIds: new Set(),
    });
    vi.clearAllMocks();
  });

  it('joins concurrent pending HITL loads for the same conversation', async () => {
    const agentServiceMock = vi.mocked(
      (await import('../../../services/agentService')).agentService
    );
    const responseRequest = deferred<{ requests: [] }>();
    agentServiceMock.getPendingHITLRequests.mockReturnValueOnce(responseRequest.promise as any);

    const firstLoad = useAgentHITLStore.getState().loadPendingHITL('conv-deduped');
    const secondLoad = useAgentHITLStore.getState().loadPendingHITL('conv-deduped');

    await Promise.resolve();

    expect(agentServiceMock.getPendingHITLRequests).toHaveBeenCalledTimes(1);
    responseRequest.resolve({ requests: [] });
    await Promise.all([firstLoad, secondLoad]);
  });

  it('skips recent completed pending HITL loads', async () => {
    const agentServiceMock = vi.mocked(
      (await import('../../../services/agentService')).agentService
    );
    agentServiceMock.getPendingHITLRequests.mockResolvedValue({ requests: [] } as any);

    await useAgentHITLStore.getState().loadPendingHITL('conv-recent');
    await useAgentHITLStore.getState().loadPendingHITL('conv-recent');

    expect(agentServiceMock.getPendingHITLRequests).toHaveBeenCalledTimes(1);
  });
});
