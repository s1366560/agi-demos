/**
 * useProjectAgentLifecycle - Hook for ProjectReActAgent lifecycle management
 *
 * Provides:
 * - Real-time lifecycle status monitoring
 * - Polling for status updates
 * - Actions (refresh, pause, resume, stop)
 * - Metrics tracking
 *
 * @module hooks/useProjectAgentLifecycle
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  agentStatusService,
  AgentSessionStatus,
  ProjectAgentMetrics,
} from '../services/agentStatusService';
import { logger } from '../utils/logger';

interface UseProjectAgentLifecycleOptions {
  projectId: string;
  pollingInterval?: number;
  enabled?: boolean;
}

interface UseProjectAgentLifecycleReturn {
  /** Current session status */
  sessionStatus: AgentSessionStatus | null;
  /** Agent metrics */
  metrics: ProjectAgentMetrics | null;
  /** Whether data is loading */
  isLoading: boolean;
  /** Error message if any */
  error: string | null;
  /** Refresh status manually */
  refresh: () => Promise<void>;
  /** Pause the agent */
  pause: () => Promise<void>;
  /** Resume the agent */
  resume: () => Promise<void>;
  /** Stop the agent */
  stop: () => Promise<void>;
  /** Reload agent (refresh tools, clear caches) */
  reload: () => Promise<void>;
}

export function useProjectAgentLifecycle({
  projectId,
  pollingInterval = 10000, // 10 seconds default
  enabled = true,
}: UseProjectAgentLifecycleOptions): UseProjectAgentLifecycleReturn {
  const [sessionStatus, setSessionStatus] = useState<AgentSessionStatus | null>(null);
  const [metrics, setMetrics] = useState<ProjectAgentMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  /**
   * Fetch session status
   */
  const fetchStatus = useCallback(async () => {
    if (!enabled || !projectId) return;

    try {
      // Cancel previous request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      abortControllerRef.current = new AbortController();

      const status = await agentStatusService.getAgentSessionStatus(projectId);
      setSessionStatus(status);
      setError(null);
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        logger.warn('[useProjectAgentLifecycle] Failed to fetch status:', err);
        // Don't set error for 404 (workflow not found is normal when not initialized)
        if (err.status !== 404) {
          setError(err.message);
        }
        // Set a default uninitialized status
        setSessionStatus({
          is_initialized: false,
          is_active: false,
          total_chats: 0,
          active_chats: 0,
          tool_count: 0,
        });
      }
    }
  }, [projectId, enabled]);

  /**
   * Fetch metrics
   */
  const fetchMetrics = useCallback(async () => {
    if (!enabled || !projectId) return;

    try {
      const metricsData = await agentStatusService.getProjectAgentMetrics(projectId);
      setMetrics(metricsData);
    } catch (err: any) {
      // Metrics might not be available, ignore errors
      logger.debug('[useProjectAgentLifecycle] Failed to fetch metrics:', err);
    }
  }, [projectId, enabled]);

  /**
   * Refresh both status and metrics
   */
  const refresh = useCallback(async () => {
    setIsLoading(true);
    await Promise.all([fetchStatus(), fetchMetrics()]);
    setIsLoading(false);
  }, [fetchStatus, fetchMetrics]);

  /**
   * Pause the agent
   */
  const pause = useCallback(async () => {
    if (!projectId) return;
    try {
      setIsLoading(true);
      await agentStatusService.pauseProjectAgent(projectId);
      await refresh();
    } catch (err: any) {
      logger.error('[useProjectAgentLifecycle] Failed to pause agent:', err);
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, refresh]);

  /**
   * Resume the agent
   */
  const resume = useCallback(async () => {
    if (!projectId) return;
    try {
      setIsLoading(true);
      await agentStatusService.resumeProjectAgent(projectId);
      await refresh();
    } catch (err: any) {
      logger.error('[useProjectAgentLifecycle] Failed to resume agent:', err);
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, refresh]);

  /**
   * Stop the agent
   */
  const stop = useCallback(async () => {
    if (!projectId) return;
    try {
      setIsLoading(true);
      await agentStatusService.stopProjectAgent(projectId);
      await refresh();
    } catch (err: any) {
      logger.error('[useProjectAgentLifecycle] Failed to stop agent:', err);
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, refresh]);

  /**
   * Reload/refresh the agent
   */
  const reload = useCallback(async () => {
    if (!projectId) return;
    try {
      setIsLoading(true);
      await agentStatusService.refreshProjectAgent(projectId);
      // Wait a bit for refresh to take effect
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await refresh();
    } catch (err: any) {
      logger.error('[useProjectAgentLifecycle] Failed to reload agent:', err);
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, refresh]);

  // Polling effect
  useEffect(() => {
    if (!enabled || !projectId) return;

    // Initial fetch
    refresh();

    // Set up polling
    const interval = setInterval(refresh, pollingInterval);

    return () => {
      clearInterval(interval);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [refresh, pollingInterval, enabled, projectId]);

  return {
    sessionStatus,
    metrics,
    isLoading,
    error,
    refresh,
    pause,
    resume,
    stop,
    reload,
  };
}

export default useProjectAgentLifecycle;
