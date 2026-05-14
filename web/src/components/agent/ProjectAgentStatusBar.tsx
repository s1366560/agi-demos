/**
 * ProjectAgentStatusBar - Project ReAct Agent Lifecycle Status Bar
 *
 * Displays the complete lifecycle state of the ProjectReActAgent:
 * - Pool tier (HOT/WARM/COLD) when pool management is enabled
 * - Sandbox status (with click-to-start and metrics popover)
 * - Lifecycle state (uninitialized, initializing, ready, executing, paused, error, shutting_down)
 * - Resource counts (tools, skills, subagents)
 * - Execution metrics (total/failed chats, active chats)
 * - Health status (uptime, last error)
 * - Lifecycle control buttons (start, stop, restart)
 *
 * This component now uses the unified agent status hook for consolidated state management,
 * with optional pool-based lifecycle management integration.
 *
 * @module components/agent/ProjectAgentStatusBar
 */

import type { FC } from 'react';
import { useState, useCallback, useEffect, useMemo, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Zap,
  MessageSquare,
  Wifi,
  Loader2,
  CheckCircle2,
  AlertCircle,
  PauseCircle,
  Power,
  Cpu,
  Wrench,
  BrainCircuit,
  Activity,
  AlertTriangle,
  Play,
  Square,
  RefreshCw,
  Plug,
  Flame,
  Cloud,
  Snowflake,
  Layers,
  Heart,
  Brain,
  Eye,
  MessageCircle,
  RotateCcw,
  ListTodo,
  Route,
  Filter,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useAgentState, usePendingToolsStack } from '@/stores/agent/executionStore';
import { useIsStreaming } from '@/stores/agent/streamingStore';
import { useAgentV3Store } from '@/stores/agentV3';

import { LazyTooltip, LazyPopconfirm, message } from '@/components/ui/lazyAntd';

import {
  useUnifiedAgentStatus,
  type ProjectAgentLifecycleState,
} from '../../hooks/useUnifiedAgentStatus';
import { agentService } from '../../services/agentService';
import {
  poolService,
  type PoolInstance,
  type ProjectTier,
  type InstanceStatus,
} from '../../services/poolService';

import { ContextStatusIndicator } from './context/ContextStatusIndicator';
import { SandboxStatusIndicator } from './sandbox/SandboxStatusIndicator';

import type { LucideIcon } from 'lucide-react';

interface ProjectAgentStatusBarProps {
  /** Project ID */
  projectId: string;
  /** Tenant ID */
  tenantId: string;
  /** Number of messages */
  messageCount?: number | undefined;
  /** Enable pool management integration */
  enablePoolManagement?: boolean | undefined;
  /** Show the embedded sandbox lifecycle indicator */
  showSandboxStatus?: boolean | undefined;
  /** Show the embedded task progress indicator */
  showTaskProgress?: boolean | undefined;
}

/**
 * Map pool instance status to lifecycle state
 */
function mapPoolStatusToLifecycle(status: InstanceStatus | undefined): ProjectAgentLifecycleState {
  if (!status) return 'uninitialized';

  switch (status) {
    case 'created':
    case 'initializing':
      return 'initializing';
    case 'initialization_failed':
    case 'unhealthy':
    case 'degraded':
      return 'error';
    case 'ready':
      return 'ready';
    case 'executing':
      return 'executing';
    case 'paused':
      return 'paused';
    case 'terminating':
      return 'shutting_down';
    case 'terminated':
      return 'uninitialized';
    default:
      return 'uninitialized';
  }
}

/**
 * Lifecycle state configuration. `label` and `description` store i18n keys —
 * translate them at the usage site via `t()`.
 */
const lifecycleConfig: Record<
  ProjectAgentLifecycleState,
  {
    label: string;
    icon: LucideIcon;
    color: string;
    bgColor: string;
    description: string;
    animate?: boolean | undefined;
  }
> = {
  uninitialized: {
    label: 'agent.lifecycle.states.uninitialized',
    icon: Power,
    color: 'text-slate-500',
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    description: 'agent.lifecycle.descriptions.uninitialized',
  },
  initializing: {
    label: 'agent.lifecycle.states.initializing',
    icon: Loader2,
    color: 'text-blue-500',
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
    description: 'agent.lifecycle.descriptions.initializing',
    animate: true,
  },
  ready: {
    label: 'agent.lifecycle.states.ready',
    icon: CheckCircle2,
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-100 dark:bg-emerald-900/30',
    description: 'agent.lifecycle.descriptions.ready',
  },
  executing: {
    label: 'agent.lifecycle.states.executing',
    icon: Cpu,
    color: 'text-amber-500',
    bgColor: 'bg-amber-100 dark:bg-amber-900/30',
    description: 'agent.lifecycle.descriptions.executing',
    animate: true,
  },
  paused: {
    label: 'agent.lifecycle.states.paused',
    icon: PauseCircle,
    color: 'text-orange-500',
    bgColor: 'bg-orange-100 dark:bg-orange-900/30',
    description: 'agent.lifecycle.descriptions.paused',
  },
  error: {
    label: 'agent.lifecycle.states.error',
    icon: AlertCircle,
    color: 'text-red-500',
    bgColor: 'bg-red-100 dark:bg-red-900/30',
    description: 'agent.lifecycle.descriptions.error',
  },
  shutting_down: {
    label: 'agent.lifecycle.states.shutting_down',
    icon: Power,
    color: 'text-slate-500',
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    description: 'agent.lifecycle.descriptions.shutting_down',
    animate: true,
  },
};

/**
 * Tier configuration for pool-based management
 */
const tierConfig: Record<
  ProjectTier,
  {
    label: string;
    icon: LucideIcon;
    color: string;
    bgColor: string;
    description: string;
  }
> = {
  hot: {
    label: 'HOT',
    icon: Flame,
    color: 'text-orange-500',
    bgColor: 'bg-orange-100 dark:bg-orange-900/30',
    description: 'agent.lifecycle.pool.tiers.hot',
  },
  warm: {
    label: 'WARM',
    icon: Cloud,
    color: 'text-blue-500',
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
    description: 'agent.lifecycle.pool.tiers.warm',
  },
  cold: {
    label: 'COLD',
    icon: Snowflake,
    color: 'text-slate-500',
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    description: 'agent.lifecycle.pool.tiers.cold',
  },
};

/**
 * Agent execution state configuration (from AgentStatePill)
 */
type AgentExecState =
  | 'idle'
  | 'thinking'
  | 'preparing'
  | 'acting'
  | 'observing'
  | 'awaiting_input'
  | 'retrying';

interface ExecStateConfig {
  icon: LucideIcon;
  iconAnimate: string;
  color: string;
  bgColor: string;
  borderColor: string;
}

const execStateConfig: Record<AgentExecState, ExecStateConfig> = {
  thinking: {
    icon: Brain,
    iconAnimate: 'animate-pulse motion-reduce:animate-none',
    color: 'text-slate-600 dark:text-slate-400',
    bgColor: 'bg-slate-100 dark:bg-slate-800/50',
    borderColor: 'border-slate-200 dark:border-slate-700',
  },
  preparing: {
    icon: Loader2,
    iconAnimate: 'animate-spin motion-reduce:animate-none',
    color: 'text-blue-600 dark:text-blue-400',
    bgColor: 'bg-blue-50 dark:bg-blue-900/20',
    borderColor: 'border-blue-200 dark:border-blue-800',
  },
  acting: {
    icon: Zap,
    iconAnimate: '',
    color: 'text-blue-600 dark:text-blue-400',
    bgColor: 'bg-blue-50 dark:bg-blue-900/20',
    borderColor: 'border-blue-200 dark:border-blue-800',
  },
  observing: {
    icon: Eye,
    iconAnimate: '',
    color: 'text-emerald-600 dark:text-emerald-400',
    bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
    borderColor: 'border-emerald-200 dark:border-emerald-800',
  },
  awaiting_input: {
    icon: MessageCircle,
    iconAnimate: 'animate-pulse motion-reduce:animate-none',
    color: 'text-slate-600 dark:text-slate-400',
    bgColor: 'bg-slate-100 dark:bg-slate-800/50',
    borderColor: 'border-slate-200 dark:border-slate-700',
  },
  retrying: {
    icon: RotateCcw,
    iconAnimate: 'animate-spin motion-reduce:animate-none',
    color: 'text-red-600 dark:text-red-400',
    bgColor: 'bg-red-50 dark:bg-red-900/20',
    borderColor: 'border-red-200 dark:border-red-800',
  },
  idle: {
    icon: CheckCircle2,
    iconAnimate: '',
    color: 'text-slate-400 dark:text-slate-500',
    bgColor: 'bg-slate-100 dark:bg-slate-800/50',
    borderColor: 'border-slate-200 dark:border-slate-700',
  },
};

/**
 * Status bar phase dot
 */
const StatusPhaseDot: FC<{ active: boolean; completed: boolean }> = ({ active, completed }) => (
  <span
    className={`
      w-1.5 h-1.5 rounded-full transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300
      ${active ? 'bg-current scale-125' : completed ? 'bg-current opacity-40' : 'bg-slate-300 dark:bg-slate-600'}
    `}
  />
);

const EMPTY_TASKS: never[] = [];
const POOL_STATUS_REFRESH_MS = 15000;
const POOL_INSTANCE_REFRESH_MS = 60000;
const POOL_STATUS_CACHE_TTL_MS = 15000;

interface PoolStatusSnapshot {
  enabled: boolean;
  instance: PoolInstance | null;
  fetchedAt: number;
}

const poolStatusSnapshotCache = new Map<string, PoolStatusSnapshot>();

/**
 * ProjectAgentStatusBar - Refactored to use unified status hook
 *
 * This component now uses the useUnifiedAgentStatus hook which consolidates:
 * - Lifecycle state (from useAgentLifecycleState via WebSocket)
 * - Execution state (from agentV3 store)
 * - Plan mode state (deprecated)
 * - Streaming state (from streamingStore)
 * - Sandbox connection (from sandboxStore)
 * - Pool instance state (from poolService - when enabled)
 *
 * When pool management is enabled, lifecycle state is derived from pool instance status.
 * When disabled, falls back to WebSocket-based lifecycle state.
 */
export const ProjectAgentStatusBar: FC<ProjectAgentStatusBarProps> = ({
  projectId,
  tenantId,
  messageCount = 0,
  enablePoolManagement = false,
  showSandboxStatus = true,
  showTaskProgress = true,
}) => {
  const { t } = useTranslation();

  // Agent execution state from sub-stores (streaming/execution domain)
  const agentState = useAgentState() as AgentExecState;
  const storeIsStreaming = useIsStreaming();
  const pendingToolsStack = usePendingToolsStack();

  // Conversation-scoped state (stays on agentV3 — reads from conversationStates Map)
  const { tasks, executionPathDecision, selectionTrace, policyFiltered } = useAgentV3Store(
    useShallow((s) => {
      const convId = s.activeConversationId;
      const convState = convId ? s.conversationStates.get(convId) : null;
      const convTasks = convState?.tasks;
      return {
        tasks: convTasks ?? EMPTY_TASKS,
        executionPathDecision: convState?.executionPathDecision ?? null,
        selectionTrace: convState?.selectionTrace ?? null,
        policyFiltered: convState?.policyFiltered ?? null,
      };
    })
  );

  // Use the unified status hook for consolidated state
  // Always enable WebSocket for sandbox state sync, even when pool management is enabled
  const {
    status,
    isLoading,
    error: wsError,
    isStreaming,
  } = useUnifiedAgentStatus({
    projectId,
    tenantId,
    // Always enabled for WebSocket connection (needed for sandbox lifecycle events)
    enabled: !!projectId,
  });

  // Determine if we should show agent execution state (pill) vs lifecycle state
  const showExecState = (isStreaming || storeIsStreaming) && agentState !== 'idle';
  const execConfig = useMemo(() => execStateConfig[agentState], [agentState]);
  const currentTool =
    pendingToolsStack.length > 0 ? pendingToolsStack[pendingToolsStack.length - 1] : null;
  const isActingPhase = agentState === 'acting' || agentState === 'preparing';
  const isPostThinking = agentState === 'acting' || agentState === 'observing';

  // Pool instance state (primary when pool management is enabled)
  const [poolInstance, setPoolInstance] = useState<PoolInstance | null>(null);
  const [poolEnabled, setPoolEnabled] = useState(false);
  const [poolLoading, setPoolLoading] = useState(false);
  const [poolError, setPoolError] = useState<string | null>(null);
  const [poolRefreshNonce, setPoolRefreshNonce] = useState(0);
  const lastPoolInstanceFetchAtRef = useRef(0);
  const poolEffectTokenRef = useRef(0);

  // Fetch pool instance status when pool management is enabled
  useEffect(() => {
    if (!enablePoolManagement || !tenantId || !projectId) {
      return;
    }

    const effectToken = poolEffectTokenRef.current + 1;
    poolEffectTokenRef.current = effectToken;
    let inFlight = false;
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    const cacheKey = `${tenantId}:${projectId}:chat`;
    const isEffectActive = () => poolEffectTokenRef.current === effectToken;

    const scheduleNextRefresh = (delayMs = POOL_STATUS_REFRESH_MS) => {
      if (!isEffectActive()) return;
      if (refreshTimer) {
        clearTimeout(refreshTimer);
      }
      refreshTimer = setTimeout(() => {
        void fetchPoolInstance('timer');
      }, delayMs);
    };

    const updateSnapshot = (enabled: boolean, instance: PoolInstance | null) => {
      poolStatusSnapshotCache.set(cacheKey, {
        enabled,
        instance,
        fetchedAt: Date.now(),
      });
    };

    const fetchPoolInstance = async (reason: 'initial' | 'timer' | 'manual') => {
      if (!isEffectActive() || inFlight) {
        return;
      }

      inFlight = true;
      setPoolLoading(true);
      setPoolError(null);
      try {
        // First check if pool is enabled
        const statusResponse = await poolService.getStatus();
        if (!isEffectActive()) return;

        setPoolEnabled(statusResponse.enabled);
        if (!statusResponse.enabled) {
          lastPoolInstanceFetchAtRef.current = 0;
          setPoolInstance(null);
          updateSnapshot(false, null);
          return;
        }

        let nextInstance = poolStatusSnapshotCache.get(cacheKey)?.instance ?? null;
        const now = Date.now();
        const shouldRefreshInstance =
          reason !== 'timer' ||
          now - lastPoolInstanceFetchAtRef.current >= POOL_INSTANCE_REFRESH_MS;

        if (shouldRefreshInstance) {
          // Fetch instance for this project
          const instanceKey = `${tenantId}:${projectId}:chat`;
          const instances = await poolService.listInstances({ page: 1, page_size: 100 });
          if (!isEffectActive()) return;

          nextInstance =
            instances.instances.find((i: PoolInstance) => i.instance_key === instanceKey) || null;
          lastPoolInstanceFetchAtRef.current = now;
        }

        setPoolInstance(nextInstance);
        updateSnapshot(true, nextInstance);
      } catch (err) {
        // Pool service might not be available
        if (isEffectActive()) {
          setPoolEnabled(false);
          setPoolInstance(null);
          setPoolError(err instanceof Error ? err.message : 'Pool service unavailable');
          updateSnapshot(false, null);
        }
      } finally {
        inFlight = false;
        if (isEffectActive()) {
          setPoolLoading(false);
          scheduleNextRefresh();
        }
      }
    };

    const cachedSnapshot = poolStatusSnapshotCache.get(cacheKey);
    const isCacheFresh =
      !!cachedSnapshot && Date.now() - cachedSnapshot.fetchedAt < POOL_STATUS_CACHE_TTL_MS;

    if (cachedSnapshot && isCacheFresh) {
      setPoolEnabled(cachedSnapshot.enabled);
      setPoolInstance(cachedSnapshot.instance);
      lastPoolInstanceFetchAtRef.current = cachedSnapshot.fetchedAt;
      scheduleNextRefresh();
    } else {
      void fetchPoolInstance('initial');
    }

    return () => {
      if (poolEffectTokenRef.current === effectToken) {
        poolEffectTokenRef.current += 1;
      }
      if (refreshTimer) {
        clearTimeout(refreshTimer);
      }
    };
  }, [enablePoolManagement, tenantId, projectId, poolRefreshNonce]);

  // Lifecycle control state
  const [isActionPending, setIsActionPending] = useState(false);

  // Determine lifecycle state based on pool status or WebSocket
  const lifecycleState: ProjectAgentLifecycleState =
    enablePoolManagement && poolEnabled
      ? mapPoolStatusToLifecycle(poolInstance?.status)
      : status.lifecycle;

  const config = lifecycleConfig[lifecycleState];
  const error = enablePoolManagement ? poolError : wsError;

  const StatusIcon = config.icon;
  const isError = lifecycleState === 'error';

  // Check if agent can be stopped (is running)
  const canStop =
    lifecycleState === 'ready' || lifecycleState === 'executing' || lifecycleState === 'paused';
  // Check if agent can be restarted (exists)
  const canRestart =
    lifecycleState !== 'uninitialized' &&
    lifecycleState !== 'shutting_down' &&
    lifecycleState !== 'initializing';
  // Check if agent can be paused (pool mode only)
  const canPause =
    enablePoolManagement && poolEnabled && poolInstance && lifecycleState === 'ready';
  // Check if agent can be resumed (pool mode only)
  const canResume =
    enablePoolManagement && poolEnabled && poolInstance && lifecycleState === 'paused';

  const domainLane =
    (executionPathDecision?.metadata?.domain_lane as string | undefined) ??
    selectionTrace?.domain_lane ??
    policyFiltered?.domain_lane ??
    null;
  const hasInsights = Boolean(executionPathDecision || selectionTrace || policyFiltered);

  // Get instance key for pool operations
  const instanceKey = `${tenantId}:${projectId}:chat`;

  // Lifecycle control handlers - use pool API when enabled, fallback to WebSocket
  const handleStopAgent = useCallback(async () => {
    setIsActionPending(true);
    try {
      if (enablePoolManagement && poolEnabled && poolInstance) {
        // Use pool API to terminate instance
        await poolService.terminateInstance(instanceKey, false);
        poolStatusSnapshotCache.delete(instanceKey);
        setPoolRefreshNonce((prev) => prev + 1);
        message.info(t('agent.lifecycle.messages.terminating'));
      } else {
        // Fallback to WebSocket
        agentService.stopAgent(projectId);
        message.info(t('agent.lifecycle.messages.stopping'));
      }
    } catch (_err) {
      message.error(t('agent.lifecycle.messages.stopFailed'));
    } finally {
      setTimeout(() => {
        setIsActionPending(false);
      }, 3000);
    }
  }, [projectId, enablePoolManagement, poolEnabled, poolInstance, instanceKey, t]);

  const handleRestartAgent = useCallback(async () => {
    setIsActionPending(true);
    try {
      if (enablePoolManagement && poolEnabled && poolInstance) {
        // Terminate and let auto-create handle restart
        await poolService.terminateInstance(instanceKey, true);
        poolStatusSnapshotCache.delete(instanceKey);
        setPoolRefreshNonce((prev) => prev + 1);
        message.info(t('agent.lifecycle.messages.restarting'));
      } else {
        agentService.restartAgent(projectId);
        message.info(t('agent.lifecycle.messages.restartingAgent'));
      }
    } catch (_err) {
      message.error(t('agent.lifecycle.messages.restartFailed'));
    } finally {
      setTimeout(() => {
        setIsActionPending(false);
      }, 5000);
    }
  }, [projectId, enablePoolManagement, poolEnabled, poolInstance, instanceKey, t]);

  const handlePauseAgent = useCallback(async () => {
    if (!poolInstance) return;
    setIsActionPending(true);
    try {
      await poolService.pauseInstance(instanceKey);
      poolStatusSnapshotCache.delete(instanceKey);
      setPoolRefreshNonce((prev) => prev + 1);
      message.info(t('agent.lifecycle.messages.pausing'));
    } catch (_err) {
      message.error(t('agent.lifecycle.messages.pauseFailed'));
    } finally {
      setTimeout(() => {
        setIsActionPending(false);
      }, 2000);
    }
  }, [poolInstance, instanceKey, t]);

  const handleResumeAgent = useCallback(async () => {
    if (!poolInstance) return;
    setIsActionPending(true);
    try {
      await poolService.resumeInstance(instanceKey);
      poolStatusSnapshotCache.delete(instanceKey);
      setPoolRefreshNonce((prev) => prev + 1);
      message.info(t('agent.lifecycle.messages.resuming'));
    } catch (_err) {
      message.error(t('agent.lifecycle.messages.resumeFailed'));
    } finally {
      setTimeout(() => {
        setIsActionPending(false);
      }, 2000);
    }
  }, [poolInstance, instanceKey, t]);

  // Get pool tier config
  const poolTierConfig = poolInstance?.tier ? tierConfig[poolInstance.tier] : null;
  const TierIcon = poolTierConfig?.icon ?? Layers;

  return (
    <div className="px-4 py-1.5 flex items-center justify-between gap-2 min-w-0">
      {/* Left: Pool Tier, Sandbox Status, Lifecycle Status & Resources */}
      <div className="flex items-center gap-2 min-w-0 overflow-hidden">
        {/* Pool Tier Indicator (shown when pool management is enabled) */}
        {enablePoolManagement && poolEnabled && (
          <>
            <LazyTooltip
              title={
                <div className="space-y-2 max-w-xs">
                  <div className="font-medium flex items-center gap-2">
                    <Layers size={14} />
                    <span>{t('agent.lifecycle.pool.title')}</span>
                  </div>
                  {poolInstance ? (
                    <>
                      <div className="text-xs">
                        <div className="flex justify-between">
                          <span className="opacity-70">{t('agent.lifecycle.pool.tier')}:</span>
                          <span className={poolTierConfig?.color}>{poolTierConfig?.label}</span>
                          {/* poolTierConfig?.label stays untranslated — HOT/WARM/COLD are brand identifiers, not localized labels. */}
                        </div>
                        <div className="flex justify-between">
                          <span className="opacity-70">{t('agent.lifecycle.pool.status')}:</span>
                          <span>{poolInstance.status}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="opacity-70">{t('agent.lifecycle.pool.health')}:</span>
                          <span
                            className={
                              poolInstance.health_status === 'healthy'
                                ? 'text-emerald-400'
                                : 'text-amber-400'
                            }
                          >
                            {poolInstance.health_status}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="opacity-70">{t('agent.lifecycle.pool.activeRequests')}:</span>
                          <span>{poolInstance.active_requests}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="opacity-70">{t('agent.lifecycle.pool.totalRequests')}:</span>
                          <span>{poolInstance.total_requests}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="opacity-70">{t('agent.lifecycle.pool.memory')}:</span>
                          <span>{poolInstance.memory_used_mb} MB</span>
                        </div>
                      </div>
                      <div className="text-xs opacity-70 pt-1 border-t border-gray-600 mt-1">
                        {poolTierConfig?.description ? t(poolTierConfig.description) : ''}
                      </div>
                    </>
                  ) : (
                    <div className="text-xs opacity-70">{t('agent.lifecycle.pool.noInstance')}</div>
                  )}
                </div>
              }
            >
              <div
                className={`
                  flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
                  ${poolTierConfig?.bgColor ?? 'bg-slate-100 dark:bg-slate-800'}
                  ${poolTierConfig?.color ?? 'text-slate-500'}
                  transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 cursor-help
                `}
              >
                {poolLoading ? (
                  <Loader2 size={12} className="animate-spin motion-reduce:animate-none" />
                ) : (
                  <TierIcon size={12} />
                )}
                <span className="hidden sm:inline">
                  {poolInstance
                    ? (poolTierConfig?.label ?? 'POOL')
                    : t('agent.lifecycle.pool.pending')}
                </span>
                {poolInstance?.health_status === 'healthy' && (
                  <Heart size={10} className="text-emerald-500 fill-emerald-500" />
                )}
              </div>
            </LazyTooltip>
            {/* Separator */}
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
          </>
        )}

        {showSandboxStatus && (
          <>
            {/* Sandbox Status Indicator */}
            <SandboxStatusIndicator projectId={projectId} tenantId={tenantId} />

            {/* Separator */}
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
          </>
        )}

        {/* Agent Status - Shows execution state when streaming, lifecycle state otherwise */}
        {showExecState ? (
          <div
            className={`
              flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
              ${execConfig.bgColor} ${execConfig.color} border ${execConfig.borderColor}
              transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300
            `}
          >
            <execConfig.icon size={12} className={execConfig.iconAnimate} />
            <span className="hidden sm:inline">{t(`agent.state.${agentState}`, agentState)}</span>
            {currentTool && agentState === 'acting' && (
              <span className="text-xs opacity-60 truncate max-w-[80px] hidden sm:inline">
                {currentTool}
              </span>
            )}
            {/* Phase progress dots */}
            <div className="flex items-center gap-0.5 ml-0.5">
              <StatusPhaseDot active={agentState === 'thinking'} completed={isPostThinking} />
              <StatusPhaseDot active={isActingPhase} completed={agentState === 'observing'} />
              <StatusPhaseDot active={agentState === 'observing'} completed={false} />
            </div>
          </div>
        ) : (
          <LazyTooltip
            title={
              <div className="space-y-2 max-w-xs">
                <div className="font-medium">{t(config.label)}</div>
                <div className="text-xs opacity-80">{t(config.description)}</div>
                {error && (
                  <div className="text-xs text-red-400 pt-1 border-t border-gray-600 mt-1">
                    {t('agent.lifecycle.error.prefix')}: {error}
                  </div>
                )}
              </div>
            }
          >
            <div
              className={`
                flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
                ${config.bgColor} ${config.color}
                transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 cursor-help
              `}
            >
              <StatusIcon
                size={12}
                className={config.animate ? 'animate-spin motion-reduce:animate-none' : ''}
              />
              <span className="hidden sm:inline">{t(config.label)}</span>
              {status.resources.activeCalls > 0 ? (
                <span className="ml-0.5">({status.resources.activeCalls})</span>
              ) : null}
            </div>
          </LazyTooltip>
        )}

        {/* Resources: Tools with detailed breakdown */}
        {status.toolStats.total > 0 && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
            <LazyTooltip
              title={
                <div className="space-y-1">
                  <div className="font-medium">{t('agent.lifecycle.stats.toolStats')}</div>
                  <div>{t('agent.lifecycle.stats.totalTools')}: {status.toolStats.total}</div>
                  <div>{t('agent.lifecycle.stats.builtinTools')}: {status.toolStats.builtin}</div>
                  <div>{t('agent.lifecycle.stats.mcpTools')}: {status.toolStats.mcp}</div>
                </div>
              }
            >
              <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500">
                <Wrench size={11} />
                <span>{status.toolStats.builtin}</span>
                {status.toolStats.mcp > 0 && (
                  <>
                    <span className="text-slate-400">+</span>
                    <Plug size={10} className="text-blue-500" />
                    <span className="text-blue-500">{status.toolStats.mcp}</span>
                  </>
                )}
              </div>
            </LazyTooltip>
          </>
        )}

        {/* Resources: Skills with detailed breakdown */}
        {status.skillStats.total > 0 && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
            <LazyTooltip
              title={
                <div className="space-y-1">
                  <div className="font-medium">{t('agent.lifecycle.stats.skillStats')}</div>
                  <div>{t('agent.lifecycle.stats.totalSkills')}: {status.skillStats.total}</div>
                  <div>{t('agent.lifecycle.stats.loaded')}: {status.skillStats.loaded}</div>
                </div>
              }
            >
              <div className="hidden sm:flex items-center gap-1 text-xs text-slate-500">
                <BrainCircuit size={11} />
                <span>
                  {status.skillStats.loaded}/{status.skillStats.total}
                </span>
              </div>
            </LazyTooltip>
          </>
        )}

        {/* Message Count */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
        <LazyTooltip title={t('agent.lifecycle.stats.messageCount')}>
          <div className="hidden sm:flex items-center gap-1 text-xs text-slate-500">
            <MessageSquare size={11} />
            <span>{messageCount}</span>
          </div>
        </LazyTooltip>

        {/* Task Progress */}
        {showTaskProgress && tasks.length > 0 && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
            <LazyTooltip
              title={
                <div className="space-y-1">
                  <div className="font-medium">{t('agent.lifecycle.stats.taskProgress')}</div>
                  <div>
                    {t('agent.lifecycle.stats.completed')}: {tasks.filter((t) => t.status === 'completed').length}/{tasks.length}
                  </div>
                  <div>{t('agent.lifecycle.stats.inProgress')}: {tasks.filter((t) => t.status === 'in_progress').length}</div>
                  <div>{t('agent.lifecycle.stats.pending')}: {tasks.filter((t) => t.status === 'pending').length}</div>
                </div>
              }
            >
              <div className="flex items-center gap-1 text-xs text-purple-600 dark:text-purple-400">
                <ListTodo size={11} />
                <span className="tabular-nums">
                  {tasks.filter((t) => t.status === 'completed').length}/{tasks.length}
                </span>
              </div>
            </LazyTooltip>
          </>
        )}

        {/* Context Window Status */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
        <div className="hidden sm:flex items-center">
          <ContextStatusIndicator />
        </div>

        {/* Plan Mode */}
        {status.planMode.isActive && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
            <LazyTooltip
              title={t('agent.lifecycle.planMode.tooltip', { mode: status.planMode.currentMode?.toUpperCase() || 'PLAN' })}
            >
              <div className="flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400">
                <Zap size={11} />
                <span className="hidden sm:inline">
                  {status.planMode.currentMode === 'plan' ? t('agent.lifecycle.planMode.label') : status.planMode.currentMode}
                </span>
              </div>
            </LazyTooltip>
          </>
        )}

        {/* Execution Insights */}
        {hasInsights && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
            <LazyTooltip
              title={
                <div className="space-y-2 max-w-xs">
                  <div className="font-medium border-b border-slate-200/20 pb-1">
                    Execution Insights
                  </div>
                  {executionPathDecision && (
                    <div className="flex items-start gap-2 text-xs">
                      <Route size={12} className="mt-0.5 text-blue-400 flex-shrink-0" />
                      <div>
                        <span className="font-medium">Path:</span>{' '}
                        {executionPathDecision.path.replace(/_/g, ' ')} (
                        {executionPathDecision.confidence.toFixed(2)})
                        {domainLane && <span className="ml-1 opacity-70">· lane {domainLane}</span>}
                      </div>
                    </div>
                  )}
                  {selectionTrace && (
                    <div className="flex items-start gap-2 text-xs">
                      <Filter size={12} className="mt-0.5 text-purple-400 flex-shrink-0" />
                      <div>
                        <span className="font-medium">Selection:</span> {selectionTrace.final_count}
                        /{selectionTrace.initial_count} tools kept across{' '}
                        {selectionTrace.stages.length} stages
                      </div>
                    </div>
                  )}
                  {policyFiltered && policyFiltered.removed_total > 0 && (
                    <div className="flex items-start gap-2 text-xs">
                      <Filter size={12} className="mt-0.5 text-amber-400 flex-shrink-0" />
                      <div>
                        <span className="font-medium">Policy:</span> filtered{' '}
                        {policyFiltered.removed_total} tools
                      </div>
                    </div>
                  )}
                </div>
              }
            >
              <div className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 cursor-help transition-colors">
                <Route size={11} className="text-blue-500" />
                <span className="hidden sm:inline">
                  {executionPathDecision?.path.replace(/_/g, ' ') || 'Insights'}
                </span>
              </div>
            </LazyTooltip>
          </>
        )}

        {/* Error Indicator */}
        {isError && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />
            <LazyTooltip title={error || t('agent.lifecycle.error.description')}>
              <div className="flex items-center gap-1 text-xs text-red-500">
                <AlertTriangle size={11} />
                <span className="hidden sm:inline">{t('agent.lifecycle.error.label')}</span>
              </div>
            </LazyTooltip>
          </>
        )}
      </div>

      {/* Right: Lifecycle Controls & Connection */}
      <div className="flex items-center gap-2 text-xs flex-shrink-0">
        {/* Lifecycle Control Buttons */}
        <div className="flex items-center gap-1.5">
          {/* Pause Button - pool mode only, shown when agent is ready */}
          {canPause && (
            <LazyTooltip title={t('agent.lifecycle.controls.pause')}>
              <button
                type="button"
                onClick={() => {
                  void handlePauseAgent();
                }}
                disabled={isActionPending}
                className={`
                  p-1 rounded transition-colors
                  ${
                    isActionPending
                      ? 'text-slate-400 cursor-not-allowed'
                      : 'text-orange-500 hover:bg-orange-100 dark:hover:bg-orange-900/30'
                  }
                `}
              >
                {isActionPending ? (
                  <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                ) : (
                  <PauseCircle size={14} />
                )}
              </button>
            </LazyTooltip>
          )}

          {/* Resume Button - pool mode only, shown when agent is paused */}
          {canResume && (
            <LazyTooltip title={t('agent.lifecycle.controls.resume')}>
              <button
                type="button"
                onClick={() => {
                  void handleResumeAgent();
                }}
                disabled={isActionPending}
                className={`
                  p-1 rounded transition-colors
                  ${
                    isActionPending
                      ? 'text-slate-400 cursor-not-allowed'
                      : 'text-emerald-500 hover:bg-emerald-100 dark:hover:bg-emerald-900/30'
                  }
                `}
              >
                {isActionPending ? (
                  <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                ) : (
                  <Play size={14} />
                )}
              </button>
            </LazyTooltip>
          )}

          {/* Stop Button - shown when agent is running */}
          {canStop && (
            <LazyPopconfirm
              title={t('agent.lifecycle.controls.stopAgent')}
              description={
                enablePoolManagement && poolEnabled
                  ? t('agent.lifecycle.controls.confirmTerminate')
                  : t('agent.lifecycle.controls.confirmStop')
              }
              onConfirm={handleStopAgent}
              okText={t('agent.lifecycle.controls.stop')}
              cancelText={t('agent.lifecycle.controls.cancel')}
              okButtonProps={{ danger: true }}
            >
              <LazyTooltip title={enablePoolManagement && poolEnabled ? t('agent.lifecycle.controls.terminateInstance') : t('agent.lifecycle.controls.stopAgent')}>
                <button
                  type="button"
                  disabled={isActionPending}
                  className={`
                    p-1 rounded transition-colors
                    ${
                      isActionPending
                        ? 'text-slate-400 cursor-not-allowed'
                        : 'text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30'
                    }
                  `}
                >
                  {isActionPending ? (
                    <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                  ) : (
                    <Square size={14} />
                  )}
                </button>
              </LazyTooltip>
            </LazyPopconfirm>
          )}

          {/* Restart Button - shown when agent exists */}
          {canRestart && (
            <LazyPopconfirm
              title={t('agent.lifecycle.controls.restart')}
              description={t('agent.lifecycle.controls.confirmRestart')}
              onConfirm={handleRestartAgent}
              okText={t('agent.lifecycle.controls.restart')}
              cancelText={t('agent.lifecycle.controls.cancel')}
            >
              <LazyTooltip title={t('agent.lifecycle.controls.restartAgent')}>
                <button
                  type="button"
                  disabled={isActionPending}
                  className={`
                    p-1 rounded transition-colors
                    ${
                      isActionPending
                        ? 'text-slate-400 cursor-not-allowed'
                        : 'text-blue-500 hover:bg-blue-100 dark:hover:bg-blue-900/30'
                    }
                  `}
                >
                  {isActionPending ? (
                    <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                  ) : (
                    <RefreshCw size={14} />
                  )}
                </button>
              </LazyTooltip>
            </LazyPopconfirm>
          )}
        </div>

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 hidden sm:block" />

        {/* Connection & Activity Status - Combined */}
        <LazyTooltip
          title={
            <div className="space-y-1">
              <div>
                {isLoading
                  ? 'Loading...'
                  : status.connection.websocket
                    ? 'WebSocket Connected'
                    : 'Ready'}
              </div>
              {status.resources.activeCalls > 0 && (
                <div>Active tool calls: {status.resources.activeCalls}</div>
              )}
            </div>
          }
        >
          <div className="flex items-center gap-1.5 text-slate-400">
            {isLoading ? (
              <Loader2 size={12} className="animate-spin motion-reduce:animate-none" />
            ) : status.resources.activeCalls > 0 ? (
              <>
                <Activity
                  size={12}
                  className="text-blue-500 animate-pulse motion-reduce:animate-none"
                />
                <span className="hidden sm:inline text-blue-500">
                  {status.resources.activeCalls} active
                </span>
              </>
            ) : status.connection.websocket ? (
              <>
                <Wifi size={12} className="text-emerald-500" />
                <span className="hidden sm:inline text-emerald-500">Online</span>
              </>
            ) : (
              <>
                <Wifi size={12} />
                <span className="hidden sm:inline">Ready</span>
              </>
            )}
          </div>
        </LazyTooltip>
      </div>
    </div>
  );
};

export default ProjectAgentStatusBar;
