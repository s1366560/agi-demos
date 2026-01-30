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

import { useState, useEffect, useMemo } from "react";
import { logger } from "../utils/logger";
import { agentService } from "../services/agentService";
import type { LifecycleStateData, LifecycleStatus } from "../types/agent";

// Global lock to prevent duplicate subscriptions in React StrictMode
const globalSubscriptionLock = new Set<string>();

export interface UseAgentLifecycleStateOptions {
  projectId: string;
  tenantId: string;
  enabled?: boolean;
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
  const [lifecycleState, setLifecycleState] = useState<LifecycleStateData | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lockKey = `lifecycle-state-${projectId}`;

  useEffect(() => {
    if (!enabled || !projectId) {
      // Unsubscribe if disabled or project changed
      if (globalSubscriptionLock.has(lockKey)) {
        agentService.unsubscribeLifecycleState();
        globalSubscriptionLock.delete(lockKey);
      }
      setIsConnected(false);
      return;
    }

    // GLOBAL LOCK: Prevent duplicate subscriptions in React StrictMode
    if (globalSubscriptionLock.has(lockKey)) {
      logger.debug("[useAgentLifecycleState] Already subscribed globally, skipping");
      return;
    }

    const connectAndSubscribe = async () => {
      try {
        // Connect agentService if needed
        if (!agentService.isConnected()) {
          await agentService.connect();
        }
        setIsConnected(agentService.isConnected());

        // Subscribe to lifecycle state updates (with global lock check)
        if (!globalSubscriptionLock.has(lockKey)) {
          globalSubscriptionLock.add(lockKey);
          agentService.subscribeLifecycleState(projectId, tenantId, (state) => {
            setLifecycleState(state);
          });
          logger.info("[useAgentLifecycleState] Subscribed to lifecycle state updates");
        }
      } catch (err) {
        logger.error("[useAgentLifecycleState] Failed to connect:", err);
        setError("Failed to connect");
        globalSubscriptionLock.delete(lockKey);
      }
    };

    connectAndSubscribe();

    // Listen to agentService connection status changes
    const unsubscribeStatusListener = agentService.onStatusChange((status) => {
      setIsConnected(status === "connected");
    });

    // Cleanup on unmount or when dependencies change
    return () => {
      unsubscribeStatusListener();
      if (globalSubscriptionLock.has(lockKey)) {
        agentService.unsubscribeLifecycleState();
        globalSubscriptionLock.delete(lockKey);
      }
    };
  }, [enabled, projectId, tenantId]);

  // Compute detailed status based on lifecycle state
  const status = useMemo<LifecycleStatus>(() => {
    if (!lifecycleState) {
      return {
        label: "Unknown",
        color: "text-gray-500",
        icon: "HelpCircle",
        description: "Agent state unknown",
      };
    }

    switch (lifecycleState.lifecycleState) {
      case "initializing":
        return {
          label: "Initializing",
          color: "text-amber-500",
          icon: "Loader2",
          description: "Agent session is starting up...",
        };

      case "ready":
        return {
          label: "Ready",
          color: "text-emerald-500",
          icon: "CheckCircle",
          description: `Agent ready with ${lifecycleState.toolCount || 0} tools`,
        };

      case "executing":
        return {
          label: "Executing",
          color: "text-blue-500",
          icon: "Play",
          description: "Agent is processing a request",
        };

      case "paused":
        return {
          label: "Paused",
          color: "text-yellow-500",
          icon: "Pause",
          description: "Agent is paused",
        };

      case "shutting_down":
        return {
          label: "Shutting Down",
          color: "text-orange-500",
          icon: "Power",
          description: "Agent is shutting down...",
        };

      case "error":
        return {
          label: "Error",
          color: "text-red-500",
          icon: "AlertCircle",
          description: lifecycleState.errorMessage || "Agent encountered an error",
        };

      default:
        return {
          label: "Unknown",
          color: "text-gray-500",
          icon: "HelpCircle",
          description: "Agent state unknown",
        };
    }
  }, [lifecycleState]);

  return {
    lifecycleState,
    isConnected,
    error,
    status,
  };
}
