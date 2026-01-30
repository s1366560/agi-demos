import { useState, useEffect, useMemo } from 'react';
import { logger } from '../utils/logger';
import { agentService } from '../services/agentService';

// Global lock to prevent duplicate connections in React StrictMode
const globalSubscriptionLock = new Set<string>();

export interface AgentSessionStatus {
  is_initialized: boolean;
  is_active: boolean;
  total_chats: number;
  active_chats: number;
  tool_count: number;
  cached_since?: string;
  workflow_id?: string;
}

export interface DetailedStatus {
  label: string;
  color: string;
  icon: string;
  description: string;
}

interface UseAgentStatusWebSocketOptions {
  projectId: string;
  isStreaming?: boolean;
  agentState?: string;
  activeToolCallsCount?: number;
  enabled?: boolean;
}

/**
 * Hook for real-time Agent Session status via WebSocket
 * 
 * This hook REUSES the agentService's WebSocket connection instead of creating
 * a new one. It sends subscribe_status/unsubscribe_status messages through the
 * shared connection.
 */
export function useAgentStatusWebSocket({
  projectId,
  isStreaming = false,
  agentState = 'idle',
  activeToolCallsCount = 0,
  enabled = true,
}: UseAgentStatusWebSocketOptions) {
  const [sessionStatus, setSessionStatus] = useState<AgentSessionStatus | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Connect to agentService and subscribe to status updates
  useEffect(() => {
    const lockKey = `status-sub-${projectId}`;
    
    if (!enabled || !projectId) {
      // Unsubscribe if disabled or project changed
      if (globalSubscriptionLock.has(lockKey)) {
        agentService.unsubscribeStatus();
        globalSubscriptionLock.delete(lockKey);
      }
      setIsConnected(false);
      return;
    }

    // GLOBAL LOCK: Prevent duplicate subscriptions in React StrictMode
    if (globalSubscriptionLock.has(lockKey)) {
      logger.debug('[useAgentStatusWebSocket] Already subscribed globally, skipping');
      return;
    }

    // Connect to agentService if not already connected
    const connectAndSubscribe = async () => {
      try {
        // Connect agentService if needed
        if (!agentService.isConnected()) {
          await agentService.connect();
        }
        setIsConnected(agentService.isConnected());

        // Subscribe to status updates for this project (with global lock check)
        if (!globalSubscriptionLock.has(lockKey)) {
          globalSubscriptionLock.add(lockKey);
          agentService.subscribeStatus(projectId, (status) => {
            setSessionStatus(status as AgentSessionStatus);
          });
          logger.info('[useAgentStatusWebSocket] Subscribed to status updates');
        }
      } catch (err) {
        logger.error('[useAgentStatusWebSocket] Failed to connect:', err);
        setError('Failed to connect');
        globalSubscriptionLock.delete(lockKey);
      }
    };

    connectAndSubscribe();

    // Listen to agentService connection status changes
    const unsubscribeStatusListener = agentService.onStatusChange((status) => {
      setIsConnected(status === 'connected');
    });
    
    // Cleanup on unmount or when dependencies change
    return () => {
      unsubscribeStatusListener();
      if (globalSubscriptionLock.has(lockKey)) {
        agentService.unsubscribeStatus();
        globalSubscriptionLock.delete(lockKey);
      }
    };
  }, [enabled, projectId]);

  // Compute detailed status based on streaming state, tool calls, and session status
  const detailedStatus = useMemo<DetailedStatus>(() => {
    // Priority 1: Session initialization status from WebSocket
    if (sessionStatus) {
      if (!sessionStatus.is_initialized) {
        return {
          label: 'Initializing',
          color: 'text-amber-500',
          icon: 'Loader2',
          description: 'Agent session is starting up...',
        };
      }
      
      if (sessionStatus.is_active && activeToolCallsCount > 0) {
        return {
          label: `Using ${activeToolCallsCount} Tool${activeToolCallsCount > 1 ? 's' : ''}`,
          color: 'text-blue-500',
          icon: 'Wrench',
          description: `Agent is using ${activeToolCallsCount} tool(s)`,
        };
      }
    }

    // Priority 2: Streaming state from props
    if (isStreaming) {
      return {
        label: 'Thinking',
        color: 'text-amber-500',
        icon: 'Loader2',
        description: 'Agent is processing your request',
      };
    }

    // Priority 3: Active tool calls from props
    if (activeToolCallsCount > 0) {
      return {
        label: `Using ${activeToolCallsCount} Tool${activeToolCallsCount > 1 ? 's' : ''}`,
        color: 'text-blue-500',
        icon: 'Wrench',
        description: `Agent is using ${activeToolCallsCount} tool(s)`,
      };
    }

    // Priority 4: Agent state from props
    if (agentState === 'planning') {
      return {
        label: 'Planning',
        color: 'text-purple-500',
        icon: 'GitBranch',
        description: 'Agent is creating a plan',
      };
    }

    if (agentState === 'executing') {
      return {
        label: 'Executing',
        color: 'text-blue-500',
        icon: 'Play',
        description: 'Agent is executing the plan',
      };
    }

    // Default: Ready
    return {
      label: 'Ready',
      color: 'text-emerald-500',
      icon: 'CheckCircle',
      description: 'Agent is ready to help',
    };
  }, [sessionStatus, isStreaming, activeToolCallsCount, agentState]);

  return {
    sessionStatus,
    isConnected,
    error,
    detailedStatus,
  };
}
