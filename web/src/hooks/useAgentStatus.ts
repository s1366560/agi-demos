import { useState, useEffect, useCallback, useRef } from 'react';
import { agentStatusService, WorkflowStatus, AgentSessionStatus } from '../services/agentStatusService';
import { useAgentV3Store } from '../stores/agentV3';
import { logger } from '../utils/logger';

export interface DetailedStatus {
  label: string;
  color: string;
  icon: string;
  description: string;
}

interface UseAgentStatusOptions {
  projectId: string;
  conversationId?: string;
  pollingInterval?: number;
  enabled?: boolean;
}

export function useAgentStatus({
  projectId,
  conversationId,
  pollingInterval = 5000,
  enabled = true,
}: UseAgentStatusOptions) {
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus | null>(null);
  const [sessionStatus, setSessionStatus] = useState<AgentSessionStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const { isStreaming, agentState, activeToolCalls } = useAgentV3Store();
  const abortControllerRef = useRef<AbortController | null>(null);

  // Fetch workflow status
  const fetchWorkflowStatus = useCallback(async () => {
    if (!conversationId || !enabled) return;
    
    try {
      const status = await agentStatusService.getWorkflowStatus(conversationId);
      setWorkflowStatus(status);
      setError(null);
    } catch (err: any) {
      if (err.status === 404) {
        // Workflow not found is normal when not executing
        setWorkflowStatus(null);
      } else {
        logger.warn('[useAgentStatus] Failed to fetch workflow status:', err);
      }
    }
  }, [conversationId, enabled]);

  // Fetch session status
  const fetchSessionStatus = useCallback(async () => {
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
        logger.warn('[useAgentStatus] Failed to fetch session status:', err);
        setError(err.message);
      }
    }
  }, [projectId, enabled]);

  // Combined status fetch
  const fetchStatus = useCallback(async () => {
    if (!enabled) return;
    
    setIsLoading(true);
    await Promise.all([
      fetchWorkflowStatus(),
      fetchSessionStatus(),
    ]);
    setIsLoading(false);
  }, [fetchWorkflowStatus, fetchSessionStatus, enabled]);

  // Polling effect
  useEffect(() => {
    if (!enabled) return;
    
    // Initial fetch
    fetchStatus();
    
    // Set up polling
    const interval = setInterval(fetchStatus, pollingInterval);
    
    return () => {
      clearInterval(interval);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [fetchStatus, pollingInterval, enabled]);

  // Derived status for UI
  const getDetailedStatus = useCallback((): DetailedStatus => {
    // Priority 1: Workflow execution status
    if (workflowStatus?.status === 'RUNNING') {
      return {
        label: 'Executing',
        color: 'amber',
        icon: 'workflow',
        description: `Workflow active`,
      };
    }
    
    // Priority 2: Agent state from store
    if (isStreaming || agentState !== 'idle') {
      const stateMap: Record<string, { label: string; color: string; icon: string; description: string }> = {
        thinking: { 
          label: 'Thinking', 
          color: 'blue', 
          icon: 'brain',
          description: 'Analyzing your request'
        },
        acting: { 
          label: 'Using Tools', 
          color: 'purple', 
          icon: 'tool',
          description: `${activeToolCalls.size} tool(s) running`
        },
        observing: { 
          label: 'Processing', 
          color: 'amber', 
          icon: 'eye',
          description: 'Processing results'
        },
        awaiting_input: { 
          label: 'Waiting', 
          color: 'orange', 
          icon: 'pause',
          description: 'Waiting for input'
        },
      };
      
      return stateMap[agentState] || { 
        label: 'Processing', 
        color: 'amber', 
        icon: 'loader',
        description: 'Working on your request'
      };
    }
    
    // Priority 3: Session initialization status
    if (sessionStatus) {
      if (!sessionStatus.is_initialized) {
        return {
          label: 'Initializing',
          color: 'blue',
          icon: 'sparkles',
          description: 'Preparing agent session...',
        };
      }
      
      return {
        label: 'Ready',
        color: 'emerald',
        icon: 'check-circle',
        description: `${sessionStatus.tool_count} tools available`,
      };
    }
    
    // Default
    return {
      label: 'Connecting',
      color: 'slate',
      icon: 'wifi',
      description: 'Connecting to agent...',
    };
  }, [workflowStatus, isStreaming, agentState, sessionStatus, activeToolCalls]);

  const detailedStatus = getDetailedStatus();

  return {
    workflowStatus,
    sessionStatus,
    isLoading,
    error,
    detailedStatus,
    refresh: fetchStatus,
  };
}
