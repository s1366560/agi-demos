/**
 * ProjectAgentStatusBar - Project ReAct Agent Lifecycle Status Bar
 *
 * Displays the complete lifecycle state of the ProjectReActAgent:
 * - Sandbox status (with click-to-start and metrics popover)
 * - Lifecycle state (uninitialized, initializing, ready, executing, paused, error, shutting_down)
 * - Resource counts (tools, skills, subagents)
 * - Execution metrics (total/failed chats, active chats)
 * - Health status (uptime, last error)
 * - Lifecycle control buttons (start, stop, restart)
 *
 * This component now uses the unified agent status hook for consolidated state management.
 *
 * @module components/agent/ProjectAgentStatusBar
 */

import type { FC } from 'react';
import { useState, useCallback } from 'react';
import { LazyTooltip, LazyPopconfirm, message } from '@/components/ui/lazyAntd';
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
} from 'lucide-react';
import { useUnifiedAgentStatus, type ProjectAgentLifecycleState } from '../../hooks/useUnifiedAgentStatus';
import { SandboxStatusIndicator } from './sandbox/SandboxStatusIndicator';
import { agentService } from '../../services/agentService';

interface ProjectAgentStatusBarProps {
  /** Project ID */
  projectId: string;
  /** Tenant ID */
  tenantId: string;
  /** Number of messages */
  messageCount?: number;
}

/**
 * Lifecycle state configuration
 */
const lifecycleConfig: Record<
  ProjectAgentLifecycleState,
  {
    label: string;
    icon: React.ElementType;
    color: string;
    bgColor: string;
    description: string;
    animate?: boolean;
  }
> = {
  uninitialized: {
    label: '未启动',
    icon: Power,
    color: 'text-slate-500',
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    description: 'Agent 尚未初始化，将在首次请求时自动启动',
  },
  initializing: {
    label: '初始化中',
    icon: Loader2,
    color: 'text-blue-500',
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
    description: '正在加载工具、技能和配置',
    animate: true,
  },
  ready: {
    label: '就绪',
    icon: CheckCircle2,
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-100 dark:bg-emerald-900/30',
    description: 'Agent 已就绪，可以接收请求',
  },
  executing: {
    label: '执行中',
    icon: Cpu,
    color: 'text-amber-500',
    bgColor: 'bg-amber-100 dark:bg-amber-900/30',
    description: '正在处理聊天请求',
    animate: true,
  },
  paused: {
    label: '已暂停',
    icon: PauseCircle,
    color: 'text-orange-500',
    bgColor: 'bg-orange-100 dark:bg-orange-900/30',
    description: 'Agent 已暂停，不接收新请求',
  },
  error: {
    label: '错误',
    icon: AlertCircle,
    color: 'text-red-500',
    bgColor: 'bg-red-100 dark:bg-red-900/30',
    description: 'Agent 遇到错误',
  },
  shutting_down: {
    label: '关闭中',
    icon: Power,
    color: 'text-slate-500',
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    description: 'Agent 正在关闭',
    animate: true,
  },
};

/**
 * ProjectAgentStatusBar - Refactored to use unified status hook
 *
 * This component now uses the useUnifiedAgentStatus hook which consolidates:
 * - Lifecycle state (from useAgentLifecycleState via WebSocket)
 * - Execution state (from agentV3 store)
 * - Plan mode state (from planModeStore)
 * - Streaming state (from streamingStore)
 * - Sandbox connection (from sandboxStore)
 */
export const ProjectAgentStatusBar: FC<ProjectAgentStatusBarProps> = ({
  projectId,
  tenantId,
  messageCount = 0,
}) => {
  // Use the unified status hook for consolidated state (WebSocket-based)
  const { status, isLoading, error, isStreaming } = useUnifiedAgentStatus({
    projectId,
    tenantId,
    enabled: !!projectId,
  });

  // Lifecycle control state
  const [isActionPending, setIsActionPending] = useState(false);

  const lifecycleState = status.lifecycle;
  const config = lifecycleConfig[lifecycleState];

  const StatusIcon = config.icon;
  const isError = lifecycleState === 'error';

  // Check if agent can be started (not running)
  const canStart = lifecycleState === 'uninitialized' || lifecycleState === 'error';
  // Check if agent can be stopped (is running)
  const canStop = lifecycleState === 'ready' || lifecycleState === 'executing' || lifecycleState === 'paused';
  // Check if agent can be restarted (exists)
  const canRestart = lifecycleState !== 'uninitialized' && lifecycleState !== 'shutting_down' && lifecycleState !== 'initializing';

  // Lifecycle control handlers
  const handleStartAgent = useCallback(() => {
    setIsActionPending(true);
    agentService.startAgent(projectId);
    message.info('正在启动 Agent...');
    // Reset pending state after a delay (actual state will be updated via WebSocket)
    setTimeout(() => setIsActionPending(false), 3000);
  }, [projectId]);

  const handleStopAgent = useCallback(() => {
    setIsActionPending(true);
    agentService.stopAgent(projectId);
    message.info('正在停止 Agent...');
    setTimeout(() => setIsActionPending(false), 3000);
  }, [projectId]);

  const handleRestartAgent = useCallback(() => {
    setIsActionPending(true);
    agentService.restartAgent(projectId);
    message.info('正在重启 Agent...');
    setTimeout(() => setIsActionPending(false), 5000);
  }, [projectId]);

  return (
    <div className="px-4 py-1.5 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
      {/* Left: Sandbox Status, Lifecycle Status & Resources */}
      <div className="flex items-center gap-3">
        {/* Sandbox Status Indicator (First Column) */}
        <SandboxStatusIndicator
          projectId={projectId}
          tenantId={tenantId}
        />

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />

        {/* Agent Lifecycle Status */}
        <LazyTooltip
          title={
            <div className="space-y-2 max-w-xs">
              <div className="font-medium">{config.label}</div>
              <div className="text-xs opacity-80">{config.description}</div>
              {error && (
                <div className="text-xs text-red-400 pt-1 border-t border-gray-600 mt-1">
                  错误: {error}
                </div>
              )}
            </div>
          }
        >
          <div
            className={`
              flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
              ${config.bgColor} ${config.color}
              transition-all duration-300 cursor-help
            `}
          >
            <StatusIcon
              size={12}
              className={config.animate ? 'animate-spin' : ''}
            />
            <span>{config.label}</span>
            {status.resources.activeCalls > 0 ? (
              <span className="ml-0.5">({status.resources.activeCalls})</span>
            ) : null}
          </div>
        </LazyTooltip>

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />

        {/* Resources: Tools with detailed breakdown */}
        {status.toolStats.total > 0 && (
          <LazyTooltip
            title={
              <div className="space-y-1">
                <div className="font-medium">工具统计</div>
                <div>总工具: {status.toolStats.total}</div>
                <div>内置工具: {status.toolStats.builtin}</div>
                <div>MCP 工具: {status.toolStats.mcp}</div>
              </div>
            }
          >
            <div className="flex items-center gap-1.5 text-xs text-slate-500">
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
        )}

        {/* Resources: Skills with detailed breakdown */}
        {status.skillStats.total > 0 && (
          <LazyTooltip
            title={
              <div className="space-y-1">
                <div className="font-medium">技能统计</div>
                <div>总技能: {status.skillStats.total}</div>
                <div>已加载: {status.skillStats.loaded}</div>
              </div>
            }
          >
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <BrainCircuit size={11} />
              <span>{status.skillStats.loaded}/{status.skillStats.total}</span>
            </div>
          </LazyTooltip>
        )}

        {/* Message Count */}
        <LazyTooltip title="对话消息数">
          <div className="flex items-center gap-1 text-xs text-slate-500">
            <MessageSquare size={11} />
            <span>{messageCount}</span>
          </div>
        </LazyTooltip>

        {/* Plan Mode */}
        {status.planMode.isActive && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <LazyTooltip title={`${status.planMode.currentMode?.toUpperCase() || 'PLAN'} 模式 - Agent 正在创建详细计划`}>
              <div className="flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400">
                <Zap size={11} />
                <span>{status.planMode.currentMode === 'plan' ? '计划' : status.planMode.currentMode}</span>
              </div>
            </LazyTooltip>
          </>
        )}

        {/* Streaming Indicator */}
        {isStreaming && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <div className="flex items-center gap-1 text-xs text-amber-600">
              <Activity size={11} className="animate-pulse" />
              <span>流式响应中</span>
            </div>
          </>
        )}

        {/* Error Indicator */}
        {isError && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <LazyTooltip title={error || 'Agent 错误'}>
              <div className="flex items-center gap-1 text-xs text-red-500">
                <AlertTriangle size={11} />
                <span>错误</span>
              </div>
            </LazyTooltip>
          </>
        )}
      </div>

      {/* Right: Lifecycle Controls & Connection */}
      <div className="flex items-center gap-3 text-xs">
        {/* Lifecycle Control Buttons */}
        <div className="flex items-center gap-1.5">
          {/* Start Button - shown when agent is not running */}
          {canStart && (
            <LazyTooltip title="启动 Agent">
              <button
                type="button"
                onClick={handleStartAgent}
                disabled={isActionPending}
                className={`
                  p-1 rounded transition-colors
                  ${isActionPending 
                    ? 'text-slate-400 cursor-not-allowed' 
                    : 'text-emerald-600 hover:bg-emerald-100 dark:hover:bg-emerald-900/30'
                  }
                `}
              >
                {isActionPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Play size={14} />
                )}
              </button>
            </LazyTooltip>
          )}

          {/* Stop Button - shown when agent is running */}
          {canStop && (
            <LazyPopconfirm
              title="停止 Agent"
              description="确定要停止 Agent 吗？正在进行的任务将被中断。"
              onConfirm={handleStopAgent}
              okText="停止"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <LazyTooltip title="停止 Agent">
                <button
                  type="button"
                  disabled={isActionPending}
                  className={`
                    p-1 rounded transition-colors
                    ${isActionPending 
                      ? 'text-slate-400 cursor-not-allowed' 
                      : 'text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30'
                    }
                  `}
                >
                  {isActionPending ? (
                    <Loader2 size={14} className="animate-spin" />
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
              title="重启 Agent"
              description="重启将刷新工具和配置。确定要重启吗？"
              onConfirm={handleRestartAgent}
              okText="重启"
              cancelText="取消"
            >
              <LazyTooltip title="重启 Agent (刷新工具和配置)">
                <button
                  type="button"
                  disabled={isActionPending}
                  className={`
                    p-1 rounded transition-colors
                    ${isActionPending 
                      ? 'text-slate-400 cursor-not-allowed' 
                      : 'text-blue-500 hover:bg-blue-100 dark:hover:bg-blue-900/30'
                    }
                  `}
                >
                  {isActionPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <RefreshCw size={14} />
                  )}
                </button>
              </LazyTooltip>
            </LazyPopconfirm>
          )}
        </div>

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />

        {/* Connection & Activity Status - Combined */}
        <LazyTooltip
          title={
            <div className="space-y-1">
              <div>{isLoading ? '加载中...' : status.connection.websocket ? 'WebSocket 已连接' : '就绪'}</div>
              {status.resources.activeCalls > 0 && (
                <div>活跃工具调用: {status.resources.activeCalls}</div>
              )}
            </div>
          }
        >
          <div className="flex items-center gap-1.5 text-slate-400">
            {isLoading ? (
              <Loader2 size={12} className="animate-spin" />
            ) : status.resources.activeCalls > 0 ? (
              <>
                <Activity size={12} className="text-blue-500 animate-pulse" />
                <span className="text-blue-500">{status.resources.activeCalls} 调用中</span>
              </>
            ) : status.connection.websocket ? (
              <>
                <Wifi size={12} className="text-emerald-500" />
                <span className="text-emerald-500">在线</span>
              </>
            ) : (
              <>
                <Wifi size={12} />
                <span>就绪</span>
              </>
            )}
          </div>
        </LazyTooltip>
      </div>
    </div>
  );
};

export default ProjectAgentStatusBar;
