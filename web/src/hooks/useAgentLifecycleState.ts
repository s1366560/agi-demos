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

import { useState, useEffect, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { agentService } from '../services/agentService';
import { logger } from '../utils/logger';

import type { LifecycleStateData, LifecycleStatus } from '../types/agent';

// Global lock to prevent duplicate subscriptions in React StrictMode
const globalSubscriptionLock = new Set<string>();

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
  const { t } = useTranslation();
  const [lifecycleState, setLifecycleState] = useState<LifecycleStateData | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lockKey = `lifecycle-state-${tenantId}:${projectId}`;

  useEffect(() => {
    if (!enabled || !projectId) {
      return;
    }

    let isCancelled = false;
    let ownsSubscription = false;

    if (globalSubscriptionLock.has(lockKey)) {
      logger.debug('[useAgentLifecycleState] Already subscribed globally, skipping');
      return () => {
        isCancelled = true;
      };
    }

    const connectAndSubscribe = async () => {
      try {
        if (!agentService.isConnected()) {
          await agentService.connect();
        }

        if (isCancelled) {
          return;
        }

        setIsConnected(agentService.isConnected());

        if (!globalSubscriptionLock.has(lockKey)) {
          globalSubscriptionLock.add(lockKey);
          ownsSubscription = true;
          agentService.subscribeLifecycleState(projectId, tenantId, (state) => {
            if (!isCancelled) {
              setLifecycleState(state);
            }
          });
          logger.info('[useAgentLifecycleState] Subscribed to lifecycle state updates');
        }
      } catch (err) {
        if (isCancelled) {
          return;
        }
        logger.error('[useAgentLifecycleState] Failed to connect:', err);
        setError('Failed to connect');
        if (ownsSubscription) {
          globalSubscriptionLock.delete(lockKey);
          ownsSubscription = false;
        }
      }
    };

    void connectAndSubscribe();

    // Listen to agentService connection status changes
    const unsubscribeStatusListener = agentService.onStatusChange((status) => {
      setIsConnected(status === 'connected');
    });

    // Cleanup on unmount or when dependencies change
    return () => {
      isCancelled = true;
      unsubscribeStatusListener();
      if (ownsSubscription) {
        agentService.unsubscribeLifecycleState();
        globalSubscriptionLock.delete(lockKey);
        ownsSubscription = false;
      }
    };
  }, [enabled, projectId, tenantId, lockKey]);

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
