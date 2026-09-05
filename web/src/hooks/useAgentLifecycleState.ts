import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
} from '../plugins/webOperationAdmissionV2';
/**
 * React hook for subscribing to Agent lifecycle state changes via WebSocket.
 *
 * This hook provides real-time updates on the ProjectReActAgent lifecycle,
 * including initialization, execution, and shutdown states.
 *
 * @example
 * ```tsx
 * function AgentStatus() {
 *   const { lifecycleState, status, isConnected } = useAgentLifecycleState({
 *     projectId: 'proj-123',
 *     tenantId: 'tenant-456',
 *     enabled: true,
 *   });
 *
 *   return (
 *     <div>
 *       <div>State: {status.label}</div>
 *       <div>Tools: {lifecycleState?.toolCount || 0}</div>
 *     </div>
 *   );
 * }
 * ```
 */

import { useState, useEffect, useMemo, useSyncExternalStore } from 'react';

import { useTranslation } from 'react-i18next';

import { useAuthStore } from '@/stores/auth';

import { agentService } from '../services/agentService';

import type { LifecycleStateData, LifecycleStatus } from '../types/agent';

// Global lock to prevent duplicate subscriptions in React StrictMode
const globalSubscriptionLock = new WeakMap<object, Map<string, symbol>>();

export interface UseAgentLifecycleStateOptions {
  projectId: string;
  tenantId: string;
  enabled?: boolean | undefined;
}

export interface UseAgentLifecycleStateResult {
  lifecycleState: LifecycleStateData | null;
  isConnected: boolean;
  error: string | null;
  status: LifecycleStatus;
}

/**
 * Hook for real-time Agent lifecycle state via WebSocket
 */
export function useAgentLifecycleState({
  projectId,
  tenantId,
  enabled = true,
}: UseAgentLifecycleStateOptions): UseAgentLifecycleStateResult {
  const availability = useSyncExternalStore(
    subscribeWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2
  );
  const { t } = useTranslation();
  const [lifecycleState, setLifecycleState] = useState<LifecycleStateData | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const token = useAuthStore((state) => state.token);

  const [stateScope, setStateScope] = useState({ availability, projectId, tenantId });
  if (
    stateScope.availability !== availability ||
    stateScope.projectId !== projectId ||
    stateScope.tenantId !== tenantId
  ) {
    setStateScope({ availability, projectId, tenantId });
    setLifecycleState(null);
    setIsConnected(false);
    setError(null);
  }

  const lockKey = `lifecycle-state-${tenantId}:${projectId}`;

  useEffect(() => {
    if (!enabled || !projectId || !token || !availability.available) return;
    const locks = globalSubscriptionLock.get(availability.owner) ?? new Map<string, symbol>();
    globalSubscriptionLock.set(availability.owner, locks);
    const ticket = Symbol();
    if (locks.has(lockKey)) return;
    locks.set(lockKey, ticket);
    let cancelled = false;
    let release: (() => void) | undefined;
    const current = () =>
      !cancelled &&
      getWebOperationAvailabilityV2().owner === availability.owner &&
      getWebOperationAvailabilityV2().available;
    void (async () => {
      try {
        const operation = await agentService.connectSession();
        if (!current()) return;
        agentService.assertSession(operation);
        setIsConnected(agentService.isConnected());
        release = agentService.subscribeLifecycleState(
          projectId,
          tenantId,
          (state) => {
            if (current()) setLifecycleState(state);
          },
          operation
        );
      } catch {
        if (current()) setError('Failed to connect');
      }
    })();
    const unsubscribeStatusListener = agentService.onStatusChange((status) => {
      if (current()) setIsConnected(status === 'connected');
    });
    return () => {
      cancelled = true;
      unsubscribeStatusListener();
      release?.();
      if (locks.get(lockKey) === ticket) locks.delete(lockKey);
    };
  }, [enabled, projectId, tenantId, lockKey, token, availability]);

  // Compute detailed status based on lifecycle state
  const status = useMemo<LifecycleStatus>(() => {
    if (!lifecycleState) {
      return {
        label: t('agent.lifecycle.notStarted.label'),
        color: 'text-slate-500',
        icon: 'Power',
        description: t('agent.lifecycle.notStarted.description'),
      };
    }

    switch (lifecycleState.lifecycleState) {
      case 'initializing':
        return {
          label: t('agent.lifecycle.initializing.label'),
          color: 'text-blue-500',
          icon: 'Loader2',
          description: t('agent.lifecycle.initializing.description'),
        };

      case 'ready':
        return {
          label: t('agent.lifecycle.ready.label'),
          color: 'text-emerald-500',
          icon: 'CheckCircle',
          description: t('agent.lifecycle.ready.description', {
            count: lifecycleState.toolCount || 0,
          }),
        };

      case 'executing':
        return {
          label: t('agent.lifecycle.running.label'),
          color: 'text-amber-500',
          icon: 'Cpu',
          description: t('agent.lifecycle.running.description'),
        };

      case 'paused':
        return {
          label: t('agent.lifecycle.paused.label'),
          color: 'text-orange-500',
          icon: 'Pause',
          description: t('agent.lifecycle.paused.description'),
        };

      case 'shutting_down':
        return {
          label: t('agent.lifecycle.shuttingDown.label'),
          color: 'text-slate-500',
          icon: 'Power',
          description: t('agent.lifecycle.shuttingDown.description'),
        };

      case 'error':
        return {
          label: t('agent.lifecycle.error.label'),
          color: 'text-red-500',
          icon: 'AlertCircle',
          description: lifecycleState.errorMessage || t('agent.lifecycle.error.description'),
        };

      default:
        return {
          label: t('agent.lifecycle.unknown.label'),
          color: 'text-gray-500',
          icon: 'HelpCircle',
          description: t('agent.lifecycle.unknown.description'),
        };
    }
  }, [lifecycleState, t]);

  return {
    lifecycleState,
    isConnected,
    error,
    status,
  };
}
