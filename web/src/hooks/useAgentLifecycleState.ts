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
        label: "未启动",
        color: "text-slate-500",
        icon: "Power",
        description: "Agent 尚未初始化，将在首次请求时自动启动",
      };
    }

    switch (lifecycleState.lifecycleState) {
      case "initializing":
        return {
          label: "初始化中",
          color: "text-blue-500",
          icon: "Loader2",
          description: "正在加载工具、技能和配置",
        };

      case "ready":
        return {
          label: "就绪",
          color: "text-emerald-500",
          icon: "CheckCircle",
          description: `Agent 已就绪，${lifecycleState.toolCount || 0} 个工具`,
        };

      case "executing":
        return {
          label: "执行中",
          color: "text-amber-500",
          icon: "Cpu",
          description: "正在处理聊天请求",
        };

      case "paused":
        return {
          label: "已暂停",
          color: "text-orange-500",
          icon: "Pause",
          description: "Agent 已暂停，不接收新请求",
        };

      case "shutting_down":
        return {
          label: "关闭中",
          color: "text-slate-500",
          icon: "Power",
          description: "Agent 正在关闭",
        };

      case "error":
        return {
          label: "错误",
          color: "text-red-500",
          icon: "AlertCircle",
          description: lifecycleState.errorMessage || "Agent 遇到错误",
        };

      default:
        return {
          label: "未知",
          color: "text-gray-500",
          icon: "HelpCircle",
          description: "Agent 状态未知",
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
